from __future__ import annotations

from contextlib import suppress
from time import monotonic
from typing import Any

import kopf
from kubernetes import client, config
from prometheus_client import start_http_server

from . import metrics
from .builders.cronjob_builder import build_cronjob
from .constants import API_GROUP, API_GROUP_VERSION, COND_READY
from .utils.schedule import compute_computed_schedule


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_: Any) -> None:
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
    **_: Any,
) -> None:
    started_at = monotonic()
    try:
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

        # For now, mark as unknown until probe is implemented
        _update_condition(
            patch.status, "AuthValid", "Unknown", "Deferred", "Connectivity not yet probed"
        )
        _update_condition(
            patch.status, "CloneReady", "Unknown", "Deferred", "Clone not yet attempted"
        )
        _update_condition(
            patch.status, COND_READY, "Unknown", "Deferred", "Repository not yet verified"
        )
        _emit_event(
            kind="Repository",
            namespace=namespace,
            name=name,
            reason="ValidateSucceeded",
            message="Repository spec minimally validated",
        )
        metrics.RECONCILE_TOTAL.labels(kind="Repository", result="success").inc()
    except Exception:
        metrics.RECONCILE_TOTAL.labels(kind="Repository", result="error").inc()
        raise
    finally:
        metrics.RECONCILE_DURATION.labels(kind="Repository").observe(monotonic() - started_at)


@kopf.on.create(API_GROUP_VERSION, "playbooks")
@kopf.on.update(API_GROUP_VERSION, "playbooks")
@kopf.on.resume(API_GROUP_VERSION, "playbooks")
def reconcile_playbook(
    spec: dict[str, Any],
    status: dict[str, Any],
    patch: kopf.Patch,
    name: str,
    namespace: str,
    **_: Any,
) -> None:
    started_at = monotonic()
    try:
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

        # In later phases, verify repo readiness and paths; for now mark unknown
        _update_condition(
            patch.status, COND_READY, "Unknown", "Deferred", "Awaiting repository validation"
        )
        _emit_event(
            kind="Playbook",
            namespace=namespace,
            name=name,
            reason="ValidateSucceeded",
            message="Playbook spec minimally validated",
        )
        metrics.RECONCILE_TOTAL.labels(kind="Playbook", result="success").inc()
    except Exception:
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
    logger: kopf.Logger,
    **_: Any,
) -> None:
    started_at = monotonic()
    try:
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
        except Exception:
            repository_obj = None

        cj_manifest = build_cronjob(
            schedule_name=name,
            namespace=namespace,
            computed_schedule=computed,
            playbook=playbook_obj,
            repository=repository_obj,
            schedule_spec=spec,
            owner_uid=uid,
            owner_api_version=f"{API_GROUP}/v1alpha1",
            owner_kind="Schedule",
            owner_name=name,
        )

        # Apply via Server-Side Apply (SSA) with our field manager — create or patch.
        batch_api = client.BatchV1Api()
        batch_api.patch_namespaced_cron_job(
            name=name,
            namespace=namespace,
            body=cj_manifest,
            field_manager="ansible-operator",
            force=True,
            content_type="application/apply-patch+yaml",
        )
        logger.info(f"Applied CronJob via SSA schedule/{name}")
        _emit_event(
            kind="Schedule",
            namespace=namespace,
            name=name,
            reason="CronJobApplied",
            message="CronJob applied via SSA",
        )

        _update_condition(patch.status, COND_READY, "True", "Applied", "CronJob applied with SSA")
        metrics.RECONCILE_TOTAL.labels(kind="Schedule", result="success").inc()
    except Exception:
        metrics.RECONCILE_TOTAL.labels(kind="Schedule", result="error").inc()
        raise
    finally:
        metrics.RECONCILE_DURATION.labels(kind="Schedule").observe(monotonic() - started_at)


# Finalizers (no-op placeholders for now)
@kopf.on.delete(API_GROUP_VERSION, "schedules")
def on_delete_schedule(name: str, namespace: str, **_: Any) -> None:
    return
