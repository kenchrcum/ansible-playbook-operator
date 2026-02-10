from __future__ import annotations

import os
from contextlib import suppress
from datetime import UTC, datetime
from time import monotonic
from typing import Any

import kopf
from kubernetes import client, config
from prometheus_client import start_http_server

from . import logging as structured_logging
from . import metrics
from .builders.cronjob_builder import build_cronjob
from .builders.job_builder import build_connectivity_probe_job
from .constants import (
    ANNOTATION_OWNER_UID,
    API_GROUP,
    API_GROUP_VERSION,
    COND_BLOCKED_BY_CONCURRENCY,
    COND_READY,
    EXECUTOR_SERVICE_ACCOUNT_ENV,
    LABEL_MANAGED_BY,
    LABEL_OWNER_NAME,
    LABEL_OWNER_UID,
    LABEL_RUN_ID,
)
from .services.dependencies import dependency_service
from .services.git import GitService
from .services.manual_run import manual_run_service
from .utils.schedule import compute_computed_schedule

FINALIZER_REPOSITORY = f"{API_GROUP}/finalizer"


def _get_executor_service_account() -> str | None:
    """Get the executor ServiceAccount name from environment variable."""
    return os.getenv(EXECUTOR_SERVICE_ACCOUNT_ENV)


def _can_safely_adopt_cronjob(
    existing_cj: Any, owner_uid: str, owner_name: str, namespace: str
) -> tuple[bool, str]:
    """Check if an existing CronJob can be safely adopted by this Schedule.

    Returns:
        Tuple of (can_adopt: bool, reason: str)
    """
    metadata = existing_cj.metadata
    labels = metadata.labels or {}
    annotations = metadata.annotations or {}

    # Check if already managed by ansible-operator
    if labels.get(LABEL_MANAGED_BY) == "ansible-operator":
        # Check if owner UID matches (via label or annotation)
        existing_owner_uid = labels.get(LABEL_OWNER_UID) or annotations.get(ANNOTATION_OWNER_UID)
        if existing_owner_uid == owner_uid:
            return True, "matching owner UID"
        else:
            return False, f"different owner UID: existing={existing_owner_uid}, current={owner_uid}"

    # Check if owner references match
    owner_refs = metadata.owner_references or []
    for ref in owner_refs:
        if ref.kind == "Schedule" and ref.name == owner_name and ref.uid == owner_uid:
            return True, "matching owner reference"

    # Check if UID annotation matches (for manual adoption)
    existing_uid_annotation = annotations.get(ANNOTATION_OWNER_UID)
    if existing_uid_annotation == owner_uid:
        return True, "matching UID annotation"

    # Not safe to adopt
    return False, "no matching ownership indicators (labels, owner references, or UID annotation)"


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


@kopf.on.startup()
def rebuild_dependency_indices(**_: Any) -> None:
    """Rebuild dependency indices on operator startup to ensure cross-resource triggers work."""
    structured_logging.logger.info(
        "Rebuilding dependency indices after operator restart",
        event="startup",
        reason="IndexRebuild",
    )

    try:
        api = client.CustomObjectsApi()

        # Get all namespaces to scan based on watch scope
        namespaces = []
        watch_scope = os.getenv("WATCH_SCOPE", "namespace")

        if watch_scope == "all":
            # Get all namespaces for cluster-wide operation
            try:
                v1 = client.CoreV1Api()
                ns_list = v1.list_namespace()
                namespaces = [ns.metadata.name for ns in ns_list.items]
            except Exception:
                # Fallback to default namespace if we can't list namespaces
                namespaces = ["default"]
        else:
            # Single namespace operation - get current namespace
            try:
                current_ns = os.getenv("POD_NAMESPACE", "default")
                namespaces = [current_ns]
            except Exception:
                namespaces = ["default"]

        # Rebuild all dependency indices
        dependency_service.rebuild_all_indices(namespaces)

        structured_logging.logger.info(
            f"Rebuilt dependency indices for {len(namespaces)} namespaces",
            event="startup",
            reason="IndexRebuild",
            namespaces=namespaces,
        )

    except Exception as e:
        structured_logging.logger.error(
            f"Failed to rebuild dependency indices: {e}",
            event="startup",
            reason="IndexRebuildFailed",
            error=str(e),
        )


