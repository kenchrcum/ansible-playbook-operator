from __future__ import annotations

from contextlib import suppress
from time import monotonic
from typing import Any

import kopf
from kubernetes import client, config
from prometheus_client import start_http_server

from . import logging as structured_logging
from . import metrics
from .builders.cronjob_builder import build_cronjob
from .builders.job_builder import build_connectivity_probe_job
from .constants import API_GROUP, API_GROUP_VERSION, COND_READY
from .services.git import GitService
from .utils.schedule import compute_computed_schedule

FINALIZER_REPOSITORY = f"{API_GROUP}/finalizer"


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_: Any) -> None:
    # Set up structured JSON logging
    structured_logging.setup_structured_logging()

    # Prefer SSA, set reasonable timeouts and workers
    # Use annotation-based diffbase storage to avoid conflicts with status.kopf field management.
    # Fallback to smart storages which adapt to cluster capabilities.
    try:
        settings.persistence.progress_storage = kopf.StatusProgressStorage()
        settings.persistence.diffbase_storage = kopf.AnnotationDiffBaseStorage()
    except Exception:
        settings.persistence.progress_storage = kopf.SmartProgressStorage()
    settings.posting.level = 0  # default
    settings.networking.request_timeout = 30.0
    settings.execution.max_workers = 4

    # Start metrics HTTP server (Prometheus) on :8080
    with suppress(Exception):
        start_http_server(8080)

    # Load cluster config if running in cluster; fallback to local for tests
    try:
        config.load_incluster_config()
    except Exception:
        try:
            config.load_kube_config()
        except Exception:
            # Running without kube config (e.g., unit tests)
            return


def _update_condition(
    status: dict[str, Any], type_: str, status_value: str, reason: str, message: str
) -> None:
    conditions = status.setdefault("conditions", [])
    # Replace any existing condition with the same type
    filtered = [c for c in conditions if c.get("type") != type_]
    filtered.append({"type": type_, "status": status_value, "reason": reason, "message": message})
    status["conditions"] = filtered


def _emit_event(
    *,
    kind: str,
    namespace: str,
    name: str,
    reason: str,
    message: str,
    type_: str = "Normal",
) -> None:
    try:
        v1 = client.CoreV1Api()
        involved = client.V1ObjectReference(
            api_version=API_GROUP_VERSION,
            kind=kind,
            name=name,
            namespace=namespace,
        )
        event = client.V1Event(
            metadata=client.V1ObjectMeta(generate_name=f"{name}-"),
            type=type_,
            reason=reason,
            message=message,
            involved_object=involved,
        )
        v1.create_namespaced_event(namespace=namespace, body=event)
    except Exception:
        # Events are best-effort
        pass


