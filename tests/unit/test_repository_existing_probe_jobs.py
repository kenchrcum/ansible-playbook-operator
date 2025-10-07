"""Tests for repository reconciliation with existing probe jobs."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from kubernetes import client

from ansible_operator.main import reconcile_repository
from ansible_operator.constants import API_GROUP_VERSION


class MockApiException(Exception):
    """Mock API exception with status attribute."""

    def __init__(self, status: int, reason: str = ""):
        super().__init__(reason)
        self.status = status


class TestRepositoryExistingProbeJobs:
    """Test repository reconciliation with existing probe jobs."""

    @patch("ansible_operator.main.client")
    @patch("ansible_operator.main.build_connectivity_probe_job")
    @patch("ansible_operator.main.dependency_service")
    @patch("ansible_operator.main.structured_logging")
    @patch("ansible_operator.main.metrics")
    @patch("ansible_operator.main._get_executor_service_account")
    def test_reconcile_repository_existing_job_succeeded(
        self, mock_sa, mock_metrics, mock_logging, mock_deps, mock_build_job, mock_client
    ):
        """Test repository reconciliation when existing probe job has succeeded."""
        # Setup mocks
        mock_sa.return_value = "executor-sa"

        # Mock Kubernetes API clients
        mock_batch_api = Mock()
        mock_client.BatchV1Api.return_value = mock_batch_api

        # Mock job creation failure (409 - already exists)
        mock_api_exception = MockApiException(status=409, reason="Job already exists")
        mock_batch_api.create_namespaced_job.side_effect = mock_api_exception

        # Mock existing job with succeeded status
        mock_existing_job = Mock()
        mock_existing_job.status.succeeded = 1
        mock_existing_job.status.failed = 0
        mock_batch_api.read_namespaced_job.return_value = mock_existing_job

        # Mock job manifest
        mock_job_manifest = {"apiVersion": "batch/v1", "kind": "Job"}
        mock_build_job.return_value = mock_job_manifest

        # Mock patch object
        mock_patch = Mock()
        mock_patch.status = {}
        mock_patch.meta = {}

        # Call the function
        reconcile_repository(
            spec={"url": "https://github.com/test/repo"},
            status={},
            patch=mock_patch,
            name="test-repo",
            namespace="default",
            uid="test-uid",
            meta={},
        )

        # Verify job creation was attempted
        mock_batch_api.create_namespaced_job.assert_called_once()

        # Verify existing job was read
        mock_batch_api.read_namespaced_job.assert_called_once_with(
            name="test-repo-probe", namespace="default"
        )

        # Verify job was NOT patched (already succeeded)
        mock_batch_api.patch_namespaced_job.assert_not_called()

        # Verify conditions were set to succeeded
        assert len(mock_patch.status["conditions"]) == 3
        conditions = {c["type"]: c for c in mock_patch.status["conditions"]}
        assert conditions["AuthValid"]["status"] == "True"
        assert conditions["AuthValid"]["reason"] == "ProbeSucceeded"
        assert conditions["CloneReady"]["status"] == "True"
        assert conditions["CloneReady"]["reason"] == "ProbeSucceeded"
        assert conditions["Ready"]["status"] == "True"
        assert conditions["Ready"]["reason"] == "Validated"

        # Verify logging
        mock_logging.logger.info.assert_called()
        log_calls = [call[0][0] for call in mock_logging.logger.info.call_args_list]
        assert any("Existing probe job already succeeded" in call for call in log_calls)

    @patch("ansible_operator.main.client")
    @patch("ansible_operator.main.build_connectivity_probe_job")
    @patch("ansible_operator.main.dependency_service")
    @patch("ansible_operator.main.structured_logging")
    @patch("ansible_operator.main.metrics")
    @patch("ansible_operator.main._get_executor_service_account")
    def test_reconcile_repository_existing_job_failed(
        self, mock_sa, mock_metrics, mock_logging, mock_deps, mock_build_job, mock_client
    ):
        """Test repository reconciliation when existing probe job has failed."""
        # Setup mocks
        mock_sa.return_value = "executor-sa"

        # Mock Kubernetes API clients
        mock_batch_api = Mock()
        mock_client.BatchV1Api.return_value = mock_batch_api

        # Mock job creation failure (409 - already exists)
        mock_api_exception = MockApiException(status=409, reason="Job already exists")
        mock_batch_api.create_namespaced_job.side_effect = mock_api_exception

        # Mock existing job with failed status
        mock_existing_job = Mock()
        mock_existing_job.status.succeeded = 0
        mock_existing_job.status.failed = 1
        mock_batch_api.read_namespaced_job.return_value = mock_existing_job

        # Mock job manifest
        mock_job_manifest = {"apiVersion": "batch/v1", "kind": "Job"}
        mock_build_job.return_value = mock_job_manifest

        # Mock patch object
        mock_patch = Mock()
        mock_patch.status = {}
        mock_patch.meta = {}

        # Call the function
        reconcile_repository(
            spec={"url": "https://github.com/test/repo"},
            status={},
            patch=mock_patch,
            name="test-repo",
            namespace="default",
            uid="test-uid",
            meta={},
        )

        # Verify job creation was attempted
        mock_batch_api.create_namespaced_job.assert_called_once()

        # Verify existing job was read
        mock_batch_api.read_namespaced_job.assert_called_once_with(
            name="test-repo-probe", namespace="default"
        )

        # Verify job was NOT patched (already failed)
        mock_batch_api.patch_namespaced_job.assert_not_called()

        # Verify conditions were set to failed
        assert len(mock_patch.status["conditions"]) == 3
        conditions = {c["type"]: c for c in mock_patch.status["conditions"]}
        assert conditions["AuthValid"]["status"] == "False"
        assert conditions["AuthValid"]["reason"] == "ProbeFailed"
        assert conditions["CloneReady"]["status"] == "False"
        assert conditions["CloneReady"]["reason"] == "ProbeFailed"
        assert conditions["Ready"]["status"] == "False"
        assert conditions["Ready"]["reason"] == "ProbeFailed"

        # Verify logging
        mock_logging.logger.info.assert_called()
        log_calls = [call[0][0] for call in mock_logging.logger.info.call_args_list]
        assert any("Existing probe job already failed" in call for call in log_calls)

    @patch("ansible_operator.main.client")
    @patch("ansible_operator.main.build_connectivity_probe_job")
    @patch("ansible_operator.main.dependency_service")
    @patch("ansible_operator.main.structured_logging")
    @patch("ansible_operator.main.metrics")
    @patch("ansible_operator.main._get_executor_service_account")
    def test_reconcile_repository_existing_job_running(
        self, mock_sa, mock_metrics, mock_logging, mock_deps, mock_build_job, mock_client
    ):
        """Test repository reconciliation when existing probe job is still running."""
        # Setup mocks
        mock_sa.return_value = "executor-sa"

        # Mock Kubernetes API clients
        mock_batch_api = Mock()
        mock_client.BatchV1Api.return_value = mock_batch_api

        # Mock job creation failure (409 - already exists)
        mock_api_exception = MockApiException(status=409, reason="Job already exists")
        mock_batch_api.create_namespaced_job.side_effect = mock_api_exception

        # Mock existing job that's still running
        mock_existing_job = Mock()
        mock_existing_job.status.succeeded = None
        mock_existing_job.status.failed = None
        mock_batch_api.read_namespaced_job.return_value = mock_existing_job

        # Mock job manifest
        mock_job_manifest = {"apiVersion": "batch/v1", "kind": "Job"}
        mock_build_job.return_value = mock_job_manifest

        # Mock patch object
        mock_patch = Mock()
        mock_patch.status = {}
        mock_patch.meta = {}

        # Call the function
        reconcile_repository(
            spec={"url": "https://github.com/test/repo"},
            status={},
            patch=mock_patch,
            name="test-repo",
            namespace="default",
            uid="test-uid",
            meta={},
        )

        # Verify job creation was attempted
        mock_batch_api.create_namespaced_job.assert_called_once()

        # Verify existing job was read
        mock_batch_api.read_namespaced_job.assert_called_once_with(
            name="test-repo-probe", namespace="default"
        )

        # Verify job was patched (still running)
        mock_batch_api.patch_namespaced_job.assert_called_once_with(
            name="test-repo-probe",
            namespace="default",
            body=mock_job_manifest,
            field_manager="ansible-operator",
        )

        # Verify conditions were set to running
        assert len(mock_patch.status["conditions"]) == 3
        conditions = {c["type"]: c for c in mock_patch.status["conditions"]}
        assert conditions["AuthValid"]["status"] == "Unknown"
        assert conditions["AuthValid"]["reason"] == "ProbeRunning"
        assert conditions["CloneReady"]["status"] == "Unknown"
        assert conditions["CloneReady"]["reason"] == "Deferred"
        assert conditions["Ready"]["status"] == "Unknown"
        assert conditions["Ready"]["reason"] == "Deferred"

    @patch("ansible_operator.main.client")
    @patch("ansible_operator.main.build_connectivity_probe_job")
    @patch("ansible_operator.main.dependency_service")
    @patch("ansible_operator.main.structured_logging")
    @patch("ansible_operator.main.metrics")
    @patch("ansible_operator.main._get_executor_service_account")
    def test_reconcile_repository_existing_job_deleted_between_calls(
        self, mock_sa, mock_metrics, mock_logging, mock_deps, mock_build_job, mock_client
    ):
        """Test repository reconciliation when existing job is deleted between creation attempt and read."""
        # Setup mocks
        mock_sa.return_value = "executor-sa"

        # Mock Kubernetes API clients
        mock_batch_api = Mock()
        mock_client.BatchV1Api.return_value = mock_batch_api

        # Mock job creation failure (409 - already exists) then success
        mock_api_exception = MockApiException(status=409, reason="Job already exists")
        mock_batch_api.create_namespaced_job.side_effect = [mock_api_exception, None]

        # Mock job read failure (404 - job deleted)
        mock_job_api_exception = MockApiException(status=404, reason="Job not found")
        mock_batch_api.read_namespaced_job.side_effect = mock_job_api_exception

        # Mock job manifest
        mock_job_manifest = {"apiVersion": "batch/v1", "kind": "Job"}
        mock_build_job.return_value = mock_job_manifest

        # Mock patch object
        mock_patch = Mock()
        mock_patch.status = {}
        mock_patch.meta = {}

        # Call the function
        reconcile_repository(
            spec={"url": "https://github.com/test/repo"},
            status={},
            patch=mock_patch,
            name="test-repo",
            namespace="default",
            uid="test-uid",
            meta={},
        )

        # Verify job creation was attempted twice (first failed, second succeeded)
        assert mock_batch_api.create_namespaced_job.call_count == 2

        # Verify existing job was read
        mock_batch_api.read_namespaced_job.assert_called_once_with(
            name="test-repo-probe", namespace="default"
        )

        # Verify job was NOT patched
        mock_batch_api.patch_namespaced_job.assert_not_called()

        # Verify conditions were set to running
        assert len(mock_patch.status["conditions"]) == 3
        conditions = {c["type"]: c for c in mock_patch.status["conditions"]}
        assert conditions["AuthValid"]["status"] == "Unknown"
        assert conditions["AuthValid"]["reason"] == "ProbeRunning"

    @patch("ansible_operator.main.client")
    @patch("ansible_operator.main.build_connectivity_probe_job")
    @patch("ansible_operator.main.dependency_service")
    @patch("ansible_operator.main.structured_logging")
    @patch("ansible_operator.main.metrics")
    @patch("ansible_operator.main._get_executor_service_account")
    def test_reconcile_repository_new_job_created(
        self, mock_sa, mock_metrics, mock_logging, mock_deps, mock_build_job, mock_client
    ):
        """Test repository reconciliation when new probe job is created successfully."""
        # Setup mocks
        mock_sa.return_value = "executor-sa"

        # Mock Kubernetes API clients
        mock_batch_api = Mock()
        mock_client.BatchV1Api.return_value = mock_batch_api

        # Mock job creation success
        mock_batch_api.create_namespaced_job.return_value = None

        # Mock job manifest
        mock_job_manifest = {"apiVersion": "batch/v1", "kind": "Job"}
        mock_build_job.return_value = mock_job_manifest

        # Mock patch object
        mock_patch = Mock()
        mock_patch.status = {}
        mock_patch.meta = {}

        # Call the function
        reconcile_repository(
            spec={"url": "https://github.com/test/repo"},
            status={},
            patch=mock_patch,
            name="test-repo",
            namespace="default",
            uid="test-uid",
            meta={},
        )

        # Verify job creation was called
        mock_batch_api.create_namespaced_job.assert_called_once_with(
            namespace="default", body=mock_job_manifest, field_manager="ansible-operator"
        )

        # Verify existing job was NOT read
        mock_batch_api.read_namespaced_job.assert_not_called()

        # Verify job was NOT patched
        mock_batch_api.patch_namespaced_job.assert_not_called()

        # Verify conditions were set to running
        assert len(mock_patch.status["conditions"]) == 3
        conditions = {c["type"]: c for c in mock_patch.status["conditions"]}
        assert conditions["AuthValid"]["status"] == "Unknown"
        assert conditions["AuthValid"]["reason"] == "ProbeRunning"
        assert conditions["CloneReady"]["status"] == "Unknown"
        assert conditions["CloneReady"]["reason"] == "Deferred"
        assert conditions["Ready"]["status"] == "Unknown"
        assert conditions["Ready"]["reason"] == "Deferred"