@kopf.on.startup()
def reconcile_orphaned_probe_jobs(**_: Any) -> None:
    """Detect and reconcile orphaned repository probe jobs after operator restart."""
    structured_logging.logger.info(
        "Checking for orphaned repository probe jobs after operator restart",
        event="startup",
        reason="ProbeJobReconciliation",
    )

    try:
        batch_api = client.BatchV1Api()
        api = client.CustomObjectsApi()

        # Get all namespaces to scan based on watch scope
        namespaces = []
        watch_scope = os.getenv("WATCH_SCOPE", "namespace")

        if watch_scope == "all":
            # Get all namespaces for cluster-wide operation
            try:
                v1 = client.CoreV1Api()
                ns_list = v1.list_namespace()
                namespaces = [ns.metadata.name for ns in ns_list.items]
            except Exception:
                # Fallback to default namespace if we can't list namespaces
                namespaces = ["default"]
        else:
            # Single namespace operation - get current namespace
            try:
                current_ns = os.getenv("POD_NAMESPACE", "default")
                namespaces = [current_ns]
            except Exception:
                namespaces = ["default"]

        orphaned_jobs_found = 0
        reconciled_jobs = 0

        for namespace in namespaces:
            try:
                # List all jobs with connectivity probe label
                jobs = batch_api.list_namespaced_job(
                    namespace=namespace,
                    label_selector="ansible.cloud37.dev/probe-type=connectivity",
                )

                for job in jobs.items:
                    orphaned_jobs_found += 1
                    job_name = job.metadata.name
                    job_status = job.status

                    # Check if job is completed (succeeded or failed)
                    succeeded = job_status.succeeded or 0
                    failed = job_status.failed or 0

                    if succeeded > 0 or failed > 0:
                        # Job is completed, reconcile repository status
                        if job_name.endswith("-probe"):
                            repository_name = job_name[:-6]  # Remove "-probe" suffix

                            # Check if repository still exists
                            try:
                                repository = api.get_namespaced_custom_object(
                                    group=API_GROUP,
                                    version="v1alpha1",
                                    namespace=namespace,
                                    plural="repositories",
                                    name=repository_name,
                                )

                                # Update repository status based on job completion
                                patch_body: dict[str, Any] = {"status": {}}

                                if succeeded > 0:
                                    structured_logging.logger.info(
                                        "Reconciling orphaned probe job - succeeded",
                                        event="startup",
                                        reason="ProbeJobReconciled",
                                        job_name=job_name,
                                        repository=f"{namespace}/{repository_name}",
                                    )
                                    _update_condition(
                                        patch_body["status"],
                                        "AuthValid",
                                        "True",
                                        "ProbeSucceeded",
                                        "Connectivity probe successful (reconciled)",
                                    )
                                    _update_condition(
                                        patch_body["status"],
                                        "CloneReady",
                                        "True",
                                        "ProbeSucceeded",
                                        "Repository clone ready (reconciled)",
                                    )
                                    _update_condition(
                                        patch_body["status"],
                                        COND_READY,
                                        "True",
                                        "Validated",
                                        "Repository is ready for use (reconciled)",
                                    )
                                else:  # failed > 0
                                    structured_logging.logger.info(
                                        "Reconciling orphaned probe job - failed",
                                        event="startup",
                                        reason="ProbeJobReconciled",
                                        job_name=job_name,
                                        repository=f"{namespace}/{repository_name}",
                                    )
                                    _update_condition(
                                        patch_body["status"],
                                        "AuthValid",
                                        "False",
                                        "ProbeFailed",
                                        "Connectivity probe failed (reconciled)",
                                    )
                                    _update_condition(
                                        patch_body["status"],
                                        "CloneReady",
                                        "False",
                                        "ProbeFailed",
                                        "Cannot attempt clone without connectivity (reconciled)",
                                    )
                                    _update_condition(
                                        patch_body["status"],
                                        COND_READY,
                                        "False",
                                        "ProbeFailed",
                                        "Repository connectivity check failed (reconciled)",
                                    )

                                # Apply the status update
                                if patch_body["status"]:
                                    api.patch_namespaced_custom_object_status(
                                        group=API_GROUP,
                                        version="v1alpha1",
                                        namespace=namespace,
                                        plural="repositories",
                                        name=repository_name,
                                        body=patch_body,
                                        field_manager="ansible-operator",
                                    )
                                    reconciled_jobs += 1

                                    # Trigger dependent Playbooks when Repository becomes ready
                                    if succeeded > 0:
                                        dependency_service.requeue_dependent_playbooks(
                                            namespace, repository_name
                                        )

                            except client.exceptions.ApiException as e:
                                if e.status == 404:
                                    # Repository was deleted, job will be cleaned up by owner reference
                                    structured_logging.logger.info(
                                        "Orphaned probe job found but repository deleted",
                                        event="startup",
                                        reason="ProbeJobOrphaned",
                                        job_name=job_name,
                                        repository=f"{namespace}/{repository_name}",
                                    )
                                else:
                                    raise

            except Exception as e:
                structured_logging.logger.warning(
                    f"Failed to reconcile probe jobs in namespace {namespace}: {e}",
                    event="startup",
                    reason="ProbeJobReconciliationFailed",
                    namespace=namespace,
                    error=str(e),
                )

        structured_logging.logger.info(
            f"Reconciled {reconciled_jobs} orphaned probe jobs out of {orphaned_jobs_found} found",
            event="startup",
            reason="ProbeJobReconciliation",
            orphaned_jobs_found=orphaned_jobs_found,
            reconciled_jobs=reconciled_jobs,
        )

    except Exception as e:
        structured_logging.logger.error(
            f"Failed to reconcile orphaned probe jobs: {e}",
            event="startup",
            reason="ProbeJobReconciliationFailed",
            error=str(e),
        )


def _update_condition(
    status: dict[str, Any], type_: str, status_value: str, reason: str, message: str
) -> None:
    conditions = status.setdefault("conditions", [])
    # Replace any existing condition with the same type
    filtered = [c for c in conditions if c.get("type") != type_]
    filtered.append({"type": type_, "status": status_value, "reason": reason, "message": message})
    status["conditions"] = filtered


def _check_concurrent_jobs(namespace: str, schedule_name: str, owner_uid: str) -> tuple[bool, str]:
    """
    Check if there are currently running Jobs for this Schedule.
    Returns (has_concurrent_jobs, blocking_reason).
    """
    try:
        batch_api = client.BatchV1Api()
        # List Jobs in the namespace with our owner label
        jobs = batch_api.list_namespaced_job(
            namespace=namespace,
            label_selector=f"{LABEL_OWNER_UID}={owner_uid}",
        )

        # Check for active (running) jobs
        active_jobs = []
        for job in jobs.items:
            status = job.status
            # Job is considered active if it's not completed or failed
            if (status.active is not None and status.active > 0) or (
                status.succeeded is None and status.failed is None
            ):
                active_jobs.append(job.metadata.name)

        if active_jobs:
            return True, f"Active Jobs: {', '.join(active_jobs)}"

        return False, ""
    except Exception:
        # If we can't check, assume no blocking (fail open)
        return False, ""


