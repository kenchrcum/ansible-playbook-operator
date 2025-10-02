from __future__ import annotations

from typing import Any

from ..constants import (
    API_GROUP,
    LABEL_MANAGED_BY,
    LABEL_OWNER_KIND,
    LABEL_OWNER_NAME,
    LABEL_OWNER_UID,
)


def build_cronjob(
    *,
    schedule_name: str,
    namespace: str,
    computed_schedule: str,
    playbook: dict[str, Any],
    schedule_spec: dict[str, Any],
    owner_uid: str,
    owner_api_version: str = f"{API_GROUP}/v1alpha1",
    owner_kind: str = "Schedule",
    owner_name: str | None = None,
    image_default: str = "kenchrcum/ansible-runner:latest",
) -> dict[str, Any]:
    """Render a CronJob manifest from Playbook and Schedule specs.

    This function is pure and safe to unit-test.
    """
    runtime = (playbook.get("spec") or {}).get("runtime") or {}
    image: str = runtime.get("image") or image_default

    resources: dict[str, Any] = schedule_spec.get("resources") or {}
    backoff_limit: int | None = schedule_spec.get("backoffLimit")
    s_history: int | None = schedule_spec.get("successfulJobsHistoryLimit")
    f_history: int | None = schedule_spec.get("failedJobsHistoryLimit")
    ttl_seconds: int | None = schedule_spec.get("ttlSecondsAfterFinished")
    starting_deadline: int | None = schedule_spec.get("startingDeadlineSeconds")
    concurrency_policy: str | None = schedule_spec.get("concurrencyPolicy")

    pod_security_context = runtime.get("podSecurityContext") or {}
    container_security_context = runtime.get("securityContext") or {
        "runAsNonRoot": True,
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
    }

    cronjob_name = f"{schedule_name}"
    owner_name = owner_name or schedule_name

    manifest: dict[str, Any] = {
        "apiVersion": "batch/v1",
        "kind": "CronJob",
        "metadata": {
            "name": cronjob_name,
            "namespace": namespace,
            "labels": {
                LABEL_MANAGED_BY: "ansible-operator",
                LABEL_OWNER_KIND: "Schedule",
                LABEL_OWNER_NAME: f"{namespace}.{schedule_name}",
                LABEL_OWNER_UID: owner_uid,
            },
            "ownerReferences": [
                {
                    "apiVersion": owner_api_version,
                    "kind": owner_kind,
                    "name": owner_name,
                    "uid": owner_uid,
                    "controller": True,
                    "blockOwnerDeletion": False,
                }
            ],
        },
        "spec": {
            "schedule": computed_schedule,
            "concurrencyPolicy": concurrency_policy or "Forbid",
            **(
                {"startingDeadlineSeconds": starting_deadline}
                if starting_deadline is not None
                else {}
            ),
            **({"successfulJobsHistoryLimit": s_history} if s_history is not None else {}),
            **({"failedJobsHistoryLimit": f_history} if f_history is not None else {}),
            "jobTemplate": {
                "spec": {
                    **({"backoffLimit": backoff_limit} if backoff_limit is not None else {}),
                    "template": {
                        "spec": {
                            "restartPolicy": "Never",
                            "securityContext": pod_security_context,
                            **(
                                {"imagePullSecrets": runtime.get("imagePullSecrets")}
                                if runtime.get("imagePullSecrets")
                                else {}
                            ),
                            **(
                                {"nodeSelector": runtime.get("nodeSelector")}
                                if runtime.get("nodeSelector")
                                else {}
                            ),
                            **(
                                {"tolerations": runtime.get("tolerations")}
                                if runtime.get("tolerations")
                                else {}
                            ),
                            **(
                                {"affinity": runtime.get("affinity")}
                                if runtime.get("affinity")
                                else {}
                            ),
                            "containers": [
                                {
                                    "name": "ansible-runner",
                                    "image": image,
                                    **({"resources": resources} if resources else {}),
                                    "securityContext": container_security_context,
                                    # Command and env will be generated in later phases
                                    "command": ["/bin/bash", "-c"],
                                    "args": [
                                        (
                                            "echo 'ansible-playbook execution to be' "
                                            " 'implemented' && exit 0"
                                        )
                                    ],
                                }
                            ],
                        }
                    },
                }
            },
            **({"ttlSecondsAfterFinished": ttl_seconds} if ttl_seconds is not None else {}),
        },
    }
    return manifest
