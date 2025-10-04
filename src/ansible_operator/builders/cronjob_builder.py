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
    repository: dict[str, Any] | None = None,
    known_hosts_available: bool = False,
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
    spec = playbook.get("spec") or {}
    runtime = spec.get("runtime") or {}
    secrets_cfg = spec.get("secrets") or {}
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
        "runAsUser": 1000,
        "runAsGroup": 1000,
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "seccompProfile": {"type": "RuntimeDefault"},
        "capabilities": {"drop": ["ALL"]},
    }

    # Build environment variables from secret mappings
    env_list: list[dict[str, Any]] = []
    for item in secrets_cfg.get("env") or []:
        env_var_name = item.get("envVarName")
        secret_ref = item.get("secretRef") or {}
        if env_var_name and secret_ref.get("name") and secret_ref.get("key"):
            env_list.append(
                {
                    "name": env_var_name,
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": secret_ref["name"],
                            "key": secret_ref["key"],
                        }
                    },
                }
            )

    env_from_list: list[dict[str, Any]] = []
    for ref in secrets_cfg.get("envFromSecretRefs") or []:
        name_ref = ref.get("name")
        if name_ref:
            env_from_list.append({"secretRef": {"name": name_ref}})

    volumes = list(runtime.get("volumes") or [])
    volume_mounts = list(runtime.get("volumeMounts") or [])
    service_account_name = runtime.get("serviceAccountName")
    active_deadline_seconds = runtime.get("activeDeadlineSeconds")

    cronjob_name = f"{schedule_name}"
    owner_name = owner_name or schedule_name

    # Build execution script
    repo_spec = (repository or {}).get("spec") or {}
    repo_url: str = repo_spec.get("url", "")
    repo_revision: str | None = repo_spec.get("revision")
    repo_branch: str = repo_spec.get("branch") or "main"
    repo_paths = repo_spec.get("paths") or {}
    requirements_file = repo_paths.get("requirementsFile") or "requirements.yml"
    playbook_path: str = spec.get("playbookPath") or ""
    inventory_path: str | None = spec.get("inventoryPath")
    inventory_paths: list[str] = spec.get("inventoryPaths") or []
    ansible_cfg_path: str | None = spec.get("ansibleCfgPath")

    ssh_cfg = repo_spec.get("ssh") or {}
    ssh_known_hosts_cm = (ssh_cfg.get("knownHostsConfigMapRef") or {}).get("name")
    strict_host_key = ssh_cfg.get("strictHostKeyChecking", True)

    auth = repo_spec.get("auth") or {}
    auth_method: str | None = auth.get("method")
    auth_secret_name: str | None = (auth.get("secretRef") or {}).get("name")

    # Add volumes for workspace and home dir to support readOnlyRootFilesystem
    volumes.append({"name": "workspace", "emptyDir": {}})
    volume_mounts.append({"name": "workspace", "mountPath": "/workspace"})
    volumes.append({"name": "home", "emptyDir": {}})
    volume_mounts.append({"name": "home", "mountPath": "/home/ansible"})

    # Mount SSH secret and known_hosts when using ssh
    if auth_method == "ssh" and auth_secret_name:
        volumes.append({"name": "ssh-auth", "secret": {"secretName": auth_secret_name}})
        volume_mounts.append({"name": "ssh-auth", "mountPath": "/ssh-auth", "readOnly": True})
    if ssh_known_hosts_cm and known_hosts_available:
        volumes.append({"name": "ssh-known", "configMap": {"name": ssh_known_hosts_cm}})
        volume_mounts.append(
            {"name": "ssh-known", "mountPath": "/ssh-knownhosts", "readOnly": True}
        )

    # Token-based auth env var
    if auth_method == "token" and auth_secret_name:
        env_list.append(
            {
                "name": "REPO_TOKEN",
                "valueFrom": {"secretKeyRef": {"name": auth_secret_name, "key": "token"}},
            }
        )

    # Build inventory flags
    inventory_flags: list[str] = []
    if inventory_path:
        inventory_flags.extend(["-i", inventory_path])
    for ipath in inventory_paths:
        inventory_flags.extend(["-i", ipath])

    extra_env_exports: list[str] = []
    if ansible_cfg_path:
        extra_env_exports.append(f'export ANSIBLE_CONFIG="{ansible_cfg_path}"')

    # Build git auth setup
    git_auth_setup: list[str] = ["mkdir -p $HOME/.ssh"]
    if auth_method == "ssh":
        git_auth_setup.append("install -m 0600 /ssh-auth/ssh-privatekey $HOME/.ssh/id_rsa")
        if strict_host_key and known_hosts_available:
            git_auth_setup.append(
                'export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/id_rsa \
                    -o UserKnownHostsFile=/ssh-knownhosts/known_hosts \
                    -o StrictHostKeyChecking=yes"'
            )
        elif strict_host_key and not known_hosts_available:
            # Enforce pinning: fail fast if strict enabled but no known hosts provided
            git_auth_setup.append(
                "echo 'known_hosts not provided while strictHostKeyChecking=true' >&2; exit 1"
            )
        else:
            git_auth_setup.append(
                'export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/id_rsa -o StrictHostKeyChecking=no"'
            )
    elif auth_method == "token":
        # Minimal GitHub token support via netrc, avoiding logging the token
        git_auth_setup.extend(
            [
                "GIT_HOST=github.com",
                "if echo \"{repo_url}\" | grep -q 'github.com'; then GIT_HOST=github.com; fi",
                "umask 077",
                'printf \'machine %s login oauth2 password %s\n\' "$GIT_HOST" "$REPO_TOKEN" \
                    > $HOME/.netrc',
            ]
        )

    # Build clone and checkout
    clone_dir = "/workspace/repo"
    clone_and_checkout: list[str] = [
        f'git clone "{repo_url}" {clone_dir}',
        f"cd {clone_dir}",
    ]
    if repo_revision:
        clone_and_checkout.append(f'git checkout --detach "{repo_revision}"')
    else:
        clone_and_checkout.append(f'git checkout "{repo_branch}"')

    # Install galaxy requirements if present
    clone_and_checkout.append(
        f"if [ -f {requirements_file} ]; then ansible-galaxy install -r {requirements_file}; fi"
    )

    # Build ansible-playbook command
    extra_vars_flags: list[str] = []
    extra_vars = spec.get("extraVars") or {}
    if extra_vars:
        # Inline JSON; avoid secrets in logs by not echoing
        import json

        extra_vars_json = json.dumps(extra_vars)
        extra_vars_flags = ["--extra-vars", extra_vars_json]

    ansible_cmd_parts: list[str] = [
        "ansible-playbook",
        playbook_path,
        *inventory_flags,
        *extra_vars_flags,
    ]

    script_lines: list[str] = [
        "set -euo pipefail",
        "export HOME=/home/ansible",
        *extra_env_exports,
        *git_auth_setup,
        *clone_and_checkout,
        "cd /workspace/repo",
        " ".join(ansible_cmd_parts),
    ]

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
                {"suspend": bool(schedule_spec.get("suspend"))}
                if "suspend" in schedule_spec
                else {}
            ),
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
                    **(
                        {"activeDeadlineSeconds": active_deadline_seconds}
                        if active_deadline_seconds is not None
                        else {}
                    ),
                    "template": {
                        "spec": {
                            "restartPolicy": "Never",
                            "securityContext": pod_security_context,
                            **(
                                {"serviceAccountName": service_account_name}
                                if service_account_name
                                else {}
                            ),
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
                            **({"volumes": volumes} if volumes else {}),
                            "containers": [
                                {
                                    "name": "ansible-runner",
                                    "image": image,
                                    **({"resources": resources} if resources else {}),
                                    "securityContext": container_security_context,
                                    **({"env": env_list} if env_list else {}),
                                    **({"envFrom": env_from_list} if env_from_list else {}),
                                    **({"volumeMounts": volume_mounts} if volume_mounts else {}),
                                    "command": ["/bin/bash", "-c"],
                                    "args": ["\n".join(script_lines)],
                                }
                            ],
                            **({"volumes": volumes} if volumes else {}),
                        }
                    },
                }
            },
            **({"ttlSecondsAfterFinished": ttl_seconds} if ttl_seconds is not None else {}),
        },
    }
    return manifest