def _update_schedule_conditions(
    patch_status: dict[str, Any],
    namespace: str,
    schedule_name: str,
    uid: str,
    spec: dict[str, Any],
    cronjob_exists: bool = True,
    playbook_ready: bool = True,
    current_status: dict[str, Any] | None = None,
) -> None:
    """
    Update Schedule conditions based on current state.
    """
    concurrency_policy = spec.get("concurrencyPolicy", "Forbid")

    # Check for concurrent jobs for all policies (to set BlockedByConcurrency condition)
    has_concurrent_jobs, blocking_reason = _check_concurrent_jobs(namespace, schedule_name, uid)

    # Get current conditions for comparison
    current_conditions = {}
    if current_status:
        for condition in current_status.get("conditions", []):
            current_conditions[condition.get("type")] = condition

    # Update BlockedByConcurrency condition
    new_blocked_status = "True" if has_concurrent_jobs else "False"
    new_blocked_reason = "ConcurrentJobsRunning" if has_concurrent_jobs else "NoConcurrentJobs"
    new_blocked_message = (
        f"Schedule blocked by concurrency policy: {blocking_reason}"
        if has_concurrent_jobs
        else "No concurrent Jobs running"
    )

    current_blocked = current_conditions.get(COND_BLOCKED_BY_CONCURRENCY, {})
    if (
        current_blocked.get("status") != new_blocked_status
        or current_blocked.get("reason") != new_blocked_reason
    ):
        _update_condition(
            patch_status,
            COND_BLOCKED_BY_CONCURRENCY,
            new_blocked_status,
            new_blocked_reason,
            new_blocked_message,
        )

        # Emit event for condition change
        event_type = "Warning" if has_concurrent_jobs else "Normal"
        _emit_event(
            kind="Schedule",
            namespace=namespace,
            name=schedule_name,
            reason="ConditionChanged",
            message=f"BlockedByConcurrency condition changed to {new_blocked_status}: {new_blocked_message}",
            type_=event_type,
        )

    # Update Ready condition based on overall state
    if not cronjob_exists:
        new_ready_status = "False"
        new_ready_reason = "CronJobMissing"
        new_ready_message = "CronJob not found or not created"
    elif not playbook_ready:
        new_ready_status = "False"
        new_ready_reason = "PlaybookNotReady"
        new_ready_message = "Referenced Playbook is not ready"
    elif has_concurrent_jobs and concurrency_policy == "Forbid":
        new_ready_status = "False"
        new_ready_reason = "BlockedByConcurrency"
        new_ready_message = f"Schedule blocked by concurrency policy: {blocking_reason}"
    else:
        new_ready_status = "True"
        new_ready_reason = "Ready"
        new_ready_message = "Schedule is ready and CronJob is active"

    current_ready = current_conditions.get(COND_READY, {})
    if (
        current_ready.get("status") != new_ready_status
        or current_ready.get("reason") != new_ready_reason
    ):
        _update_condition(
            patch_status,
            COND_READY,
            new_ready_status,
            new_ready_reason,
            new_ready_message,
        )

        # Emit event for condition change
        event_type = "Warning" if new_ready_status == "False" else "Normal"
        _emit_event(
            kind="Schedule",
            namespace=namespace,
            name=schedule_name,
            reason="ConditionChanged",
            message=f"Ready condition changed to {new_ready_status}: {new_ready_message}",
            type_=event_type,
        )


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
    metrics.RECONCILE_TOTAL.labels(kind="Repository", result="started").inc()
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
            executor_service_account=_get_executor_service_account(),
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
            # New job created, set conditions to indicate probe is running
            _update_condition(
                patch.status,
                "AuthValid",
                "Unknown",
                "ProbeRunning",
                "Connectivity probe in progress",
            )
            _update_condition(
                patch.status, "CloneReady", "Unknown", "Deferred", "Waiting for connectivity probe"
            )
            _update_condition(
                patch.status,
                COND_READY,
                "Unknown",
                "Deferred",
                "Repository connectivity being probed",
            )
        except Exception as e:
            if hasattr(e, "status") and e.status == 409:
                # Job already exists; check its status and patch if needed
                try:
                    existing_job = batch_api.read_namespaced_job(name=job_name, namespace=namespace)
                    job_status = existing_job.status
                    succeeded = job_status.succeeded or 0
                    failed = job_status.failed or 0

                    if succeeded > 0:
                        # Job already succeeded, update repository status immediately
                        structured_logging.logger.info(
                            "Existing probe job already succeeded, updating repository status",
                            controller="Repository",
                            resource=f"{namespace}/{name}",
                            uid=uid,
                            event="reconcile",
                            reason="ProbeAlreadySucceeded",
                            job_name=job_name,
                        )
                        _update_condition(
                            patch.status,
                            "AuthValid",
                            "True",
                            "ProbeSucceeded",
                            "Connectivity probe successful",
                        )
                        _update_condition(
                            patch.status,
                            "CloneReady",
                            "True",
                            "ProbeSucceeded",
                            "Repository clone ready",
                        )
                        _update_condition(
                            patch.status,
                            COND_READY,
                            "True",
                            "Validated",
                            "Repository is ready for use",
                        )
                    elif failed > 0:
                        # Job already failed, update repository status immediately
                        structured_logging.logger.info(
                            "Existing probe job already failed, updating repository status",
                            controller="Repository",
                            resource=f"{namespace}/{name}",
                            uid=uid,
                            event="reconcile",
                            reason="ProbeAlreadyFailed",
                            job_name=job_name,
                        )
                        _update_condition(
                            patch.status,
                            "AuthValid",
                            "False",
                            "ProbeFailed",
                            "Connectivity probe failed",
                        )
                        _update_condition(
                            patch.status,
                            "CloneReady",
                            "False",
                            "ProbeFailed",
                            "Cannot attempt clone without connectivity",
                        )
                        _update_condition(
                            patch.status,
                            COND_READY,
                            "False",
                            "ProbeFailed",
                            "Repository connectivity check failed",
                        )
                    else:
                        # Job is still running, patch it and set running conditions
                        batch_api.patch_namespaced_job(
                            name=job_name,
                            namespace=namespace,
                            body=job_manifest,
                            field_manager="ansible-operator",
                        )
                        _update_condition(
                            patch.status,
                            "AuthValid",
                            "Unknown",
                            "ProbeRunning",
                            "Connectivity probe in progress",
                        )
                        _update_condition(
                            patch.status,
                            "CloneReady",
                            "Unknown",
                            "Deferred",
                            "Waiting for connectivity probe",
                        )
                        _update_condition(
                            patch.status,
                            COND_READY,
                            "Unknown",
                            "Deferred",
                            "Repository connectivity being probed",
                        )
                except Exception as job_e:
                    if hasattr(job_e, "status") and job_e.status == 404:
                        # Job was deleted between creation attempt and read, create it
                        batch_api.create_namespaced_job(
                            namespace=namespace,
                            body=job_manifest,
                            field_manager="ansible-operator",
                        )
                        _update_condition(
                            patch.status,
                            "AuthValid",
                            "Unknown",
                            "ProbeRunning",
                            "Connectivity probe in progress",
                        )
                        _update_condition(
                            patch.status,
                            "CloneReady",
                            "Unknown",
                            "Deferred",
                            "Waiting for connectivity probe",
                        )
                        _update_condition(
                            patch.status,
                            COND_READY,
                            "Unknown",
                            "Deferred",
                            "Repository connectivity being probed",
                        )
                    else:
                        raise
            else:
                raise

        # Index dependencies and trigger dependent Playbooks
        dependency_service.index_repository_dependencies(namespace, name)
        dependency_service.requeue_dependent_playbooks(namespace, name)

        structured_logging.logger.info(
            "Repository reconciliation completed successfully",
            controller="Repository",
            resource=f"{namespace}/{name}",
            uid=uid,
            event="reconcile",
            reason="ReconcileSucceeded",
        )
        metrics.RECONCILE_TOTAL.labels(kind="Repository", result="success").inc()
        metrics.RECONCILE_DURATION.labels(kind="Repository").observe(monotonic() - started_at)
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
        metrics.RECONCILE_DURATION.labels(kind="Repository").observe(monotonic() - started_at)
        raise


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
        metrics.JOB_RUNS_TOTAL.labels(kind="Repository", result="success").inc()
        # Record job duration
        start_time = status.get("startTime")
        completion_time = status.get("completionTime")
        if start_time and completion_time:
            # Parse ISO timestamps and calculate duration
            try:
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                completion_dt = datetime.fromisoformat(completion_time.replace("Z", "+00:00"))
                duration_seconds = (completion_dt - start_dt).total_seconds()
                metrics.JOB_RUN_DURATION.labels(kind="Repository").observe(duration_seconds)
            except Exception:
                pass  # Ignore parsing errors
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

        # Trigger dependent Playbooks when Repository becomes ready
        dependency_service.requeue_dependent_playbooks(namespace, repository_name)
    elif failed > 0:
        metrics.JOB_RUNS_TOTAL.labels(kind="Repository", result="failure").inc()
        # Record job duration
        start_time = status.get("startTime")
        completion_time = status.get("completionTime")
        if start_time and completion_time:
            # Parse ISO timestamps and calculate duration
            try:
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                completion_dt = datetime.fromisoformat(completion_time.replace("Z", "+00:00"))
                duration_seconds = (completion_dt - start_dt).total_seconds()
                metrics.JOB_RUN_DURATION.labels(kind="Repository").observe(duration_seconds)
            except Exception:
                pass  # Ignore parsing errors
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


