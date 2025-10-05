"""Git service for repository validation and path checking."""

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from kubernetes import client, config


class GitValidationError(Exception):
    """Raised when git validation fails."""

    pass


class GitService:
    """Service for git operations and repository validation."""

    def __init__(self) -> None:
        """Initialize the git service."""
        try:
            config.load_incluster_config()
        except Exception:
            try:
                config.load_kube_config()
            except Exception:
                # Running without kube config (e.g., unit tests)
                pass

    def validate_repository_paths(
        self,
        repository_spec: dict[str, Any],
        playbook_spec: dict[str, Any],
        namespace: str,
    ) -> tuple[bool, str]:
        """
        Validate that required paths exist in the repository.

        Args:
            repository_spec: Repository CRD spec
            playbook_spec: Playbook CRD spec
            namespace: Kubernetes namespace

        Returns:
            Tuple of (is_valid, error_message)

        Raises:
            GitValidationError: If validation cannot be performed
        """
        # Extract repository information
        repo_url = repository_spec.get("url")
        if not repo_url:
            return False, "Repository URL not specified"

        repo_branch = repository_spec.get("branch", "main")
        repo_revision = repository_spec.get("revision")

        # Extract playbook paths
        playbook_path = playbook_spec.get("playbookPath")
        if not playbook_path:
            return False, "Playbook path not specified"

        inventory_path = playbook_spec.get("inventoryPath")
        inventory_paths = playbook_spec.get("inventoryPaths", [])
        ansible_cfg_path = playbook_spec.get("ansibleCfgPath")

        # Extract auth information
        auth = repository_spec.get("auth", {})
        auth_method = auth.get("method")
        auth_secret_ref = auth.get("secretRef", {})

        # Extract SSH configuration
        ssh_config = repository_spec.get("ssh", {})
        strict_host_key = ssh_config.get("strictHostKeyChecking", True)
        known_hosts_cm_ref = ssh_config.get("knownHostsConfigMapRef", {})

        # Create temporary directory for clone
        with tempfile.TemporaryDirectory() as temp_dir:
            clone_dir = Path(temp_dir) / "repo"

            try:
                # Prepare git command
                git_cmd = ["git", "clone", "--depth", "1", repo_url, str(clone_dir)]

                # Add authentication if specified
                if auth_method == "ssh" and auth_secret_ref.get("name"):
                    # For SSH, we would need to mount the secret and set up SSH keys
                    # This is a simplified version - in practice, this would be done
                    # in a Kubernetes Job with proper secret mounting
                    pass
                elif auth_method == "token" and auth_secret_ref.get("name"):
                    # For token auth, we would need to mount the secret and set up netrc
                    # This is a simplified version - in practice, this would be done
                    # in a Kubernetes Job with proper secret mounting
                    pass

                # Clone repository
                result = subprocess.run(
                    git_cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=temp_dir,
                )

                if result.returncode != 0:
                    return False, f"Failed to clone repository: {result.stderr}"

                # Checkout specific revision if specified
                if repo_revision:
                    checkout_cmd = ["git", "checkout", "--detach", repo_revision]
                    result = subprocess.run(
                        checkout_cmd,
                        capture_output=True,
                        text=True,
                        timeout=10,
                        cwd=clone_dir,
                    )
                    if result.returncode != 0:
                        return (
                            False,
                            f"Failed to checkout revision {repo_revision}: {result.stderr}",
                        )

                # Validate playbook path
                playbook_file = clone_dir / playbook_path
                if not playbook_file.exists():
                    return False, f"Playbook file not found: {playbook_path}"

                # Validate inventory path(s)
                if inventory_path:
                    inventory_file = clone_dir / inventory_path
                    if not inventory_file.exists():
                        return False, f"Inventory file not found: {inventory_path}"
                elif inventory_paths:
                    for inv_path in inventory_paths:
                        inventory_file = clone_dir / inv_path
                        if not inventory_file.exists():
                            return False, f"Inventory file not found: {inv_path}"

                # Validate ansible.cfg path if specified
                if ansible_cfg_path:
                    ansible_cfg_file = clone_dir / ansible_cfg_path
                    if not ansible_cfg_file.exists():
                        return False, f"Ansible config file not found: {ansible_cfg_path}"

                return True, ""

            except subprocess.TimeoutExpired:
                return False, "Repository clone timed out"
            except Exception as e:
                return False, f"Repository validation failed: {str(e)}"

    def check_repository_readiness(self, repository_name: str, namespace: str) -> tuple[bool, str]:
        """
        Check if a repository is ready by examining its status conditions.

        Args:
            repository_name: Name of the repository CRD
            namespace: Kubernetes namespace

        Returns:
            Tuple of (is_ready, error_message)
        """
        try:
            custom_api = client.CustomObjectsApi()
            repo = custom_api.get_namespaced_custom_object(
                group="ansible.cloud37.dev",
                version="v1alpha1",
                namespace=namespace,
                plural="repositories",
                name=repository_name,
            )

            status = repo.get("status", {})
            conditions = status.get("conditions", [])

            # Check for Ready condition
            ready_condition = next((c for c in conditions if c.get("type") == "Ready"), None)
            if not ready_condition:
                return False, "Repository Ready condition not found"

            if ready_condition.get("status") != "True":
                reason = ready_condition.get("reason", "Unknown")
                message = ready_condition.get("message", "Repository not ready")
                return False, f"Repository not ready: {reason} - {message}"

            return True, ""

        except client.exceptions.ApiException as e:
            if e.status == 404:
                return False, f"Repository {repository_name} not found"
            return False, f"Failed to check repository status: {e.reason}"
        except Exception as e:
            return False, f"Failed to check repository readiness: {str(e)}"