@kopf.on.create(API_GROUP_VERSION, "repositories")
@kopf.on.update(API_GROUP_VERSION, "repositories")
@kopf.on.resume(API_GROUP_VERSION, "repositories")
def reconcile_repository(
    spec: dict[str, Any],
    status: dict[str, Any],
    patch: kopf.Patch,
    name: str,
    namespace: str,
    uid: str,
    meta: kopf.Meta,
    **_: Any,
) -> None:
    started_at = monotonic()
    try:
        structured_logging.logger.info(
            "Starting repository reconciliation",
            controller="Repository",
            resource=f"{namespace}/{name}",
            uid=uid,
            event="reconcile",
            reason="ReconcileStarted",
        )
        # Handle finalizers
        if meta.get("deletionTimestamp"):
            # Repository is being deleted
            if FINALIZER_REPOSITORY in (meta.get("finalizers") or []):
                structured_logging.logger.info(
                    "Starting repository finalizer cleanup",
                    controller="Repository",
                    resource=f"{namespace}/{name}",
                    uid=uid,
                    event="finalizer",
                    reason="CleanupStarted",
                )

                # Clean up probe jobs
                batch_api = client.BatchV1Api()
                job_name = f"{name}-probe"
                cleanup_success = True

                try:
                    batch_api.delete_namespaced_job(
                        name=job_name,
                        namespace=namespace,
                        propagation_policy="Background",
                    )
                    structured_logging.logger.info(
                        "Probe job deletion initiated",
                        controller="Repository",
                        resource=f"{namespace}/{name}",
                        uid=uid,
                        event="finalizer",
                        reason="ProbeJobDeleted",
                        job_name=job_name,
                    )
                except client.exceptions.ApiException as e:
                    if e.status == 404:
                        structured_logging.logger.info(
                            "Probe job not found (already deleted)",
                            controller="Repository",
                            resource=f"{namespace}/{name}",
                            uid=uid,
                            event="finalizer",
                            reason="ProbeJobNotFound",
                            job_name=job_name,
                        )
                    else:
                        structured_logging.logger.error(
                            f"Failed to delete probe job: {str(e)}",
                            controller="Repository",
                            resource=f"{namespace}/{name}",
                            uid=uid,
                            event="finalizer",
                            reason="ProbeJobDeletionFailed",
                            job_name=job_name,
                            error=str(e),
                        )
                        cleanup_success = False

                # Remove finalizer
                finalizers = meta.get("finalizers", [])
                if FINALIZER_REPOSITORY in finalizers:
                    finalizers.remove(FINALIZER_REPOSITORY)
                    patch.meta["finalizers"] = finalizers

                    # Emit event for cleanup completion
                    event_reason = "CleanupSucceeded" if cleanup_success else "CleanupFailed"
                    event_message = (
                        "Repository finalizer cleanup completed successfully"
                        if cleanup_success
                        else "Repository finalizer cleanup completed with errors"
                    )
                    event_type = "Normal" if cleanup_success else "Warning"

                    _emit_event(
                        kind="Repository",
                        namespace=namespace,
                        name=name,
                        reason=event_reason,
                        message=event_message,
                        type_=event_type,
                    )

                    structured_logging.logger.info(
                        "Repository finalizer cleanup completed",
                        controller="Repository",
                        resource=f"{namespace}/{name}",
                        uid=uid,
                        event="finalizer",
                        reason=event_reason,
                        cleanup_success=cleanup_success,
                    )
            return

        # Add finalizer if not present
        if FINALIZER_REPOSITORY not in (meta.get("finalizers") or []):
            finalizers = meta.get("finalizers", [])
            finalizers.append(FINALIZER_REPOSITORY)
            patch.meta["finalizers"] = finalizers

            structured_logging.logger.info(
                "Added repository finalizer",
                controller="Repository",
                resource=f"{namespace}/{name}",
                uid=uid,
                event="finalizer",
                reason="FinalizerAdded",
            )

        # Minimal validation; deeper checks will be added later
        url = (spec or {}).get("url")
        if not url:
            _update_condition(
                patch.status, "AuthValid", "False", "MissingURL", "spec.url must be set"
            )
            _update_condition(
                patch.status, COND_READY, "False", "InvalidSpec", "Repository spec invalid"
            )
            _emit_event(
                kind="Repository",
                namespace=namespace,
                name=name,
                reason="ValidateFailed",
                message="Missing spec.url",
                type_="Warning",
            )
            return

        # Basic format checks
        auth = (spec or {}).get("auth") or {}
        method = auth.get("method")
        if method and not auth.get("secretRef", {}).get("name"):
            _update_condition(
                patch.status,
                "AuthValid",
                "False",
                "SecretMissing",
                "auth.secretRef.name must be set when auth.method is provided",
            )
            _update_condition(
                patch.status, COND_READY, "False", "InvalidSpec", "Repository auth invalid"
            )
            _emit_event(
                kind="Repository",
                namespace=namespace,
                name=name,
                reason="ValidateFailed",
                message="auth.method set but auth.secretRef.name missing",
                type_="Warning",
            )
            return

        # Check if known_hosts ConfigMap exists when strictHostKeyChecking is enabled
        ssh_cfg = (spec or {}).get("ssh") or {}
        known_hosts_cm = (ssh_cfg.get("knownHostsConfigMapRef") or {}).get("name")
        strict_host_key = ssh_cfg.get("strictHostKeyChecking", True)
        if strict_host_key and known_hosts_cm:
            try:
                v1 = client.CoreV1Api()
                v1.read_namespaced_config_map(known_hosts_cm, namespace)
            except client.exceptions.ApiException as e:
                if e.status == 404:
                    _update_condition(
                        patch.status,
                        "AuthValid",
                        "False",
                        "ConfigMapNotFound",
                        f"SSH known hosts ConfigMap '{known_hosts_cm}' not found",
                    )
                    _update_condition(
                        patch.status, COND_READY, "False", "InvalidSpec", "Repository auth invalid"
                    )
                    _emit_event(
                        kind="Repository",
                        namespace=namespace,
                        name=name,
                        reason="ValidateFailed",
                        message=f"SSH known hosts ConfigMap '{known_hosts_cm}' not found",
                        type_="Warning",
                    )
                    return

        # Build and apply connectivity probe Job
        job_manifest = build_connectivity_probe_job(
            repository_name=name,
            namespace=namespace,
            repository_spec=spec,
            owner_uid=uid,
        )

        batch_api = client.BatchV1Api()
        job_name = f"{name}-probe"

        # Create or patch the probe job
        try:
            batch_api.create_namespaced_job(
                namespace=namespace,
                body=job_manifest,
                field_manager="ansible-operator",
            )
        except client.exceptions.ApiException as e:
            if e.status == 409:
                # Job already exists; patch it
                batch_api.patch_namespaced_job(
                    name=job_name,
                    namespace=namespace,
                    body=job_manifest,
                    field_manager="ansible-operator",
                )
            else:
                raise

        # Set conditions to indicate probe is running
        # (status will be updated by job completion handler)
        _update_condition(
            patch.status, "AuthValid", "Unknown", "ProbeRunning", "Connectivity probe in progress"
        )
        _update_condition(
            patch.status, "CloneReady", "Unknown", "Deferred", "Waiting for connectivity probe"
        )
        _update_condition(
            patch.status, COND_READY, "Unknown", "Deferred", "Repository connectivity being probed"
        )

        structured_logging.logger.info(
            "Repository reconciliation completed successfully",
            controller="Repository",
            resource=f"{namespace}/{name}",
            uid=uid,
            event="reconcile",
            reason="ReconcileSucceeded",
        )
        metrics.RECONCILE_TOTAL.labels(kind="Repository", result="success").inc()
    except Exception as e:
        structured_logging.logger.error(
            f"Repository reconciliation failed: {str(e)}",
            controller="Repository",
            resource=f"{namespace}/{name}",
            uid=uid,
            event="reconcile",
            reason="ReconcileFailed",
        )
        metrics.RECONCILE_TOTAL.labels(kind="Repository", result="error").inc()
        raise
    finally:
        metrics.RECONCILE_DURATION.labels(kind="Repository").observe(monotonic() - started_at)