@kopf.on.event("batch", "v1", "jobs")
def handle_manual_run_job_completion(event: dict[str, Any], **_: Any) -> None:
    """Handle manual run Job completion events to update Playbook status."""
    job = event.get("object", {})
    metadata = job.get("metadata", {})
    labels = metadata.get("labels", {})

    # Only handle manual run jobs
    if labels.get("ansible.cloud37.dev/run-type") != "manual":
        return

    job_name = metadata.get("name", "")
    namespace = metadata.get("namespace", "")
    run_id = labels.get(LABEL_RUN_ID)
    owner_uid = labels.get(LABEL_OWNER_UID)
    owner_name = labels.get(LABEL_OWNER_NAME)

    if not run_id or not owner_uid or not owner_name:
        return

    # Parse owner name (format: namespace.playbook-name)
    if "." not in owner_name:
        return
    owner_namespace, playbook_name = owner_name.split(".", 1)

    # Only process if in the same namespace
    if owner_namespace != namespace:
        return

    # Get Job status
    status = job.get("status", {})

    # Only process completed jobs - check for completion conditions
    # A Job is complete when it has succeeded or failed AND has a completionTime
    # or when the Job has terminal conditions
    completion_time_str = status.get("completionTime")
    conditions = status.get("conditions", [])

    # Check if job has reached a terminal state
    is_complete = False
    is_failed = False

    for condition in conditions:
        if condition.get("type") == "Complete" and condition.get("status") == "True":
            is_complete = True
            break
        if condition.get("type") == "Failed" and condition.get("status") == "True":
            is_complete = True
            is_failed = True
            break

    # If no terminal condition and no completion time, job is still running
    if not is_complete and not completion_time_str:
        return

    succeeded = status.get("succeeded", 0)
    failed = status.get("failed", 0)
    completion_time = completion_time_str or datetime.now(UTC).isoformat()

    # Determine final status based on terminal conditions
    if succeeded > 0 and not is_failed:
        metrics.JOB_RUNS_TOTAL.labels(kind="Playbook", result="success").inc()
        # Record job duration
        start_time = status.get("startTime")
        completion_time = status.get("completionTime")
        if start_time and completion_time:
            try:
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                completion_dt = datetime.fromisoformat(completion_time.replace("Z", "+00:00"))
                duration_seconds = (completion_dt - start_dt).total_seconds()
                metrics.JOB_RUN_DURATION.labels(kind="Playbook").observe(duration_seconds)
            except Exception:
                pass  # Ignore parsing errors
        final_status = "Succeeded"
        reason = "JobSucceeded"
        message = "Manual run completed successfully"
        event_type = "Normal"
    elif is_failed or failed > 0:
        metrics.JOB_RUNS_TOTAL.labels(kind="Playbook", result="failure").inc()
        # Record job duration
        start_time = status.get("startTime")
        completion_time_actual = status.get("completionTime")
        if start_time and completion_time_actual:
            try:
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                completion_dt = datetime.fromisoformat(
                    completion_time_actual.replace("Z", "+00:00")
                )
                duration_seconds = (completion_dt - start_dt).total_seconds()
                metrics.JOB_RUN_DURATION.labels(kind="Playbook").observe(duration_seconds)
            except Exception:
                pass  # Ignore parsing errors
        final_status = "Failed"
        reason = "JobFailed"
        message = "Manual run failed"
        event_type = "Warning"
    else:
        # Job completed but without clear success or failure - shouldn't happen
        return

    # Update Playbook status
    manual_run_service.update_playbook_manual_run_status(
        playbook_name=playbook_name,
        namespace=namespace,
        run_id=run_id,
        job_name=job_name,
        status=final_status,
        reason=reason,
        message=message,
        completion_time=completion_time,
    )

    # Emit event
    _emit_event(
        kind="Playbook",
        namespace=namespace,
        name=playbook_name,
        reason=f"Job{final_status}",
        message=f"Manual run Job '{job_name}' {final_status.lower()}: {message}",
        type_=event_type,
    )

    structured_logging.logger.info(
        f"Manual run Job {final_status.lower()}",
        controller="Playbook",
        resource=f"{namespace}/{playbook_name}",
        uid=owner_uid,
        event="manual-run",
        reason=reason,
        run_id=run_id,
        job_name=job_name,
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
    meta: kopf.Meta,
    **_: Any,
) -> None:
    started_at = monotonic()
    metrics.RECONCILE_TOTAL.labels(kind="Playbook", result="started").inc()
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

        # Check for manual run request
        annotations = meta.get("annotations", {})
        run_id = manual_run_service.detect_manual_run_request(annotations)
        if run_id:
            # Check if a job with this run ID already exists to prevent duplicates
            batch_api = client.BatchV1Api()
            try:
                job_list = batch_api.list_namespaced_job(
                    namespace=namespace,
                    label_selector=f"{LABEL_RUN_ID}={run_id}",
                )
                if job_list.items:
                    # Job already exists for this run ID, clear annotation and skip
                    structured_logging.logger.info(
                        "Manual run Job already exists for run ID",
                        controller="Playbook",
                        resource=f"{namespace}/{name}",
                        uid=uid,
                        event="manual-run",
                        reason="JobAlreadyExists",
                        run_id=run_id,
                    )
                    manual_run_service.clear_manual_run_annotation(name, namespace)
                    return
            except Exception:
                # If we can't check, proceed with caution
                pass

            # Get repository object for manual run
            repository_obj: dict[str, Any] | None = None
            known_hosts_available: bool = False
            try:
                repo_ref = (spec or {}).get("repositoryRef") or {}
                if repo_ref.get("name"):
                    custom_api = client.CustomObjectsApi()
                    repository_obj = custom_api.get_namespaced_custom_object(
                        group=API_GROUP,
                        version="v1alpha1",
                        namespace=namespace,
                        plural="repositories",
                        name=repo_ref["name"],
                    )
                    # Check if known hosts ConfigMap is available
                    if repository_obj:
                        repo_spec = repository_obj.get("spec", {})
                        ssh_cfg = repo_spec.get("ssh") or {}
                        known_hosts_cm = (ssh_cfg.get("knownHostsConfigMapRef") or {}).get("name")
                        if known_hosts_cm:
                            try:
                                v1 = client.CoreV1Api()
                                v1.read_namespaced_config_map(known_hosts_cm, namespace)
                                known_hosts_available = True
                            except client.exceptions.ApiException:
                                known_hosts_available = False
            except Exception:
                repository_obj = None
                known_hosts_available = False

            # Create manual run Job
            try:
                job_name = manual_run_service.create_manual_run_job(
                    playbook_name=name,
                    namespace=namespace,
                    playbook_spec=spec,
                    repository_obj=repository_obj,
                    run_id=run_id,
                    owner_uid=uid,
                    known_hosts_available=known_hosts_available,
                )

                # Update Playbook status
                manual_run_service.update_playbook_manual_run_status(
                    playbook_name=name,
                    namespace=namespace,
                    run_id=run_id,
                    job_name=job_name,
                    status="Running",
                    reason="JobCreated",
                    message=f"Manual run Job '{job_name}' created",
                )

                # Clear the annotation
                manual_run_service.clear_manual_run_annotation(name, namespace)

                # Emit event
                _emit_event(
                    kind="Playbook",
                    namespace=namespace,
                    name=name,
                    reason="JobCreated",
                    message=f"Manual run Job '{job_name}' created with run ID '{run_id}'",
                )

                structured_logging.logger.info(
                    "Manual run Job created",
                    controller="Playbook",
                    resource=f"{namespace}/{name}",
                    uid=uid,
                    event="manual-run",
                    reason="JobCreated",
                    run_id=run_id,
                    job_name=job_name,
                )
            except Exception as e:
                structured_logging.logger.error(
                    f"Failed to create manual run Job: {str(e)}",
                    controller="Playbook",
                    resource=f"{namespace}/{name}",
                    uid=uid,
                    event="manual-run",
                    reason="JobFailed",
                    run_id=run_id,
                    error=str(e),
                )

                # Update status with failure
                manual_run_service.update_playbook_manual_run_status(
                    playbook_name=name,
                    namespace=namespace,
                    run_id=run_id,
                    job_name="",
                    status="Failed",
                    reason="JobFailed",
                    message=f"Failed to create manual run Job: {str(e)}",
                )

                # Clear the annotation even on failure
                manual_run_service.clear_manual_run_annotation(name, namespace)

                # Emit failure event
                _emit_event(
                    kind="Playbook",
                    namespace=namespace,
                    name=name,
                    reason="JobFailed",
                    message=f"Failed to create manual run Job: {str(e)}",
                    type_="Warning",
                )

        # Index dependencies and trigger dependent Schedules
        dependency_service.index_playbook_dependencies(namespace, name)
        dependency_service.requeue_dependent_schedules(namespace, name)

        structured_logging.logger.info(
            "Playbook reconciliation completed successfully",
            controller="Playbook",
            resource=f"{namespace}/{name}",
            uid=uid,
            event="reconcile",
            reason="ReconcileSucceeded",
        )
        metrics.RECONCILE_TOTAL.labels(kind="Playbook", result="success").inc()
        metrics.RECONCILE_DURATION.labels(kind="Playbook").observe(monotonic() - started_at)
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
        metrics.RECONCILE_DURATION.labels(kind="Playbook").observe(monotonic() - started_at)
        raise


