"""Tests for orphaned repository probe job handling after operator restart."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from kubernetes import client

from ansible_operator.main import reconcile_orphaned_probe_jobs
from ansible_operator.constants import API_GROUP


class TestOrphanedProbeJobs:
    """Test orphaned probe job reconciliation."""

    @patch("ansible_operator.main.client")
    @patch("ansible_operator.main.dependency_service")
    @patch("ansible_operator.main.structured_logging")
    @patch("ansible_operator.main.os.getenv")
    def test_reconcile_orphaned_probe_jobs_success(
        self, mock_getenv, mock_logging, mock_deps, mock_client
    ):
        """Test successful reconciliation of orphaned probe jobs."""
        # Setup mocks
        mock_getenv.return_value = "namespace"

        # Mock Kubernetes API clients
        mock_batch_api = Mock()
        mock_custom_api = Mock()
        mock_client.BatchV1Api.return_value = mock_batch_api
        mock_client.CustomObjectsApi.return_value = mock_custom_api

        # Mock job with succeeded status
        mock_job = Mock()
        mock_job.metadata.name = "test-repo-probe"
        mock_job.status.succeeded = 1
        mock_job.status.failed = 0

        mock_jobs_response = Mock()
        mock_jobs_response.items = [mock_job]
        mock_batch_api.list_namespaced_job.return_value = mock_jobs_response

        # Mock repository exists
        mock_repository = Mock()
        mock_custom_api.get_namespaced_custom_object.return_value = mock_repository

        # Mock successful status update
        mock_custom_api.patch_namespaced_custom_object_status.return_value = None

        # Call the function
        reconcile_orphaned_probe_jobs()

        # Verify job listing was called
        mock_batch_api.list_namespaced_job.assert_called_once_with(
            namespace="namespace", label_selector="ansible.cloud37.dev/probe-type=connectivity"
        )

        # Verify repository was checked
        mock_custom_api.get_namespaced_custom_object.assert_called_once_with(
            group=API_GROUP,
            version="v1alpha1",
            namespace="namespace",
            plural="repositories",
            name="test-repo",
        )

        # Verify status was updated
        mock_custom_api.patch_namespaced_custom_object_status.assert_called_once()

        # Verify dependent playbooks were requeued
        mock_deps.requeue_dependent_playbooks.assert_called_once_with("namespace", "test-repo")

        # Verify logging
        mock_logging.logger.info.assert_called()

    @patch("ansible_operator.main.client")
    @patch("ansible_operator.main.dependency_service")
    @patch("ansible_operator.main.structured_logging")
    @patch("ansible_operator.main.os.getenv")
    def test_reconcile_orphaned_probe_jobs_failed(
        self, mock_getenv, mock_logging, mock_deps, mock_client
    ):
        """Test reconciliation of failed orphaned probe jobs."""
        # Setup mocks
        mock_getenv.return_value = "namespace"

        # Mock Kubernetes API clients
        mock_batch_api = Mock()
        mock_custom_api = Mock()
        mock_client.BatchV1Api.return_value = mock_batch_api
        mock_client.CustomObjectsApi.return_value = mock_custom_api

        # Mock job with failed status
        mock_job = Mock()
        mock_job.metadata.name = "test-repo-probe"
        mock_job.status.succeeded = 0
        mock_job.status.failed = 1

        mock_jobs_response = Mock()
        mock_jobs_response.items = [mock_job]
        mock_batch_api.list_namespaced_job.return_value = mock_jobs_response

        # Mock repository exists
        mock_repository = Mock()
        mock_custom_api.get_namespaced_custom_object.return_value = mock_repository

        # Mock successful status update
        mock_custom_api.patch_namespaced_custom_object_status.return_value = None

        # Call the function
        reconcile_orphaned_probe_jobs()

        # Verify status was updated with failed conditions
        mock_custom_api.patch_namespaced_custom_object_status.assert_called_once()

        # Verify dependent playbooks were NOT requeued for failed jobs
        mock_deps.requeue_dependent_playbooks.assert_not_called()

    @patch("ansible_operator.main.client")
    @patch("ansible_operator.main.dependency_service")
    @patch("ansible_operator.main.structured_logging")
    @patch("ansible_operator.main.os.getenv")
    def test_reconcile_orphaned_probe_jobs_repository_deleted(
        self, mock_getenv, mock_logging, mock_deps, mock_client
    ):
        """Test handling when repository is deleted but probe job exists."""
        # Setup mocks
        mock_getenv.return_value = "namespace"

        # Mock Kubernetes API clients
        mock_batch_api = Mock()
        mock_custom_api = Mock()
        mock_client.BatchV1Api.return_value = mock_batch_api
        mock_client.CustomObjectsApi.return_value = mock_custom_api

        # Mock job with succeeded status
        mock_job = Mock()
        mock_job.metadata.name = "test-repo-probe"
        mock_job.status.succeeded = 1
        mock_job.status.failed = 0

        mock_jobs_response = Mock()
        mock_jobs_response.items = [mock_job]
        mock_batch_api.list_namespaced_job.return_value = mock_jobs_response

        # Mock repository not found (404)
        mock_api_exception = client.exceptions.ApiException()
        mock_api_exception.status = 404
        mock_custom_api.get_namespaced_custom_object.side_effect = mock_api_exception

        # Call the function
        reconcile_orphaned_probe_jobs()

        # Verify repository was checked
        mock_custom_api.get_namespaced_custom_object.assert_called_once()

        # Verify status was NOT updated (repository deleted)
        mock_custom_api.patch_namespaced_custom_object_status.assert_not_called()

        # Verify dependent playbooks were NOT requeued
        mock_deps.requeue_dependent_playbooks.assert_not_called()

    @patch("ansible_operator.main.client")
    @patch("ansible_operator.main.dependency_service")
    @patch("ansible_operator.main.structured_logging")
    @patch("ansible_operator.main.os.getenv")
    def test_reconcile_orphaned_probe_jobs_running_job(
        self, mock_getenv, mock_logging, mock_deps, mock_client
    ):
        """Test handling of running probe jobs (not completed)."""
        # Setup mocks
        mock_getenv.return_value = "namespace"

        # Mock Kubernetes API clients
        mock_batch_api = Mock()
        mock_custom_api = Mock()
        mock_client.BatchV1Api.return_value = mock_batch_api
        mock_client.CustomObjectsApi.return_value = mock_custom_api

        # Mock job that's still running (no succeeded/failed)
        mock_job = Mock()
        mock_job.metadata.name = "test-repo-probe"
        mock_job.status.succeeded = None
        mock_job.status.failed = None

        mock_jobs_response = Mock()
        mock_jobs_response.items = [mock_job]
        mock_batch_api.list_namespaced_job.return_value = mock_jobs_response

        # Call the function
        reconcile_orphaned_probe_jobs()

        # Verify job listing was called
        mock_batch_api.list_namespaced_job.assert_called_once()

        # Verify repository was NOT checked (job not completed)
        mock_custom_api.get_namespaced_custom_object.assert_not_called()

        # Verify status was NOT updated
        mock_custom_api.patch_namespaced_custom_object_status.assert_not_called()

        # Verify dependent playbooks were NOT requeued
        mock_deps.requeue_dependent_playbooks.assert_not_called()

    @patch("ansible_operator.main.client")
    @patch("ansible_operator.main.dependency_service")
    @patch("ansible_operator.main.structured_logging")
    @patch("ansible_operator.main.os.getenv")
    def test_reconcile_orphaned_probe_jobs_cluster_scope(
        self, mock_getenv, mock_logging, mock_deps, mock_client
    ):
        """Test reconciliation with cluster-wide scope."""
        # Setup mocks
        mock_getenv.return_value = "all"

        # Mock Kubernetes API clients
        mock_batch_api = Mock()
        mock_custom_api = Mock()
        mock_v1_api = Mock()
        mock_client.BatchV1Api.return_value = mock_batch_api
        mock_client.CustomObjectsApi.return_value = mock_custom_api
        mock_client.CoreV1Api.return_value = mock_v1_api

        # Mock namespace list
        mock_ns1 = Mock()
        mock_ns1.metadata.name = "ns1"
        mock_ns2 = Mock()
        mock_ns2.metadata.name = "ns2"
        mock_ns_list = Mock()
        mock_ns_list.items = [mock_ns1, mock_ns2]
        mock_v1_api.list_namespace.return_value = mock_ns_list

        # Mock empty job lists for both namespaces
        mock_jobs_response = Mock()
        mock_jobs_response.items = []
        mock_batch_api.list_namespaced_job.return_value = mock_jobs_response

        # Call the function
        reconcile_orphaned_probe_jobs()

        # Verify namespace listing was called
        mock_v1_api.list_namespace.assert_called_once()

        # Verify job listing was called for both namespaces
        assert mock_batch_api.list_namespaced_job.call_count == 2
        mock_batch_api.list_namespaced_job.assert_any_call(
            namespace="ns1", label_selector="ansible.cloud37.dev/probe-type=connectivity"
        )
        mock_batch_api.list_namespaced_job.assert_any_call(
            namespace="ns2", label_selector="ansible.cloud37.dev/probe-type=connectivity"
        )

    @patch("ansible_operator.main.client")
    @patch("ansible_operator.main.dependency_service")
    @patch("ansible_operator.main.structured_logging")
    @patch("ansible_operator.main.os.getenv")
    def test_reconcile_orphaned_probe_jobs_error_handling(
        self, mock_getenv, mock_logging, mock_deps, mock_client
    ):
        """Test error handling during reconciliation."""
        # Setup mocks
        mock_getenv.return_value = "namespace"

        # Mock Kubernetes API clients
        mock_batch_api = Mock()
        mock_client.BatchV1Api.return_value = mock_batch_api

        # Mock job listing failure
        mock_batch_api.list_namespaced_job.side_effect = Exception("API Error")

        # Call the function
        reconcile_orphaned_probe_jobs()

        # Verify error was logged
        mock_logging.logger.warning.assert_called()

        # Verify error logging contains expected information
        call_args = mock_logging.logger.warning.call_args[0][0]
        assert "Failed to reconcile probe jobs in namespace" in call_args
        assert "namespace" in call_args
        assert "API Error" in call_args
