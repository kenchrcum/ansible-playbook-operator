from __future__ import annotations

from typing import Any

from ..constants import (
    API_GROUP,
    LABEL_MANAGED_BY,
    LABEL_OWNER_KIND,
    LABEL_OWNER_NAME,
    LABEL_OWNER_UID,
    LABEL_RUN_ID,
)


def build_connectivity_probe_job(
    *,
    repository_name: str,
    namespace: str,
    repository_spec: dict[str, Any],
    owner_uid: str,
    owner_api_version: str = f"{API_GROUP}/v1alpha1",
    owner_kind: str = "Repository",
    owner_name: str | None = None,
    image_default: str = "kenchrcum/ansible-runner:latest",
    image_digest: str | None = None,
    executor_service_account: str | None = None,
) -> dict[str, Any]:
    """Render a Job manifest for testing repository connectivity via git ls-remote.

    This function is pure and safe to unit-test.
    """
    repo_url: str = repository_spec.get("url", "")
    auth = repository_spec.get("auth") or {}
    auth_method: str | None = auth.get("method")
    auth_secret_name: str | None = (auth.get("secretRef") or {}).get("name")

    ssh_cfg = repository_spec.get("ssh") or {}
    ssh_known_hosts_cm = (ssh_cfg.get("knownHostsConfigMapRef") or {}).get("name")
    strict_host_key = ssh_cfg.get("strictHostKeyChecking", True)

    volumes: list[dict[str, Any]] = []
    volume_mounts: list[dict[str, Any]] = []
    env_list: list[dict[str, Any]] = []

    # Add volumes for workspace and home dir to support readOnlyRootFilesystem
    volumes.append({"name": "workspace", "emptyDir": {}})
    volume_mounts.append({"name": "workspace", "mountPath": "/workspace"})
    volumes.append({"name": "home", "emptyDir": {}})
    volume_mounts.append({"name": "home", "mountPath": "/home/ansible"})

    # Mount SSH secret when using ssh
    if auth_method == "ssh" and auth_secret_name:
        volumes.append({"name": "ssh-auth", "secret": {"secretName": auth_secret_name}})
        volume_mounts.append({"name": "ssh-auth", "mountPath": "/ssh-auth", "readOnly": True})

    # Mount known_hosts ConfigMap when available and strict checking is enabled
    if ssh_known_hosts_cm and strict_host_key:
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

    # Build git auth setup
    git_auth_setup: list[str] = ["mkdir -p $HOME/.ssh"]
    if auth_method == "ssh":
        git_auth_setup.append("install -m 0600 /ssh-auth/ssh-privatekey $HOME/.ssh/id_rsa")
        if strict_host_key and ssh_known_hosts_cm:
            git_auth_setup.append(
                'export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/id_rsa '
                "-o UserKnownHostsFile=/ssh-knownhosts/known_hosts "
                '-o StrictHostKeyChecking=yes"'
            )
        elif strict_host_key and not ssh_known_hosts_cm:
            # Enforce pinning: fail if strict enabled but no known hosts provided
            git_auth_setup.append(
                "echo 'known_hosts not provided while strictHostKeyChecking=true' >&2; exit 1"
            )
        else:
            git_auth_setup.append(
                'export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/id_rsa -o StrictHostKeyChecking=no"'
            )
    elif auth_method == "token":
        # Minimal GitHub token support via netrc
        git_auth_setup.extend(
            [
                "GIT_HOST=github.com",
                "if echo \"{repo_url}\" | grep -q 'github.com'; then GIT_HOST=github.com; fi",
                "umask 077",
                'printf \'machine %s login oauth2 password %s\n\' "$GIT_HOST" "$REPO_TOKEN" '
                "> $HOME/.netrc",
            ]
        )

    # Build git ls-remote command
    git_ls_remote_cmd = f'git ls-remote "{repo_url}" HEAD'

    script_lines: list[str] = [
        "set -euo pipefail",
        "export HOME=/home/ansible",
        *git_auth_setup,
        f"echo 'Testing connectivity to {repo_url}'",
        git_ls_remote_cmd,
        "echo 'Connectivity test successful'",
    ]

    job_name = f"{repository_name}-probe"
    owner_name = owner_name or repository_name

    container_security_context = {
        "runAsUser": 1000,
        "runAsGroup": 1000,
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "seccompProfile": {"type": "RuntimeDefault"},
        "capabilities": {"drop": ["ALL"]},
    }

    manifest: dict[str, Any] = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "namespace": namespace,
            "labels": {
                LABEL_MANAGED_BY: "ansible-operator",
                LABEL_OWNER_KIND: owner_kind,
                LABEL_OWNER_NAME: f"{namespace}.{repository_name}",
                LABEL_OWNER_UID: owner_uid,
                "ansible.cloud37.dev/probe-type": "connectivity",
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
            "backoffLimit": 0,  # Fail fast on first attempt
            "ttlSecondsAfterFinished": 300,  # Clean up after 5 minutes
            "template": {
                "spec": {
                    "restartPolicy": "Never",
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 1000,
                        "runAsGroup": 1000,
                        "fsGroup": 1000,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    **(
                        {"serviceAccountName": executor_service_account}
                        if executor_service_account
                        else {}
                    ),
                    "containers": [
                        {
                            "name": "connectivity-probe",
                            "image": (
                                f"{image_default.split(':')[0]}@{image_digest}"
                                if image_digest
                                else image_default
                            ),
                            "securityContext": container_security_context,
                            **({"env": env_list} if env_list else {}),
                            **({"volumeMounts": volume_mounts} if volume_mounts else {}),
                            "command": ["/bin/bash", "-c"],
                            "args": ["\n".join(script_lines)],
                        }
                    ],
                    **({"volumes": volumes} if volumes else {}),
                }
            },
        },
    }
    return manifest