@kopf.on.create(API_GROUP_VERSION, "schedules")
@kopf.on.update(API_GROUP_VERSION, "schedules")
@kopf.on.resume(API_GROUP_VERSION, "schedules")
def reconcile_schedule(
    spec: dict[str, Any],
    status: dict[str, Any],
    patch: kopf.Patch,
    meta: kopf.Meta,
    name: str,
    namespace: str,
    uid: str,
    **_: Any,
) -> None:
    started_at = monotonic()
    metrics.RECONCILE_TOTAL.labels(kind="Schedule", result="started").inc()
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

        # Validate playbook reference
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

        # Check for manual run request
        annotations = meta.get("annotations", {})
        run_id = manual_run_service.detect_manual_run_request(annotations)
        if run_id:
            # Check if a job with this run ID already exists to prevent duplicates
            batch_api = client.BatchV1Api()
            try:
                job_list = batch_api.list_namespaced_job(
                    namespace=namespace,
                    label_selector=f"{LABEL_RUN_ID}={run_id}",
                )
                if job_list.items:
                    # Job already exists for this run ID, clear annotation and skip
                    structured_logging.logger.info(
                        "Manual run Job already exists for run ID",
                        controller="Schedule",
                        resource=f"{namespace}/{name}",
                        uid=uid,
                        event="manual-run",
                        reason="JobAlreadyExists",
                        run_id=run_id,
                    )
                    manual_run_service.clear_schedule_manual_run_annotation(name, namespace)
                    # Continue with normal reconciliation after handling manual run
                    # Fall through to CronJob creation/update
            except Exception:
                # If we can't check, proceed with caution
                pass

            # Get the referenced Playbook
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
            except Exception as e:
                structured_logging.logger.error(
                    f"Failed to fetch Playbook for manual run: {str(e)}",
                    controller="Schedule",
                    resource=f"{namespace}/{name}",
                    uid=uid,
                    event="manual_run",
                    reason="PlaybookNotFound",
                )
                _emit_event(
                    kind="Schedule",
                    namespace=namespace,
                    name=name,
                    reason="ManualRunFailed",
                    message=f"Failed to fetch Playbook '{playbook_ref['name']}'",
                    type_="Warning",
                )
                # Clear the annotation to prevent retry loops
                manual_run_service.clear_schedule_manual_run_annotation(name, namespace)
                return

            # Get repository object for manual run
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
                    # Check if known hosts ConfigMap is available
                    if repository_obj:
                        repo_spec = repository_obj.get("spec", {})
                        ssh_cfg = repo_spec.get("ssh") or {}
                        known_hosts_cm = (ssh_cfg.get("knownHostsConfigMapRef") or {}).get("name")
                        if known_hosts_cm:
                            try:
                                v1 = client.CoreV1Api()
                                v1.read_namespaced_config_map(known_hosts_cm, namespace)
                                known_hosts_available = True
                            except client.exceptions.ApiException:
                                known_hosts_available = False
            except Exception:
                repository_obj = None
                known_hosts_available = False

            # Create manual run Job
            try:
                job_name = manual_run_service.create_schedule_manual_run_job(
                    schedule_name=name,
                    namespace=namespace,
                    playbook_obj=playbook_obj,
                    repository_obj=repository_obj,
                    run_id=run_id,
                    owner_uid=uid,
                    known_hosts_available=known_hosts_available,
                )

                # Update Schedule status
                manual_run_service.update_schedule_manual_run_status(
                    schedule_name=name,
                    namespace=namespace,
                    run_id=run_id,
                    job_name=job_name,
                    status="Running",
                    reason="JobCreated",
                    message=f"Manual run Job '{job_name}' created",
                )

                # Clear the annotation
                manual_run_service.clear_schedule_manual_run_annotation(name, namespace)

                # Emit event
                structured_logging.logger.info(
                    "Manual run Job created",
                    controller="Schedule",
                    resource=f"{namespace}/{name}",
                    uid=uid,
                    event="manual_run",
                    reason="ManualRunJobCreated",
                    job_name=job_name,
                    run_id=run_id,
                )
                _emit_event(
                    kind="Schedule",
                    namespace=namespace,
                    name=name,
                    reason="ManualRunJobCreated",
                    message=f"Manual run Job '{job_name}' created with run ID '{run_id}'",
                )
            except Exception as e:
                structured_logging.logger.error(
                    f"Failed to create manual run Job: {str(e)}",
                    controller="Schedule",
                    resource=f"{namespace}/{name}",
                    uid=uid,
                    event="manual_run",
                    reason="ManualRunFailed",
                )
                _emit_event(
                    kind="Schedule",
                    namespace=namespace,
                    name=name,
                    reason="ManualRunFailed",
                    message=f"Failed to create manual run Job: {str(e)}",
                    type_="Warning",
                )
                # Clear the annotation to prevent retry loops
                manual_run_service.clear_schedule_manual_run_annotation(name, namespace)

            # Continue with normal reconciliation after handling manual run
            # Fall through to CronJob creation/update

        # Fetch referenced Playbook and its Repository (best-effort)
        api = client.CustomObjectsApi()
        playbook_obj: dict[str, Any] = {}
        playbook_ready = True
        try:
            playbook_obj = api.get_namespaced_custom_object(
                group=API_GROUP,
                version="v1alpha1",
                namespace=namespace,
                plural="playbooks",
                name=playbook_ref["name"],
            )
            # Check if Playbook is ready
            playbook_status = playbook_obj.get("status", {})
            playbook_conditions = playbook_status.get("conditions", [])
            ready_condition = next(
                (c for c in playbook_conditions if c.get("type") == COND_READY), None
            )
            if ready_condition and ready_condition.get("status") != "True":
                playbook_ready = False
        except Exception:
            playbook_obj = {"spec": {"runtime": {}}}
            playbook_ready = False

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
                # Check if Repository is ready
                if repository_obj:
                    repo_status = repository_obj.get("status", {})
                    repo_conditions = repo_status.get("conditions", [])
                    repo_ready_condition = next(
                        (c for c in repo_conditions if c.get("type") == COND_READY), None
                    )
                    if repo_ready_condition and repo_ready_condition.get("status") != "True":
                        playbook_ready = False

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
            executor_service_account=_get_executor_service_account(),
            known_hosts_available=known_hosts_available,
            schedule_spec=spec,
            owner_uid=uid,
            owner_api_version=f"{API_GROUP}/v1alpha1",
            owner_kind="Schedule",
            owner_name=name,
        )

        # Apply via Server-Side Apply (SSA) with our field manager — create or patch.
        batch_api = client.BatchV1Api()
        cronjob_name = cj_manifest["metadata"]["name"]

        try:
            # Try to create first (SSA apply)
            batch_api.create_namespaced_cron_job(
                namespace=namespace,
                body=cj_manifest,
                field_manager="ansible-operator",
            )
            structured_logging.logger.info(
                "CronJob created via SSA",
                controller="Schedule",
                resource=f"{namespace}/{name}",
                uid=uid,
                event="reconcile",
                reason="CronJobCreated",
                cronjob_name=cronjob_name,
            )
            _emit_event(
                kind="Schedule",
                namespace=namespace,
                name=name,
                reason="CronJobCreated",
                message=f"CronJob '{cronjob_name}' created via SSA",
            )
        except client.exceptions.ApiException as e:
            if e.status == 409:
                # Already exists; check if we can safely adopt it
                try:
                    existing_cj = batch_api.read_namespaced_cron_job(
                        name=cronjob_name,
                        namespace=namespace,
                    )

                    # Check adoption safety
                    can_adopt, adoption_reason = _can_safely_adopt_cronjob(
                        existing_cj, uid, name, namespace
                    )

                    if can_adopt:
                        # Safe to adopt; patch with SSA apply
                        batch_api.patch_namespaced_cron_job(
                            name=cronjob_name,
                            namespace=namespace,
                            body=cj_manifest,
                            field_manager="ansible-operator",
                        )
                        structured_logging.logger.info(
                            "CronJob adopted and patched via SSA",
                            controller="Schedule",
                            resource=f"{namespace}/{name}",
                            uid=uid,
                            event="reconcile",
                            reason="CronJobAdopted",
                            cronjob_name=cronjob_name,
                            adoption_reason=adoption_reason,
                        )
                        _emit_event(
                            kind="Schedule",
                            namespace=namespace,
                            name=name,
                            reason="CronJobAdopted",
                            message=f"CronJob '{cronjob_name}' adopted and patched via SSA",
                        )
                    else:
                        # Cannot safely adopt; emit warning and skip
                        structured_logging.logger.warning(
                            "Cannot safely adopt existing CronJob",
                            controller="Schedule",
                            resource=f"{namespace}/{name}",
                            uid=uid,
                            event="reconcile",
                            reason="CronJobAdoptionSkipped",
                            cronjob_name=cronjob_name,
                            adoption_reason=adoption_reason,
                        )
                        _emit_event(
                            kind="Schedule",
                            namespace=namespace,
                            name=name,
                            reason="CronJobAdoptionSkipped",
                            message=f"Cannot safely adopt CronJob '{cronjob_name}': {adoption_reason}",
                            type_="Warning",
                        )
                        # Update Schedule conditions for adoption skipped case
                        _update_schedule_conditions(
                            patch.status,
                            namespace,
                            name,
                            uid,
                            spec,
                            cronjob_exists=False,
                            playbook_ready=playbook_ready,
                            current_status=status,
                        )
                        return

                except client.exceptions.ApiException as read_e:
                    if read_e.status == 404:
                        # CronJob disappeared between create attempt and read
                        # Try to create again
                        batch_api.create_namespaced_cron_job(
                            namespace=namespace,
                            body=cj_manifest,
                            field_manager="ansible-operator",
                        )
                        structured_logging.logger.info(
                            "CronJob created via SSA (retry after 404)",
                            controller="Schedule",
                            resource=f"{namespace}/{name}",
                            uid=uid,
                            event="reconcile",
                            reason="CronJobCreated",
                            cronjob_name=cronjob_name,
                        )
                        _emit_event(
                            kind="Schedule",
                            namespace=namespace,
                            name=name,
                            reason="CronJobCreated",
                            message=f"CronJob '{cronjob_name}' created via SSA (retry)",
                        )
                    else:
                        raise
            else:
                raise

        # Logging and events are handled in the try/except blocks above

        # Update Schedule conditions based on current state
        _update_schedule_conditions(
            patch.status,
            namespace,
            name,
            uid,
            spec,
            cronjob_exists=True,
            playbook_ready=playbook_ready,
            current_status=status,
        )
        structured_logging.logger.info(
            "Schedule reconciliation completed successfully",
            controller="Schedule",
            resource=f"{namespace}/{name}",
            uid=uid,
            event="reconcile",
            reason="ReconcileSucceeded",
        )
        metrics.RECONCILE_TOTAL.labels(kind="Schedule", result="success").inc()
        metrics.RECONCILE_DURATION.labels(kind="Schedule").observe(monotonic() - started_at)
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
        metrics.RECONCILE_DURATION.labels(kind="Schedule").observe(monotonic() - started_at)
        raise


