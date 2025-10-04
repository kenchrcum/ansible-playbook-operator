from __future__ import annotations

from typing import Any

import kopf
from kubernetes import client, config

from .builders.cronjob_builder import build_cronjob
from .constants import API_GROUP, API_GROUP_VERSION, COND_READY
from .utils.schedule import compute_computed_schedule


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_: Any) -> None:
    # Prefer SSA, set reasonable timeouts and workers
    # Avoid annotation writes by using status-backed progress/diff bases where supported.
    # Fallback to smart storages which adapt to cluster capabilities.
    try:
        settings.persistence.progress_storage = kopf.StatusProgressStorage()
        settings.persistence.diffbase_storage = kopf.StatusDiffBaseStorage(
            field="status.kopf.diffbase"
        )
    except Exception:
        settings.persistence.progress_storage = kopf.SmartProgressStorage()
    settings.posting.level = 0  # default
    settings.networking.request_timeout = 30.0
    settings.execution.max_workers = 4

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
    # Minimal validation; deeper checks will be added later
    url = (spec or {}).get("url")
    if not url:
        _update_condition(patch.status, "AuthValid", "False", "MissingURL", "spec.url must be set")
        _update_condition(
            patch.status, COND_READY, "False", "InvalidSpec", "Repository spec invalid"
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
        return

    # For now, mark as unknown until probe is implemented
    _update_condition(
        patch.status, "AuthValid", "Unknown", "Deferred", "Connectivity not yet probed"
    )
    _update_condition(patch.status, "CloneReady", "Unknown", "Deferred", "Clone not yet attempted")
    _update_condition(
        patch.status, COND_READY, "Unknown", "Deferred", "Repository not yet verified"
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
    **_: Any,
) -> None:
    repo_ref = (spec or {}).get("repositoryRef") or {}
    if not repo_ref.get("name"):
        _update_condition(
            patch.status,
            COND_READY,
            "False",
            "RepoRefMissing",
            "spec.repositoryRef.name must be set",
        )
        return

    # In later phases, verify repo readiness and paths; for now mark unknown
    _update_condition(
        patch.status, COND_READY, "Unknown", "Deferred", "Awaiting repository validation"
    )


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
        return

    # Fetch referenced Playbook to incorporate runtime defaults (best-effort)
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

    cj_manifest = build_cronjob(
        schedule_name=name,
        namespace=namespace,
        computed_schedule=computed,
        playbook=playbook_obj,
        schedule_spec=spec,
        owner_uid=uid,
        owner_api_version=f"{API_GROUP}/v1alpha1",
        owner_kind="Schedule",
        owner_name=name,
    )

    # Apply via Server-Side Apply
    batch_api = client.BatchV1Api()
    try:
        # Try to read existing CronJob
        batch_api.read_namespaced_cron_job(name=name, namespace=namespace)
        # Use patch (SSA) to update
        batch_api.patch_namespaced_cron_job(
            name=name,
            namespace=namespace,
            body=cj_manifest,
        )
        logger.info(f"Patched CronJob schedule/{name}")
    except client.exceptions.ApiException as e:
        if e.status == 404:
            batch_api.create_namespaced_cron_job(
                namespace=namespace,
                body=cj_manifest,
            )
            logger.info(f"Created CronJob schedule/{name}")
        else:
            raise

    _update_condition(patch.status, COND_READY, "True", "Applied", "CronJob applied with SSA")


# Finalizers (no-op placeholders for now)
@kopf.on.delete(API_GROUP_VERSION, "schedules")
def on_delete_schedule(name: str, namespace: str, **_: Any) -> None:
    return
