"""Unit tests for playbook validation functionality."""

from unittest.mock import MagicMock, patch
from typing import Any

import pytest
from kubernetes import client

from ansible_operator.main import reconcile_playbook
from ansible_operator.services.git import GitService, GitValidationError


class MockPatch:
    """Mock patch object for testing."""

    def __init__(self):
        self.status = {}
        self.meta = MagicMock()


class TestPlaybookValidation:
    """Test playbook validation and condition management."""

    def test_reconcile_playbook_missing_repo_ref(self):
        """Test that missing repository reference sets Ready=False."""
        spec: dict[str, Any] = {}
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Mock the event emission to capture calls
        with patch("ansible_operator.main._emit_event") as mock_emit:
            reconcile_playbook(
                spec=spec,
                status=status,
                patch=mock_patch,
                name="test-playbook",
                namespace="default",
                uid="uid-123",
            )

        # Check conditions were set in mock_patch.status
        conditions = mock_patch.status.get("conditions", [])
        assert len(conditions) == 1

        ready_condition = conditions[0]
        assert ready_condition == {
            "type": "Ready",
            "status": "False",
            "reason": "RepoRefMissing",
            "message": "spec.repositoryRef.name must be set",
        }

        # Check event was emitted
        mock_emit.assert_called_once_with(
            kind="Playbook",
            namespace="default",
            name="test-playbook",
            reason="ValidateFailed",
            message="spec.repositoryRef.name must be set",
            type_="Warning",
        )

    def test_reconcile_playbook_missing_playbook_path(self):
        """Test that missing playbook path sets Ready=False."""
        spec: dict[str, Any] = {
            "repositoryRef": {"name": "test-repo"},
        }
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Mock the event emission to capture calls
        with patch("ansible_operator.main._emit_event") as mock_emit:
            reconcile_playbook(
                spec=spec,
                status=status,
                patch=mock_patch,
                name="test-playbook",
                namespace="default",
                uid="uid-123",
            )

        # Check conditions were set in mock_patch.status
        conditions = mock_patch.status.get("conditions", [])
        assert len(conditions) == 1

        ready_condition = conditions[0]
        assert ready_condition == {
            "type": "Ready",
            "status": "False",
            "reason": "InvalidPath",
            "message": "spec.playbookPath must be set",
        }

        # Check event was emitted
        mock_emit.assert_called_once_with(
            kind="Playbook",
            namespace="default",
            name="test-playbook",
            reason="ValidateFailed",
            message="spec.playbookPath must be set",
            type_="Warning",
        )

    def test_reconcile_playbook_repository_not_ready(self):
        """Test that repository not ready sets Ready=False with RepoNotReady reason."""
        spec: dict[str, Any] = {
            "repositoryRef": {"name": "test-repo"},
            "playbookPath": "playbooks/test.yml",
        }
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Mock GitService to return repository not ready
        with patch("ansible_operator.main.GitService") as mock_git_service_class:
            mock_git_service = MagicMock()
            mock_git_service.check_repository_readiness.return_value = (
                False,
                "Repository Ready condition not found",
            )
            mock_git_service_class.return_value = mock_git_service

            # Mock the event emission to capture calls
            with patch("ansible_operator.main._emit_event") as mock_emit:
                reconcile_playbook(
                    spec=spec,
                    status=status,
                    patch=mock_patch,
                    name="test-playbook",
                    namespace="default",
                    uid="uid-123",
                )

        # Check conditions were set in mock_patch.status
        conditions = mock_patch.status.get("conditions", [])
        assert len(conditions) == 1

        ready_condition = conditions[0]
        assert ready_condition == {
            "type": "Ready",
            "status": "False",
            "reason": "RepoNotReady",
            "message": "Repository Ready condition not found",
        }

        # Check event was emitted
        mock_emit.assert_called_once_with(
            kind="Playbook",
            namespace="default",
            name="test-playbook",
            reason="ValidateFailed",
            message="Repository not ready: Repository Ready condition not found",
            type_="Warning",
        )

    def test_reconcile_playbook_repository_not_found(self):
        """Test that repository not found sets Ready=False with RepoNotReady reason."""
        spec: dict[str, Any] = {
            "repositoryRef": {"name": "test-repo"},
            "playbookPath": "playbooks/test.yml",
        }
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Mock GitService to return repository ready
        with patch("ansible_operator.main.GitService") as mock_git_service_class:
            mock_git_service = MagicMock()
            mock_git_service.check_repository_readiness.return_value = (True, "")
            mock_git_service_class.return_value = mock_git_service

            # Mock Kubernetes API to return 404 for repository
            with patch("ansible_operator.main.client.CustomObjectsApi") as mock_api_class:
                mock_api = MagicMock()
                mock_api.get_namespaced_custom_object.side_effect = client.exceptions.ApiException(
                    status=404
                )
                mock_api_class.return_value = mock_api

                # Mock the event emission to capture calls
                with patch("ansible_operator.main._emit_event") as mock_emit:
                    reconcile_playbook(
                        spec=spec,
                        status=status,
                        patch=mock_patch,
                        name="test-playbook",
                        namespace="default",
                        uid="uid-123",
                    )

        # Check conditions were set in mock_patch.status
        conditions = mock_patch.status.get("conditions", [])
        assert len(conditions) == 1

        ready_condition = conditions[0]
        assert ready_condition == {
            "type": "Ready",
            "status": "False",
            "reason": "RepoNotReady",
            "message": "Repository test-repo not found",
        }

        # Check event was emitted
        mock_emit.assert_called_once_with(
            kind="Playbook",
            namespace="default",
            name="test-playbook",
            reason="ValidateFailed",
            message="Repository test-repo not found",
            type_="Warning",
        )

    def test_reconcile_playbook_invalid_paths(self):
        """Test that invalid paths set Ready=False with InvalidPath reason."""
        spec: dict[str, Any] = {
            "repositoryRef": {"name": "test-repo"},
            "playbookPath": "playbooks/test.yml",
        }
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Mock GitService to return repository ready but paths invalid
        with patch("ansible_operator.main.GitService") as mock_git_service_class:
            mock_git_service = MagicMock()
            mock_git_service.check_repository_readiness.return_value = (True, "")
            mock_git_service.validate_repository_paths.return_value = (
                False,
                "Playbook file not found: playbooks/test.yml",
            )
            mock_git_service_class.return_value = mock_git_service

            # Mock Kubernetes API to return repository
            with patch("ansible_operator.main.client.CustomObjectsApi") as mock_api_class:
                mock_api = MagicMock()
                mock_api.get_namespaced_custom_object.return_value = {
                    "spec": {"url": "https://github.com/test/repo.git"}
                }
                mock_api_class.return_value = mock_api

                # Mock the event emission to capture calls
                with patch("ansible_operator.main._emit_event") as mock_emit:
                    reconcile_playbook(
                        spec=spec,
                        status=status,
                        patch=mock_patch,
                        name="test-playbook",
                        namespace="default",
                        uid="uid-123",
                    )

        # Check conditions were set in mock_patch.status
        conditions = mock_patch.status.get("conditions", [])
        assert len(conditions) == 1

        ready_condition = conditions[0]
        assert ready_condition == {
            "type": "Ready",
            "status": "False",
            "reason": "InvalidPath",
            "message": "Playbook file not found: playbooks/test.yml",
        }

        # Check event was emitted
        mock_emit.assert_called_once_with(
            kind="Playbook",
            namespace="default",
            name="test-playbook",
            reason="ValidateFailed",
            message="Path validation failed: Playbook file not found: playbooks/test.yml",
            type_="Warning",
        )

    def test_reconcile_playbook_success(self):
        """Test successful playbook validation sets Ready=True."""
        spec: dict[str, Any] = {
            "repositoryRef": {"name": "test-repo"},
            "playbookPath": "playbooks/test.yml",
        }
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Mock GitService to return repository ready and paths valid
        with patch("ansible_operator.main.GitService") as mock_git_service_class:
            mock_git_service = MagicMock()
            mock_git_service.check_repository_readiness.return_value = (True, "")
            mock_git_service.validate_repository_paths.return_value = (True, "")
            mock_git_service_class.return_value = mock_git_service

            # Mock Kubernetes API to return repository
            with patch("ansible_operator.main.client.CustomObjectsApi") as mock_api_class:
                mock_api = MagicMock()
                mock_api.get_namespaced_custom_object.return_value = {
                    "spec": {"url": "https://github.com/test/repo.git"}
                }
                mock_api_class.return_value = mock_api

                # Mock the event emission to capture calls
                with patch("ansible_operator.main._emit_event") as mock_emit:
                    reconcile_playbook(
                        spec=spec,
                        status=status,
                        patch=mock_patch,
                        name="test-playbook",
                        namespace="default",
                        uid="uid-123",
                    )

        # Check conditions were set in mock_patch.status
        conditions = mock_patch.status.get("conditions", [])
        assert len(conditions) == 1

        ready_condition = conditions[0]
        assert ready_condition == {
            "type": "Ready",
            "status": "True",
            "reason": "Validated",
            "message": "Playbook paths and repository validated successfully",
        }

        # Check event was emitted
        mock_emit.assert_called_once_with(
            kind="Playbook",
            namespace="default",
            name="test-playbook",
            reason="ValidateSucceeded",
            message="Playbook validation completed successfully",
        )

    def test_reconcile_playbook_cross_namespace_repo(self):
        """Test playbook validation with cross-namespace repository reference."""
        spec: dict[str, Any] = {
            "repositoryRef": {"name": "test-repo", "namespace": "other-namespace"},
            "playbookPath": "playbooks/test.yml",
        }
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Mock GitService to return repository ready and paths valid
        with patch("ansible_operator.main.GitService") as mock_git_service_class:
            mock_git_service = MagicMock()
            mock_git_service.check_repository_readiness.return_value = (True, "")
            mock_git_service.validate_repository_paths.return_value = (True, "")
            mock_git_service_class.return_value = mock_git_service

            # Mock Kubernetes API to return repository
            with patch("ansible_operator.main.client.CustomObjectsApi") as mock_api_class:
                mock_api = MagicMock()
                mock_api.get_namespaced_custom_object.return_value = {
                    "spec": {"url": "https://github.com/test/repo.git"}
                }
                mock_api_class.return_value = mock_api

                # Mock the event emission to capture calls
                with patch("ansible_operator.main._emit_event") as mock_emit:
                    reconcile_playbook(
                        spec=spec,
                        status=status,
                        patch=mock_patch,
                        name="test-playbook",
                        namespace="default",
                        uid="uid-123",
                    )

        # Verify that the repository was fetched from the correct namespace
        mock_api.get_namespaced_custom_object.assert_called_once_with(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace="other-namespace",
            plural="repositories",
            name="test-repo",
        )

        # Verify GitService was called with correct namespace
        mock_git_service.check_repository_readiness.assert_called_once_with(
            "test-repo", "other-namespace"
        )
        mock_git_service.validate_repository_paths.assert_called_once_with(
            {"url": "https://github.com/test/repo.git"}, spec, "other-namespace"
        )