@kopf.timer(API_GROUP_VERSION, "schedules", interval=900)  # 15 minutes
def periodic_schedule_requeue(
    name: str,
    namespace: str,
    uid: str,
    spec: dict[str, Any],
    status: dict[str, Any],
    **_: Any,
) -> None:
    """
    Periodic soft requeue for Schedule to refresh nextRunTime if needed.

    This timer runs every 15 minutes to ensure Schedule resources have up-to-date
    nextRunTime values without causing busy loops. The requeue is "soft" because
    it only triggers reconciliation if the nextRunTime needs refreshing.
    """
    structured_logging.logger.debug(
        "Periodic Schedule requeue triggered",
        controller="Schedule",
        resource=f"{namespace}/{name}",
        uid=uid,
        event="periodic-requeue",
        reason="TimerExpired",
    )

    # Get current CronJob to check if nextRunTime needs updating
    try:
        batch_api = client.BatchV1Api()
        cronjob_name = f"schedule-{name}"

        # Try to get the CronJob
        cronjob = batch_api.read_namespaced_cron_job(cronjob_name, namespace)
        cronjob_status = cronjob.status

        # Check if we have a nextScheduleTime from the CronJob
        next_schedule_time = cronjob_status.next_schedule_time
        if next_schedule_time:
            # Convert to ISO format for comparison
            next_schedule_iso = next_schedule_time.isoformat() + "Z"

            # Check if the Schedule's nextRunTime needs updating
            current_next_run_time = status.get("nextRunTime")

            if current_next_run_time != next_schedule_iso:
                # Update the Schedule's nextRunTime
                api = client.CustomObjectsApi()
                patch_body = {
                    "status": {
                        "nextRunTime": next_schedule_iso,
                    }
                }

                api.patch_namespaced_custom_object_status(
                    group=API_GROUP,
                    version="v1alpha1",
                    namespace=namespace,
                    plural="schedules",
                    name=name,
                    body=patch_body,
                    field_manager="ansible-operator",
                )

                structured_logging.logger.info(
                    "Schedule nextRunTime updated via periodic requeue",
                    controller="Schedule",
                    resource=f"{namespace}/{name}",
                    uid=uid,
                    event="periodic-requeue",
                    reason="NextRunTimeUpdated",
                    next_run_time=next_schedule_iso,
                )
            else:
                structured_logging.logger.debug(
                    "Schedule nextRunTime is up-to-date, no update needed",
                    controller="Schedule",
                    resource=f"{namespace}/{name}",
                    uid=uid,
                    event="periodic-requeue",
                    reason="NoUpdateNeeded",
                )
        else:
            structured_logging.logger.debug(
                "CronJob has no nextScheduleTime, skipping update",
                controller="Schedule",
                resource=f"{namespace}/{name}",
                uid=uid,
                event="periodic-requeue",
                reason="NoNextScheduleTime",
            )

    except client.exceptions.ApiException as e:
        if e.status == 404:
            # CronJob doesn't exist yet, which is normal for new Schedules
            structured_logging.logger.debug(
                "CronJob not found during periodic requeue, skipping",
                controller="Schedule",
                resource=f"{namespace}/{name}",
                uid=uid,
                event="periodic-requeue",
                reason="CronJobNotFound",
            )
        else:
            structured_logging.logger.warning(
                f"Failed to get CronJob during periodic requeue: {e}",
                controller="Schedule",
                resource=f"{namespace}/{name}",
                uid=uid,
                event="periodic-requeue",
                reason="CronJobGetFailed",
                error=str(e),
            )
    except Exception as e:
        structured_logging.logger.warning(
            f"Periodic requeue failed: {e}",
            controller="Schedule",
            resource=f"{namespace}/{name}",
            uid=uid,
            event="periodic-requeue",
            reason="RequeueFailed",
            error=str(e),
        )