@kopf.on.event("batch", "v1", "jobs")
def handle_job_completion(event: dict[str, Any], **_: Any) -> None:
    """Handle Job completion events to update Repository status."""
    job = event.get("object", {})
    metadata = job.get("metadata", {})
    labels = metadata.get("labels", {})

    # Only handle connectivity probe jobs
    if labels.get("ansible.cloud37.dev/probe-type") != "connectivity":
        return

    job_name = metadata.get("name", "")
    namespace = metadata.get("namespace", "")

    # Extract repository name from job name (format: {repo-name}-probe)
    if not job_name.endswith("-probe"):
        return
    repository_name = job_name[:-6]  # Remove "-probe" suffix

    # Get repository owner reference to find the repository
    owner_refs = metadata.get("ownerReferences", [])
    if not owner_refs:
        return

    owner_ref = owner_refs[0]  # Should be the Repository
    if owner_ref.get("kind") != "Repository" or owner_ref.get("apiVersion") != API_GROUP_VERSION:
        return

    # Get current repository status
    api = client.CustomObjectsApi()
    try:
        api.get_namespaced_custom_object(
            group=API_GROUP,
            version="v1alpha1",
            namespace=namespace,
            plural="repositories",
            name=repository_name,
        )
    except client.exceptions.ApiException:
        # Repository might have been deleted
        return

    # Check job status
    status = job.get("status", {})
    succeeded = status.get("succeeded", 0)
    failed = status.get("failed", 0)

    # Update repository status based on job completion
    patch_body: dict[str, Any] = {"status": {}}

    if succeeded > 0:
        structured_logging.logger.info(
            "Repository connectivity probe succeeded",
            controller="Repository",
            resource=f"{namespace}/{repository_name}",
            uid=owner_ref.get("uid"),
            event="job",
            reason="ProbeSucceeded",
        )
        _update_condition(
            patch_body["status"],
            "AuthValid",
            "True",
            "ProbeSucceeded",
            "Connectivity probe successful",
        )
        _update_condition(
            patch_body["status"], "CloneReady", "True", "ProbeSucceeded", "Repository clone ready"
        )
        _update_condition(
            patch_body["status"],
            COND_READY,
            "True",
            "Validated",
            "Repository is ready for use",
        )
        _emit_event(
            kind="Repository",
            namespace=namespace,
            name=repository_name,
            reason="ValidateSucceeded",
            message="Repository connectivity and clone capability verified",
        )
    elif failed > 0:
        structured_logging.logger.warning(
            "Repository connectivity probe failed",
            controller="Repository",
            resource=f"{namespace}/{repository_name}",
            uid=owner_ref.get("uid"),
            event="job",
            reason="ProbeFailed",
        )
        _update_condition(
            patch_body["status"], "AuthValid", "False", "ProbeFailed", "Connectivity probe failed"
        )
        _update_condition(
            patch_body["status"],
            "CloneReady",
            "False",
            "ProbeFailed",
            "Cannot attempt clone without connectivity",
        )
        _update_condition(
            patch_body["status"],
            COND_READY,
            "False",
            "ProbeFailed",
            "Repository connectivity check failed",
        )
        _emit_event(
            kind="Repository",
            namespace=namespace,
            name=repository_name,
            reason="ValidateFailed",
            message="Repository connectivity check failed",
            type_="Warning",
        )

    # Apply the status update
    if patch_body["status"]:
        with suppress(Exception):
            api.patch_namespaced_custom_object_status(
                group=API_GROUP,
                version="v1alpha1",
                namespace=namespace,
                plural="repositories",
                name=repository_name,
                body=patch_body,
                field_manager="ansible-operator",
            )