class TestGitService:
    """Test GitService functionality."""

    def test_validate_repository_paths_missing_url(self):
        """Test validation with missing repository URL."""
        git_service = GitService()
        repo_spec: dict[str, Any] = {}
        playbook_spec: dict[str, Any] = {"playbookPath": "test.yml"}

        is_valid, error = git_service.validate_repository_paths(repo_spec, playbook_spec, "default")

        assert not is_valid
        assert "Repository URL not specified" in error

    def test_validate_repository_paths_missing_playbook_path(self):
        """Test validation with missing playbook path."""
        git_service = GitService()
        repo_spec = {"url": "https://github.com/test/repo.git"}
        playbook_spec: dict[str, Any] = {}

        is_valid, error = git_service.validate_repository_paths(repo_spec, playbook_spec, "default")

        assert not is_valid
        assert "Playbook path not specified" in error

    @patch("ansible_operator.services.git.subprocess.run")
    def test_validate_repository_paths_clone_failure(self, mock_run):
        """Test validation with git clone failure."""
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "Permission denied"

        git_service = GitService()
        repo_spec = {"url": "https://github.com/test/repo.git"}
        playbook_spec = {"playbookPath": "test.yml"}

        is_valid, error = git_service.validate_repository_paths(repo_spec, playbook_spec, "default")

        assert not is_valid
        assert "Failed to clone repository: Permission denied" in error

    @patch("ansible_operator.services.git.subprocess.run")
    def test_validate_repository_paths_checkout_failure(self, mock_run):
        """Test validation with git checkout failure."""
        # First call succeeds (clone), second fails (checkout)
        mock_run.side_effect = [
            MagicMock(returncode=0, stderr=""),  # clone success
            MagicMock(returncode=1, stderr="Revision not found"),  # checkout failure
        ]

        git_service = GitService()
        repo_spec = {
            "url": "https://github.com/test/repo.git",
            "revision": "nonexistent-revision",
        }
        playbook_spec = {"playbookPath": "test.yml"}

        is_valid, error = git_service.validate_repository_paths(repo_spec, playbook_spec, "default")

        assert not is_valid
        assert "Failed to checkout revision nonexistent-revision: Revision not found" in error

    @patch("ansible_operator.services.git.subprocess.run")
    @patch("ansible_operator.services.git.Path")
    def test_validate_repository_paths_missing_playbook_file(self, mock_path, mock_run):
        """Test validation with missing playbook file."""
        # Mock successful git operations
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""

        # Mock Path behavior
        mock_clone_dir = MagicMock()
        mock_playbook_file = MagicMock()
        mock_playbook_file.exists.return_value = False

        # Set up the chain: Path(temp_dir) / "repo" -> clone_dir
        mock_path.return_value.__truediv__.return_value = mock_clone_dir
        # Set up: clone_dir / playbook_path -> playbook_file
        mock_clone_dir.__truediv__.return_value = mock_playbook_file

        git_service = GitService()
        repo_spec = {"url": "https://github.com/test/repo.git"}
        playbook_spec = {"playbookPath": "missing.yml"}

        is_valid, error = git_service.validate_repository_paths(repo_spec, playbook_spec, "default")

        assert not is_valid
        assert "Playbook file not found: missing.yml" in error

    @patch("ansible_operator.services.git.subprocess.run")
    @patch("ansible_operator.services.git.Path")
    def test_validate_repository_paths_missing_inventory_file(self, mock_path, mock_run):
        """Test validation with missing inventory file."""
        # Mock successful git operations
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""

        # Mock Path behavior
        mock_clone_dir = MagicMock()
        mock_playbook_file = MagicMock()
        mock_playbook_file.exists.return_value = True
        mock_inventory_file = MagicMock()
        mock_inventory_file.exists.return_value = False

        # Set up the chain: Path(temp_dir) / "repo" -> clone_dir
        mock_path.return_value.__truediv__.return_value = mock_clone_dir

        # Set up different returns for different paths
        def mock_truediv(path_str):
            if "playbook.yml" in str(path_str):
                return mock_playbook_file
            elif "inventory/hosts" in str(path_str):
                return mock_inventory_file
            return MagicMock()

        mock_clone_dir.__truediv__.side_effect = mock_truediv

        git_service = GitService()
        repo_spec = {"url": "https://github.com/test/repo.git"}
        playbook_spec = {
            "playbookPath": "playbook.yml",
            "inventoryPath": "inventory/hosts",
        }

        is_valid, error = git_service.validate_repository_paths(repo_spec, playbook_spec, "default")

        assert not is_valid
        assert "Inventory file not found: inventory/hosts" in error

    @patch("ansible_operator.services.git.subprocess.run")
    @patch("ansible_operator.services.git.Path")
    def test_validate_repository_paths_missing_ansible_cfg(self, mock_path, mock_run):
        """Test validation with missing ansible.cfg file."""
        # Mock successful git operations
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""

        # Mock Path behavior
        mock_clone_dir = MagicMock()
        mock_playbook_file = MagicMock()
        mock_playbook_file.exists.return_value = True
        mock_ansible_cfg_file = MagicMock()
        mock_ansible_cfg_file.exists.return_value = False

        # Set up the chain: Path(temp_dir) / "repo" -> clone_dir
        mock_path.return_value.__truediv__.return_value = mock_clone_dir

        # Set up different returns for different paths
        def mock_truediv(path_str):
            if "playbook.yml" in str(path_str):
                return mock_playbook_file
            elif "ansible.cfg" in str(path_str):
                return mock_ansible_cfg_file
            return MagicMock()

        mock_clone_dir.__truediv__.side_effect = mock_truediv

        git_service = GitService()
        repo_spec = {"url": "https://github.com/test/repo.git"}
        playbook_spec = {
            "playbookPath": "playbook.yml",
            "ansibleCfgPath": "ansible.cfg",
        }

        is_valid, error = git_service.validate_repository_paths(repo_spec, playbook_spec, "default")

        assert not is_valid
        assert "Ansible config file not found: ansible.cfg" in error

    @patch("ansible_operator.services.git.client.CustomObjectsApi")
    def test_check_repository_readiness_not_found(self, mock_api_class):
        """Test repository readiness check when repository not found."""
        mock_api = MagicMock()
        mock_api.get_namespaced_custom_object.side_effect = client.exceptions.ApiException(
            status=404
        )
        mock_api_class.return_value = mock_api

        git_service = GitService()
        is_ready, error = git_service.check_repository_readiness("missing-repo", "default")

        assert not is_ready
        assert "Repository missing-repo not found" in error

    @patch("ansible_operator.services.git.client.CustomObjectsApi")
    def test_check_repository_readiness_no_ready_condition(self, mock_api_class):
        """Test repository readiness check when Ready condition is missing."""
        mock_api = MagicMock()
        mock_api.get_namespaced_custom_object.return_value = {"status": {"conditions": []}}
        mock_api_class.return_value = mock_api

        git_service = GitService()
        is_ready, error = git_service.check_repository_readiness("test-repo", "default")

        assert not is_ready
        assert "Repository Ready condition not found" in error

    @patch("ansible_operator.services.git.client.CustomObjectsApi")
    def test_check_repository_readiness_not_ready(self, mock_api_class):
        """Test repository readiness check when repository is not ready."""
        mock_api = MagicMock()
        mock_api.get_namespaced_custom_object.return_value = {
            "status": {
                "conditions": [
                    {
                        "type": "Ready",
                        "status": "False",
                        "reason": "AuthValid",
                        "message": "Authentication failed",
                    }
                ]
            }
        }
        mock_api_class.return_value = mock_api

        git_service = GitService()
        is_ready, error = git_service.check_repository_readiness("test-repo", "default")

        assert not is_ready
        assert "Repository not ready: AuthValid - Authentication failed" in error

    @patch("ansible_operator.services.git.client.CustomObjectsApi")
    def test_check_repository_readiness_success(self, mock_api_class):
        """Test successful repository readiness check."""
        mock_api = MagicMock()
        mock_api.get_namespaced_custom_object.return_value = {
            "status": {
                "conditions": [
                    {
                        "type": "Ready",
                        "status": "True",
                        "reason": "Validated",
                        "message": "Repository is ready",
                    }
                ]
            }
        }
        mock_api_class.return_value = mock_api

        git_service = GitService()
        is_ready, error = git_service.check_repository_readiness("test-repo", "default")

        assert is_ready
        assert error == ""