@kopf.on.event("batch", "v1", "cronjobs")
def handle_cronjob_event(event: dict[str, Any], **_: Any) -> None:
    """Handle CronJob events to update Schedule status fields."""
    cronjob = event.get("object", {})
    metadata = cronjob.get("metadata", {})
    labels = metadata.get("labels", {})

    # Only handle CronJobs managed by ansible-operator
    if labels.get(LABEL_MANAGED_BY) != "ansible-operator":
        return

    # Extract Schedule information from labels
    owner_uid = labels.get(LABEL_OWNER_UID)
    owner_name = labels.get(LABEL_OWNER_NAME)
    if not owner_uid or not owner_name:
        return

    # Parse owner name (format: namespace.schedule-name)
    if "." not in owner_name:
        return
    namespace, schedule_name = owner_name.split(".", 1)

    # Get CronJob status
    status = cronjob.get("status", {})
    last_schedule_time = status.get("lastScheduleTime")
    next_schedule_time = status.get("nextScheduleTime")

    # Update Schedule status
    patch_body: dict[str, Any] = {"status": {}}

    if last_schedule_time:
        patch_body["status"]["lastRunTime"] = last_schedule_time

    if next_schedule_time:
        patch_body["status"]["nextRunTime"] = next_schedule_time

    # Get Schedule spec to update conditions
    api = client.CustomObjectsApi()
    try:
        schedule_obj = api.get_namespaced_custom_object(
            group=API_GROUP,
            version="v1alpha1",
            namespace=namespace,
            plural="schedules",
            name=schedule_name,
        )
        schedule_spec = schedule_obj.get("spec", {})

        # Update conditions based on current state
        _update_schedule_conditions(
            patch_body["status"],
            namespace,
            schedule_name,
            owner_uid,
            schedule_spec,
            cronjob_exists=True,
            playbook_ready=True,  # Assume ready for CronJob events
            current_status=schedule_obj.get("status"),
        )
    except Exception:
        # If we can't get the Schedule, just update the time fields
        pass

    # Apply the status update
    if patch_body["status"]:
        with suppress(Exception):
            api.patch_namespaced_custom_object_status(
                group=API_GROUP,
                version="v1alpha1",
                namespace=namespace,
                plural="schedules",
                name=schedule_name,
                body=patch_body,
                field_manager="ansible-operator",
            )
            structured_logging.logger.info(
                "Schedule status updated from CronJob",
                controller="Schedule",
                resource=f"{namespace}/{schedule_name}",
                uid=owner_uid,
                event="cronjob",
                reason="StatusUpdated",
                last_schedule_time=last_schedule_time,
                next_schedule_time=next_schedule_time,
            )