@kopf.on.create(API_GROUP_VERSION, "playbooks")
@kopf.on.update(API_GROUP_VERSION, "playbooks")
@kopf.on.resume(API_GROUP_VERSION, "playbooks")
def reconcile_playbook(
    spec: dict[str, Any],
    status: dict[str, Any],
    patch: kopf.Patch,
    name: str,
    namespace: str,
    uid: str,
    **_: Any,
) -> None:
    started_at = monotonic()
    try:
        structured_logging.logger.info(
            "Starting playbook reconciliation",
            controller="Playbook",
            resource=f"{namespace}/{name}",
            uid=uid,
            event="reconcile",
            reason="ReconcileStarted",
        )
        repo_ref = (spec or {}).get("repositoryRef") or {}
        if not repo_ref.get("name"):
            _update_condition(
                patch.status,
                COND_READY,
                "False",
                "RepoRefMissing",
                "spec.repositoryRef.name must be set",
            )
            _emit_event(
                kind="Playbook",
                namespace=namespace,
                name=name,
                reason="ValidateFailed",
                message="spec.repositoryRef.name must be set",
                type_="Warning",
            )
            return

        # Validate playbook path is specified
        playbook_path = (spec or {}).get("playbookPath")
        if not playbook_path:
            _update_condition(
                patch.status,
                COND_READY,
                "False",
                "InvalidPath",
                "spec.playbookPath must be set",
            )
            _emit_event(
                kind="Playbook",
                namespace=namespace,
                name=name,
                reason="ValidateFailed",
                message="spec.playbookPath must be set",
                type_="Warning",
            )
            return

        # Check repository readiness
        git_service = GitService()
        repo_name = repo_ref.get("name")
        repo_namespace = repo_ref.get("namespace", namespace)

        is_repo_ready, repo_error = git_service.check_repository_readiness(
            str(repo_name), repo_namespace
        )
        if not is_repo_ready:
            _update_condition(
                patch.status,
                COND_READY,
                "False",
                "RepoNotReady",
                repo_error,
            )
            _emit_event(
                kind="Playbook",
                namespace=namespace,
                name=name,
                reason="ValidateFailed",
                message=f"Repository not ready: {repo_error}",
                type_="Warning",
            )
            return

        # Get repository spec for path validation
        try:
            custom_api = client.CustomObjectsApi()
            repository = custom_api.get_namespaced_custom_object(
                group="ansible.cloud37.dev",
                version="v1alpha1",
                namespace=repo_namespace,
                plural="repositories",
                name=repo_name,
            )
            repo_spec = repository.get("spec", {})
        except client.exceptions.ApiException as e:
            if e.status == 404:
                _update_condition(
                    patch.status,
                    COND_READY,
                    "False",
                    "RepoNotReady",
                    f"Repository {repo_name} not found",
                )
                _emit_event(
                    kind="Playbook",
                    namespace=namespace,
                    name=name,
                    reason="ValidateFailed",
                    message=f"Repository {repo_name} not found",
                    type_="Warning",
                )
                return
            else:
                raise

        # Validate paths exist in repository
        is_valid, validation_error = git_service.validate_repository_paths(
            repo_spec, spec, repo_namespace
        )
        if not is_valid:
            _update_condition(
                patch.status,
                COND_READY,
                "False",
                "InvalidPath",
                validation_error,
            )
            _emit_event(
                kind="Playbook",
                namespace=namespace,
                name=name,
                reason="ValidateFailed",
                message=f"Path validation failed: {validation_error}",
                type_="Warning",
            )
            return

        # All validations passed
        _update_condition(
            patch.status,
            COND_READY,
            "True",
            "Validated",
            "Playbook paths and repository validated successfully",
        )
        _emit_event(
            kind="Playbook",
            namespace=namespace,
            name=name,
            reason="ValidateSucceeded",
            message="Playbook validation completed successfully",
        )

        structured_logging.logger.info(
            "Playbook reconciliation completed successfully",
            controller="Playbook",
            resource=f"{namespace}/{name}",
            uid=uid,
            event="reconcile",
            reason="ReconcileSucceeded",
        )
        metrics.RECONCILE_TOTAL.labels(kind="Playbook", result="success").inc()
    except Exception as e:
        structured_logging.logger.error(
            f"Playbook reconciliation failed: {str(e)}",
            controller="Playbook",
            resource=f"{namespace}/{name}",
            uid=uid,
            event="reconcile",
            reason="ReconcileFailed",
        )
        metrics.RECONCILE_TOTAL.labels(kind="Playbook", result="error").inc()
        raise
    finally:
        metrics.RECONCILE_DURATION.labels(kind="Playbook").observe(monotonic() - started_at)


