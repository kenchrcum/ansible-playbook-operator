"""Tests for repository finalizer functionality."""

from typing import Any
from unittest.mock import MagicMock, patch

from kubernetes import client

from ansible_operator.main import FINALIZER_REPOSITORY, reconcile_repository


class MockPatch:
    """Mock patch object for testing."""

    def __init__(self):
        self.status = {}
        self.meta = {}


class TestRepositoryFinalizer:
    """Test repository finalizer functionality."""

    def test_add_finalizer_on_create(self):
        """Test that finalizer is added when repository is created."""
        spec: dict[str, Any] = {"url": "https://github.com/example/repo.git"}
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Create meta mock with no finalizers and no deletion timestamp
        meta_mock = MagicMock()
        meta_mock.get.side_effect = lambda key, default=None: (
            [] if key == "finalizers" else None if key == "deletionTimestamp" else MagicMock()
        )

        # Mock all Kubernetes API calls to prevent actual API calls
        with (
            patch("ansible_operator.main.client.BatchV1Api") as mock_batch_api_class,
            patch("ansible_operator.main.structured_logging.logger") as mock_logger,
        ):
            mock_batch_api = MagicMock()
            mock_batch_api_class.return_value = mock_batch_api
            mock_batch_api.create_namespaced_job.side_effect = client.exceptions.ApiException(
                status=409
            )
            mock_batch_api.patch_namespaced_job.return_value = None

            reconcile_repository(
                spec=spec,
                status=status,
                patch=mock_patch,
                name="test-repo",
                namespace="default",
                uid="uid-123",
                meta=meta_mock,
            )

        # Check that finalizer was added
        assert mock_patch.meta["finalizers"] == [FINALIZER_REPOSITORY]

        # Check that logging was called
        finalizer_log_calls = [
            call
            for call in mock_logger.info.call_args_list
            if "Added repository finalizer" in str(call)
        ]
        assert len(finalizer_log_calls) == 1

    def test_finalizer_not_added_if_already_present(self):
        """Test that finalizer is not added if already present."""
        spec: dict[str, Any] = {"url": "https://github.com/example/repo.git"}
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Create meta mock with finalizer already present
        meta_mock = MagicMock()
        # fmt: off
        meta_mock.get.side_effect = lambda key, default=None: (
            [FINALIZER_REPOSITORY]
            if key == "finalizers"
            else None
            if key == "deletionTimestamp"
            else MagicMock()
        )
        # fmt: on

        # Mock all Kubernetes API calls to prevent actual API calls
        with (
            patch("ansible_operator.main.client.BatchV1Api") as mock_batch_api_class,
            patch("ansible_operator.main.structured_logging.logger") as mock_logger,
        ):
            mock_batch_api = MagicMock()
            mock_batch_api_class.return_value = mock_batch_api
            mock_batch_api.create_namespaced_job.side_effect = client.exceptions.ApiException(
                status=409
            )
            mock_batch_api.patch_namespaced_job.return_value = None

            reconcile_repository(
                spec=spec,
                status=status,
                patch=mock_patch,
                name="test-repo",
                namespace="default",
                uid="uid-123",
                meta=meta_mock,
            )

        # Check that finalizer was not added again
        assert "finalizers" not in mock_patch.meta

        # Check that no finalizer logging was called
        finalizer_log_calls = [
            call for call in mock_logger.info.call_args_list if "FinalizerAdded" in str(call)
        ]
        assert len(finalizer_log_calls) == 0

    def test_finalizer_cleanup_on_delete_success(self):
        """Test finalizer cleanup when repository is deleted successfully."""
        spec: dict[str, Any] = {"url": "https://github.com/example/repo.git"}
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Create meta mock with deletion timestamp and finalizer
        meta_mock = MagicMock()
        meta_mock.get.side_effect = lambda key, default=None: (
            "2023-01-01T00:00:00Z"
            if key == "deletionTimestamp"
            else [FINALIZER_REPOSITORY] if key == "finalizers" else MagicMock()
        )

        # Mock successful job deletion
        mock_batch_api = MagicMock()
        mock_batch_api.delete_namespaced_job.return_value = None

        with (
            patch("ansible_operator.main.client.BatchV1Api", return_value=mock_batch_api),
            patch("ansible_operator.main.structured_logging.logger") as mock_logger,
            patch("ansible_operator.main._emit_event") as mock_emit,
        ):
            reconcile_repository(
                spec=spec,
                status=status,
                patch=mock_patch,
                name="test-repo",
                namespace="default",
                uid="uid-123",
                meta=meta_mock,
            )

        # Check that job deletion was called
        mock_batch_api.delete_namespaced_job.assert_called_once_with(
            name="test-repo-probe",
            namespace="default",
            propagation_policy="Background",
        )

        # Check that finalizer was removed
        assert mock_patch.meta["finalizers"] == []

        # Check logging calls
        log_calls = [call[0] for call in mock_logger.info.call_args_list]
        assert "Starting repository reconciliation" in log_calls[0]
        assert "Starting repository finalizer cleanup" in log_calls[1]
        assert "Probe job deletion initiated" in log_calls[2]
        assert "Repository finalizer cleanup completed" in log_calls[3]

        # Check event emission
        mock_emit.assert_called_once_with(
            kind="Repository",
            namespace="default",
            name="test-repo",
            reason="CleanupSucceeded",
            message="Repository finalizer cleanup completed successfully",
            type_="Normal",
        )

    def test_finalizer_cleanup_job_not_found(self):
        """Test finalizer cleanup when probe job is not found."""
        spec: dict[str, Any] = {"url": "https://github.com/example/repo.git"}
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Create meta mock with deletion timestamp and finalizer
        meta_mock = MagicMock()
        meta_mock.get.side_effect = lambda key, default=None: (
            "2023-01-01T00:00:00Z"
            if key == "deletionTimestamp"
            else [FINALIZER_REPOSITORY] if key == "finalizers" else MagicMock()
        )

        # Mock job not found (404 error)
        mock_batch_api = MagicMock()
        api_exception = client.exceptions.ApiException(status=404)
        mock_batch_api.delete_namespaced_job.side_effect = api_exception

        with (
            patch("ansible_operator.main.client.BatchV1Api", return_value=mock_batch_api),
            patch("ansible_operator.main.structured_logging.logger") as mock_logger,
            patch("ansible_operator.main._emit_event") as mock_emit,
        ):
            reconcile_repository(
                spec=spec,
                status=status,
                patch=mock_patch,
                name="test-repo",
                namespace="default",
                uid="uid-123",
                meta=meta_mock,
            )

        # Check that job deletion was attempted
        mock_batch_api.delete_namespaced_job.assert_called_once_with(
            name="test-repo-probe",
            namespace="default",
            propagation_policy="Background",
        )

        # Check that finalizer was removed
        assert mock_patch.meta["finalizers"] == []

        # Check logging calls
        log_calls = [call[0] for call in mock_logger.info.call_args_list]
        assert "Starting repository reconciliation" in log_calls[0]
        assert "Starting repository finalizer cleanup" in log_calls[1]
        assert "Probe job not found (already deleted)" in log_calls[2]
        assert "Repository finalizer cleanup completed" in log_calls[3]

        # Check event emission
        mock_emit.assert_called_once_with(
            kind="Repository",
            namespace="default",
            name="test-repo",
            reason="CleanupSucceeded",
            message="Repository finalizer cleanup completed successfully",
            type_="Normal",
        )

    def test_finalizer_cleanup_job_deletion_fails(self):
        """Test finalizer cleanup when probe job deletion fails."""
        spec: dict[str, Any] = {"url": "https://github.com/example/repo.git"}
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Create meta mock with deletion timestamp and finalizer
        meta_mock = MagicMock()
        meta_mock.get.side_effect = lambda key, default=None: (
            "2023-01-01T00:00:00Z"
            if key == "deletionTimestamp"
            else [FINALIZER_REPOSITORY] if key == "finalizers" else MagicMock()
        )

        # Mock job deletion failure (500 error)
        mock_batch_api = MagicMock()
        api_exception = client.exceptions.ApiException(status=500)
        mock_batch_api.delete_namespaced_job.side_effect = api_exception

        with (
            patch("ansible_operator.main.client.BatchV1Api", return_value=mock_batch_api),
            patch("ansible_operator.main.structured_logging.logger") as mock_logger,
            patch("ansible_operator.main._emit_event") as mock_emit,
        ):
            reconcile_repository(
                spec=spec,
                status=status,
                patch=mock_patch,
                name="test-repo",
                namespace="default",
                uid="uid-123",
                meta=meta_mock,
            )

        # Check that job deletion was attempted
        mock_batch_api.delete_namespaced_job.assert_called_once_with(
            name="test-repo-probe",
            namespace="default",
            propagation_policy="Background",
        )

        # Check that finalizer was removed (cleanup should continue even if job deletion fails)
        assert mock_patch.meta["finalizers"] == []

        # Check logging calls
        log_calls = [call[0] for call in mock_logger.info.call_args_list]
        error_log_calls = [call[0] for call in mock_logger.error.call_args_list]
        assert "Starting repository reconciliation" in log_calls[0]
        assert "Starting repository finalizer cleanup" in log_calls[1]
        assert "Failed to delete probe job: (500)" in error_log_calls[0][0]
        assert "Repository finalizer cleanup completed" in log_calls[2]

        # Check event emission
        mock_emit.assert_called_once_with(
            kind="Repository",
            namespace="default",
            name="test-repo",
            reason="CleanupFailed",
            message="Repository finalizer cleanup completed with errors",
            type_="Warning",
        )

    def test_finalizer_cleanup_no_finalizer_present(self):
        """Test that cleanup is skipped when no finalizer is present."""
        spec: dict[str, Any] = {"url": "https://github.com/example/repo.git"}
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Create meta mock with deletion timestamp but no finalizer
        meta_mock = MagicMock()
        meta_mock.get.side_effect = lambda key, default=None: (
            "2023-01-01T00:00:00Z"
            if key == "deletionTimestamp"
            else [] if key == "finalizers" else MagicMock()
        )

        with (
            patch("ansible_operator.main.client.BatchV1Api") as mock_batch_api_class,
            patch("ansible_operator.main.structured_logging.logger") as mock_logger,
            patch("ansible_operator.main._emit_event") as mock_emit,
        ):
            reconcile_repository(
                spec=spec,
                status=status,
                patch=mock_patch,
                name="test-repo",
                namespace="default",
                uid="uid-123",
                meta=meta_mock,
            )

        # Check that no job deletion was attempted
        mock_batch_api_class.assert_not_called()

        # Check that no finalizer changes were made
        assert "finalizers" not in mock_patch.meta

        # Check that no cleanup logging was called
        cleanup_log_calls = [
            call for call in mock_logger.info.call_args_list if "finalizer" in str(call)
        ]
        assert len(cleanup_log_calls) == 0

        # Check that no events were emitted
        mock_emit.assert_not_called()

    def test_finalizer_cleanup_partial_finalizer_removal(self):
        """Test finalizer cleanup when finalizer is not in the list."""
        spec: dict[str, Any] = {"url": "https://github.com/example/repo.git"}
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Create meta mock with deletion timestamp and different finalizer
        meta_mock = MagicMock()
        meta_mock.get.side_effect = lambda key, default=None: (
            "2023-01-01T00:00:00Z"
            if key == "deletionTimestamp"
            else ["other-finalizer"] if key == "finalizers" else MagicMock()
        )

        with (
            patch("ansible_operator.main.client.BatchV1Api") as mock_batch_api_class,
            patch("ansible_operator.main.structured_logging.logger") as mock_logger,
            patch("ansible_operator.main._emit_event") as mock_emit,
        ):
            reconcile_repository(
                spec=spec,
                status=status,
                patch=mock_patch,
                name="test-repo",
                namespace="default",
                uid="uid-123",
                meta=meta_mock,
            )

        # Check that no job deletion was attempted (wrong finalizer)
        mock_batch_api_class.assert_not_called()

        # Check that no finalizer changes were made
        assert "finalizers" not in mock_patch.meta

        # Check that no cleanup logging was called
        cleanup_log_calls = [
            call for call in mock_logger.info.call_args_list if "finalizer" in str(call)
        ]
        assert len(cleanup_log_calls) == 0

        # Check that no events were emitted
        mock_emit.assert_not_called()