@kopf.on.event("batch", "v1", "jobs")
def handle_schedule_job_event(event: dict[str, Any], **_: Any) -> None:
    """Handle Job events to update Schedule status fields."""
    job = event.get("object", {})
    metadata = job.get("metadata", {})
    labels = metadata.get("labels", {})

    # Only handle Jobs managed by ansible-operator (not connectivity probe jobs)
    if labels.get(LABEL_MANAGED_BY) != "ansible-operator":
        return

    # Skip connectivity probe jobs
    if labels.get("ansible.cloud37.dev/probe-type") == "connectivity":
        return

    # Extract Schedule information from labels
    owner_uid = labels.get(LABEL_OWNER_UID)
    owner_name = labels.get(LABEL_OWNER_NAME)
    if not owner_uid or not owner_name:
        return

    # Parse owner name (format: namespace.schedule-name)
    if "." not in owner_name:
        return
    namespace, schedule_name = owner_name.split(".", 1)

    # Get Job status
    status = job.get("status", {})
    job_name = metadata.get("name", "")
    succeeded = status.get("succeeded", 0)
    failed = status.get("failed", 0)

    # Update Schedule status with Job reference
    patch_body: dict[str, Any] = {"status": {}}

    # Record job run metrics
    if succeeded > 0:
        metrics.JOB_RUNS_TOTAL.labels(kind="Schedule", result="success").inc()
        # Record job duration
        start_time = status.get("startTime")
        completion_time = status.get("completionTime")
        if start_time and completion_time:
            try:
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                completion_dt = datetime.fromisoformat(completion_time.replace("Z", "+00:00"))
                duration_seconds = (completion_dt - start_dt).total_seconds()
                metrics.JOB_RUN_DURATION.labels(kind="Schedule").observe(duration_seconds)
            except Exception:
                pass  # Ignore parsing errors
    elif failed > 0:
        metrics.JOB_RUNS_TOTAL.labels(kind="Schedule", result="failure").inc()
        # Record job duration
        start_time = status.get("startTime")
        completion_time = status.get("completionTime")
        if start_time and completion_time:
            try:
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                completion_dt = datetime.fromisoformat(completion_time.replace("Z", "+00:00"))
                duration_seconds = (completion_dt - start_dt).total_seconds()
                metrics.JOB_RUN_DURATION.labels(kind="Schedule").observe(duration_seconds)
            except Exception:
                pass  # Ignore parsing errors

    # Update lastJobRef
    if job_name:
        patch_body["status"]["lastJobRef"] = f"{namespace}/{job_name}"

    # Update lastRunTime from Job creation time
    creation_timestamp = metadata.get("creationTimestamp")
    if creation_timestamp:
        patch_body["status"]["lastRunTime"] = creation_timestamp

    # Extract revision from Job annotations if available
    annotations = metadata.get("annotations", {})
    revision = annotations.get("ansible.cloud37.dev/revision")
    if revision:
        patch_body["status"]["lastRunRevision"] = revision

    # Get Schedule spec to update conditions
    api = client.CustomObjectsApi()
    try:
        schedule_obj = api.get_namespaced_custom_object(
            group=API_GROUP,
            version="v1alpha1",
            namespace=namespace,
            plural="schedules",
            name=schedule_name,
        )
        schedule_spec = schedule_obj.get("spec", {})

        # Update conditions based on current state
        _update_schedule_conditions(
            patch_body["status"],
            namespace,
            schedule_name,
            owner_uid,
            schedule_spec,
            cronjob_exists=True,
            playbook_ready=True,  # Assume ready for Job events
            current_status=schedule_obj.get("status"),
        )
    except Exception:
        # If we can't get the Schedule, just update the time fields
        pass

    # Apply the status update
    if patch_body["status"]:
        with suppress(Exception):
            api.patch_namespaced_custom_object_status(
                group=API_GROUP,
                version="v1alpha1",
                namespace=namespace,
                plural="schedules",
                name=schedule_name,
                body=patch_body,
                field_manager="ansible-operator",
            )
            structured_logging.logger.info(
                "Schedule status updated from Job",
                controller="Schedule",
                resource=f"{namespace}/{schedule_name}",
                uid=owner_uid,
                event="job",
                reason="StatusUpdated",
                job_name=job_name,
                revision=revision,
            )


# Finalizers and cleanup handlers
@kopf.on.delete(API_GROUP_VERSION, "repositories")
def on_delete_repository(name: str, namespace: str, **_: Any) -> None:
    """Clean up dependencies when Repository is deleted."""
    dependency_service.cleanup_dependencies(namespace, "repository", name)


@kopf.on.delete(API_GROUP_VERSION, "playbooks")
def on_delete_playbook(name: str, namespace: str, **_: Any) -> None:
    """Clean up dependencies when Playbook is deleted."""
    dependency_service.cleanup_dependencies(namespace, "playbook", name)


@kopf.on.delete(API_GROUP_VERSION, "schedules")
def on_delete_schedule(name: str, namespace: str, **_: Any) -> None:
    """Clean up dependencies when Schedule is deleted."""
    # Schedules don't have dependents, but we could clean up any references
    pass