@kopf.on.create(API_GROUP_VERSION, "schedules")
@kopf.on.update(API_GROUP_VERSION, "schedules")
@kopf.on.resume(API_GROUP_VERSION, "schedules")
def reconcile_schedule(
    spec: dict[str, Any],
    status: dict[str, Any],
    patch: kopf.Patch,
    name: str,
    namespace: str,
    uid: str,
    **_: Any,
) -> None:
    started_at = monotonic()
    try:
        structured_logging.logger.info(
            "Starting schedule reconciliation",
            controller="Schedule",
            resource=f"{namespace}/{name}",
            uid=uid,
            event="reconcile",
            reason="ReconcileStarted",
        )
        # Compute computedSchedule from spec.schedule (supports random macros)
        schedule_expr = (spec or {}).get("schedule") or ""
        computed, used_macro = compute_computed_schedule(schedule_expr, uid)
        patch.status["computedSchedule"] = computed

        # Basic stubbing for CronJob rendering; actual apply via SSA will come later
        playbook_ref = (spec or {}).get("playbookRef") or {}
        if not playbook_ref.get("name"):
            _update_condition(
                patch.status,
                COND_READY,
                "False",
                "PlaybookRefMissing",
                "spec.playbookRef.name must be set",
            )
            _emit_event(
                kind="Schedule",
                namespace=namespace,
                name=name,
                reason="ValidateFailed",
                message="spec.playbookRef.name must be set",
                type_="Warning",
            )
            return

        # Fetch referenced Playbook and its Repository (best-effort)
        api = client.CustomObjectsApi()
        playbook_obj: dict[str, Any] = {}
        try:
            playbook_obj = api.get_namespaced_custom_object(
                group=API_GROUP,
                version="v1alpha1",
                namespace=namespace,
                plural="playbooks",
                name=playbook_ref["name"],
            )
        except Exception:
            playbook_obj = {"spec": {"runtime": {}}}

        repository_obj: dict[str, Any] | None = None
        known_hosts_available: bool = False
        try:
            repo_ref = (playbook_obj.get("spec") or {}).get("repositoryRef") or {}
            if repo_ref.get("name"):
                repository_obj = api.get_namespaced_custom_object(
                    group=API_GROUP,
                    version="v1alpha1",
                    namespace=namespace,
                    plural="repositories",
                    name=repo_ref["name"],
                )
                # Check if known hosts ConfigMap exists (optional for non-strict mode)
                if repository_obj:
                    repo_spec = repository_obj.get("spec") or {}
                    ssh_cfg = repo_spec.get("ssh") or {}
                    known_hosts_cm = (ssh_cfg.get("knownHostsConfigMapRef") or {}).get("name")
                    if known_hosts_cm:
                        try:
                            v1 = client.CoreV1Api()
                            v1.read_namespaced_config_map(known_hosts_cm, namespace)
                            known_hosts_available = True
                        except client.exceptions.ApiException as e:
                            if e.status == 404 and ssh_cfg.get("strictHostKeyChecking", True):
                                _emit_event(
                                    kind="Schedule",
                                    namespace=namespace,
                                    name=name,
                                    reason="ConfigMapNotFound",
                                    message=f"SSH known hosts ConfigMap '{known_hosts_cm}' \
                                        not found - pod will fail with strict checking",
                                    type_="Warning",
                                )
                                # For non-strict mode, we don't mount the ConfigMap but continue
        except Exception:
            repository_obj = None

        cj_manifest = build_cronjob(
            schedule_name=name,
            namespace=namespace,
            computed_schedule=computed,
            playbook=playbook_obj,
            repository=repository_obj,
            known_hosts_available=known_hosts_available,
            schedule_spec=spec,
            owner_uid=uid,
            owner_api_version=f"{API_GROUP}/v1alpha1",
            owner_kind="Schedule",
            owner_name=name,
        )

        # Apply via Server-Side Apply (SSA) with our field manager — create or patch.
        batch_api = client.BatchV1Api()
        try:
            # Try to create first (SSA apply)
            batch_api.create_namespaced_cron_job(
                namespace=namespace,
                body=cj_manifest,
                field_manager="ansible-operator",
            )
        except client.exceptions.ApiException as e:
            if e.status == 409:
                # Already exists; patch with SSA apply
                batch_api.patch_namespaced_cron_job(
                    name=name,
                    namespace=namespace,
                    body=cj_manifest,
                    field_manager="ansible-operator",
                )
            else:
                raise

        structured_logging.logger.info(
            "CronJob applied via SSA",
            controller="Schedule",
            resource=f"{namespace}/{name}",
            uid=uid,
            event="reconcile",
            reason="CronJobApplied",
        )
        _emit_event(
            kind="Schedule",
            namespace=namespace,
            name=name,
            reason="CronJobApplied",
            message="CronJob applied via SSA",
        )

        _update_condition(patch.status, COND_READY, "True", "Applied", "CronJob applied with SSA")
        structured_logging.logger.info(
            "Schedule reconciliation completed successfully",
            controller="Schedule",
            resource=f"{namespace}/{name}",
            uid=uid,
            event="reconcile",
            reason="ReconcileSucceeded",
        )
        metrics.RECONCILE_TOTAL.labels(kind="Schedule", result="success").inc()
    except Exception as e:
        structured_logging.logger.error(
            f"Schedule reconciliation failed: {str(e)}",
            controller="Schedule",
            resource=f"{namespace}/{name}",
            uid=uid,
            event="reconcile",
            reason="ReconcileFailed",
        )
        metrics.RECONCILE_TOTAL.labels(kind="Schedule", result="error").inc()
        raise
    finally:
        metrics.RECONCILE_DURATION.labels(kind="Schedule").observe(monotonic() - started_at)


# Finalizers (no-op placeholders for now)
@kopf.on.delete(API_GROUP_VERSION, "schedules")
def on_delete_schedule(name: str, namespace: str, **_: Any) -> None:
    return
