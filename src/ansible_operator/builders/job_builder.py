from __future__ import annotations

from typing import Any

from ..constants import (
    API_GROUP,
    LABEL_MANAGED_BY,
    LABEL_OWNER_KIND,
    LABEL_OWNER_NAME,
    LABEL_OWNER_UID,
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
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "connectivity-probe",
                            "image": image_default,
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