def build_manual_run_job(
    *,
    playbook_name: str,
    namespace: str,
    playbook_spec: dict[str, Any],
    repository: dict[str, Any] | None = None,
    known_hosts_available: bool = False,
    run_id: str,
    owner_uid: str,
    owner_api_version: str = f"{API_GROUP}/v1alpha1",
    owner_kind: str = "Playbook",
    owner_name: str | None = None,
    image_default: str = "kenchrcum/ansible-runner:latest",
    image_digest: str | None = None,
    executor_service_account: str | None = None,
) -> dict[str, Any]:
    """Render a Job manifest for manual Playbook execution.

    This function is pure and safe to unit-test.
    """
    runtime = playbook_spec.get("runtime") or {}
    secrets_cfg = playbook_spec.get("secrets") or {}
    vault_password_secret_ref = secrets_cfg.get("vaultPasswordSecretRef")
    image: str = runtime.get("image") or image_default

    # Apply digest pinning if provided and image doesn't already have a digest
    if image_digest and "@" not in image:
        image = f"{image.split(':')[0]}@{image_digest}"

    # Build environment variables from secret mappings
    env_list: list[dict[str, Any]] = []
    volumes: list[dict[str, Any]] = []
    volume_mounts: list[dict[str, Any]] = []

    # Add volumes for workspace and home dir to support readOnlyRootFilesystem
    volumes.append({"name": "workspace", "emptyDir": {}})
    volume_mounts.append({"name": "workspace", "mountPath": "/workspace"})
    volumes.append({"name": "home", "emptyDir": {}})
    volume_mounts.append({"name": "home", "mountPath": "/home/ansible"})

    # Mount SSH secret and add token env var when using auth
    if repository:
        repo_spec = repository.get("spec", {})
        auth = repo_spec.get("auth") or {}
        auth_method: str | None = auth.get("method")
        auth_secret_name: str | None = (auth.get("secretRef") or {}).get("name")

        if auth_method == "ssh" and auth_secret_name:
            volumes.append({"name": "ssh-auth", "secret": {"secretName": auth_secret_name}})
            volume_mounts.append(
                {
                    "name": "ssh-auth",
                    "mountPath": "/ssh-auth",
                    "readOnly": True,
                }
            )
        elif auth_method == "token" and auth_secret_name:
            # Add token as environment variable for git authentication
            env_list.append(
                {
                    "name": "REPO_TOKEN",
                    "valueFrom": {"secretKeyRef": {"name": auth_secret_name, "key": "token"}},
                }
            )

        # Mount known hosts ConfigMap if available
        ssh_cfg = repo_spec.get("ssh") or {}
        ssh_known_hosts_cm = (ssh_cfg.get("knownHostsConfigMapRef") or {}).get("name")
        if ssh_known_hosts_cm and known_hosts_available:
            volumes.append({"name": "ssh-known", "configMap": {"name": ssh_known_hosts_cm}})
            volume_mounts.append(
                {
                    "name": "ssh-known",
                    "mountPath": "/ssh-knownhosts",
                    "readOnly": True,
                }
            )

    # Mount vault password secret if configured
    if vault_password_secret_ref:
        vault_secret_name = vault_password_secret_ref.get("name")
        if vault_secret_name:
            volumes.append({"name": "vault-password", "secret": {"secretName": vault_secret_name}})
            volume_mounts.append(
                {
                    "name": "vault-password",
                    "mountPath": "/vault-password",
                    "readOnly": True,
                }
            )

    # Build command for manual run
    playbook_path = playbook_spec.get("playbookPath", "")
    inventory_path = playbook_spec.get("inventoryPath")
    inventory_paths = playbook_spec.get("inventoryPaths", [])

    # Build git clone script if repository is provided
    script_parts = []

    if repository:
        repo_spec = repository.get("spec", {})
        repo_url = repo_spec.get("url", "")
        repo_revision = repo_spec.get("revision")
        repo_branch = repo_spec.get("branch") or "main"
        repo_paths = repo_spec.get("paths") or {}
        requirements_file = repo_paths.get("requirementsFile") or "requirements.yml"

        auth = repo_spec.get("auth") or {}
        auth_method = auth.get("method")

        ssh_cfg = repo_spec.get("ssh") or {}
        strict_host_key = ssh_cfg.get("strictHostKeyChecking", True)

        # Setup SSH auth
        script_parts.append("mkdir -p $HOME/.ssh")

        if auth_method == "ssh":
            script_parts.append("install -m 0600 /ssh-auth/ssh-privatekey $HOME/.ssh/id_rsa")
            if strict_host_key and known_hosts_available:
                script_parts.append(
                    'export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/id_rsa '
                    "-o UserKnownHostsFile=/ssh-knownhosts/known_hosts "
                    '-o StrictHostKeyChecking=yes"'
                )
            elif strict_host_key and not known_hosts_available:
                script_parts.append(
                    "echo 'known_hosts not provided while strictHostKeyChecking=true' >&2 && exit 1"
                )
            else:
                script_parts.append(
                    'export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/id_rsa -o StrictHostKeyChecking=no"'
                )
        elif auth_method == "token":
            script_parts.extend(
                [
                    "GIT_HOST=github.com",
                    'if echo "'
                    + repo_url
                    + '" | grep -q "github.com"; then GIT_HOST=github.com; fi',
                    "umask 077",
                    'printf "machine %s login oauth2 password %s\\n" "$GIT_HOST" "$REPO_TOKEN" > $HOME/.netrc',
                ]
            )

        # Clone repository
        script_parts.append(f'git clone "{repo_url}" /workspace/repo')
        script_parts.append("cd /workspace/repo")

        # Checkout specific revision or branch
        if repo_revision:
            script_parts.append(f'git checkout --detach "{repo_revision}"')
        else:
            script_parts.append(f'git checkout "{repo_branch}"')

        # Install galaxy requirements if present
        script_parts.append(
            f"if [ -f {requirements_file} ]; then ansible-galaxy install -r {requirements_file}; fi"
        )
    else:
        # No repository - assume playbook is mounted via other means
        script_parts.append("cd /workspace/repo")

    # Determine inventory argument
    inventory_arg = ""
    if inventory_path:
        inventory_arg = f"-i {inventory_path}"
    elif inventory_paths:
        inventory_arg = f"-i {','.join(inventory_paths)}"
    else:
        inventory_arg = "-i inventory"

    # Build execution options
    execution = playbook_spec.get("execution", {})
    execution_args = []

    if execution.get("tags"):
        execution_args.append(f"--tags {','.join(execution['tags'])}")
    if execution.get("skipTags"):
        execution_args.append(f"--skip-tags {','.join(execution['skipTags'])}")
    if execution.get("checkMode"):
        execution_args.append("--check")
    if execution.get("diff"):
        execution_args.append("--diff")
    if execution.get("verbosity", 0) > 0:
        execution_args.append("-" + "v" * execution["verbosity"])
    if execution.get("limit"):
        execution_args.append(f"--limit {execution['limit']}")
    if execution.get("connectionTimeout"):
        execution_args.append(f"--timeout {execution['connectionTimeout']}")
    if execution.get("forks"):
        execution_args.append(f"--forks {execution['forks']}")
    if execution.get("strategy") and execution["strategy"] != "linear":
        execution_args.append(f"--strategy {execution['strategy']}")
    if execution.get("flushCache"):
        execution_args.append("--flush-cache")
    if execution.get("forceHandlers"):
        execution_args.append("--force-handlers")
    if execution.get("startAtTask"):
        execution_args.append(f"--start-at-task {execution['startAtTask']}")
    if execution.get("step"):
        execution_args.append("--step")

    # Build vault password file argument
    vault_arg = ""
    if vault_password_secret_ref:
        vault_arg = "--vault-password-file /vault-password/password"

    # Build final ansible-playbook command
    execution_str = " ".join(execution_args)
    vault_str = f" {vault_arg}" if vault_arg else ""

    script_parts.append(
        f"ansible-playbook {inventory_arg} {execution_str}{vault_str} {playbook_path}"
    )

    # Construct full command
    full_script = " && ".join(script_parts)
    command = ["/bin/bash", "-c", full_script]

    # Build Job manifest
    job_name = f"{playbook_name}-manual-{run_id[:8]}"

    manifest = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "namespace": namespace,
            "labels": {
                LABEL_MANAGED_BY: "ansible-operator",
                LABEL_OWNER_KIND: owner_kind,
                LABEL_OWNER_NAME: f"{namespace}.{owner_name or playbook_name}",
                LABEL_OWNER_UID: owner_uid,
                LABEL_RUN_ID: run_id,
                "ansible.cloud37.dev/run-type": "manual",
            },
            "ownerReferences": [
                {
                    "apiVersion": owner_api_version,
                    "kind": owner_kind,
                    "name": owner_name or playbook_name,
                    "uid": owner_uid,
                    "controller": True,
                    "blockOwnerDeletion": False,
                }
            ],
        },
        "spec": {
            "backoffLimit": 3,
            "ttlSecondsAfterFinished": 3600,
            "template": {
                "metadata": {
                    "labels": {
                        LABEL_MANAGED_BY: "ansible-operator",
                        LABEL_OWNER_KIND: owner_kind,
                        LABEL_OWNER_NAME: f"{namespace}.{owner_name or playbook_name}",
                        LABEL_OWNER_UID: owner_uid,
                        LABEL_RUN_ID: run_id,
                        "ansible.cloud37.dev/run-type": "manual",
                    },
                },
                "spec": {
                    "restartPolicy": "Never",
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 1000,
                        "runAsGroup": 1000,
                        "fsGroup": 1000,
                    },
                    **(
                        {"serviceAccountName": executor_service_account}
                        if executor_service_account
                        else {}
                    ),
                    "containers": [
                        {
                            "name": "ansible-runner",
                            "image": image,
                            "command": command,
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "seccompProfile": {"type": "RuntimeDefault"},
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "env": env_list,
                            "volumeMounts": volume_mounts,
                            "resources": runtime.get("resources", {}),
                        }
                    ],
                    **({"volumes": volumes} if volumes else {}),
                },
            },
        },
    }
    return manifest
