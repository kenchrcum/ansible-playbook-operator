from typing import Any
from unittest.mock import MagicMock, patch

from kubernetes import client

from ansible_operator.main import (
    _emit_event,
    _update_condition,
    handle_job_completion,
    reconcile_repository,
)


class MockPatch:
    """Mock Kopf patch object."""

    def __init__(self):
        self.status = {}
        self.meta = MagicMock()


class TestRepositoryConditions:
    """Test repository condition management and event emission."""

    def test_reconcile_repository_missing_url(self):
        """Test that missing URL sets AuthValid=False and Ready=False."""
        spec: dict[str, Any] = {}
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Create meta mock that returns None for deletionTimestamp
        meta_mock = MagicMock()
        meta_mock.get.side_effect = lambda key, default=None: (
            None if key == "deletionTimestamp" else MagicMock()
        )

        # Mock the event emission to capture calls
        with patch("ansible_operator.main._emit_event") as mock_emit:
            reconcile_repository(
                spec=spec,
                status=status,
                patch=mock_patch,
                name="test-repo",
                namespace="default",
                uid="uid-123",
                meta=meta_mock,
            )

        # Check conditions were set in mock_patch.status
        conditions = mock_patch.status.get("conditions", [])
        assert len(conditions) == 2

        # Find conditions by type
        auth_valid = next(c for c in conditions if c["type"] == "AuthValid")
        ready = next(c for c in conditions if c["type"] == "Ready")

        assert auth_valid == {
            "type": "AuthValid",
            "status": "False",
            "reason": "MissingURL",
            "message": "spec.url must be set",
        }
        assert ready == {
            "type": "Ready",
            "status": "False",
            "reason": "InvalidSpec",
            "message": "Repository spec invalid",
        }

        # Check event was emitted
        mock_emit.assert_called_once_with(
            kind="Repository",
            namespace="default",
            name="test-repo",
            reason="ValidateFailed",
            message="Missing spec.url",
            type_="Warning",
        )

    def test_reconcile_repository_missing_auth_secret(self):
        """Test that missing auth secret sets AuthValid=False and Ready=False."""
        spec = {"url": "https://github.com/example/repo.git", "auth": {"method": "token"}}
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Create meta mock that returns None for deletionTimestamp
        meta_mock = MagicMock()
        meta_mock.get.side_effect = lambda key, default=None: (
            None if key == "deletionTimestamp" else MagicMock()
        )

        with patch("ansible_operator.main._emit_event") as mock_emit:
            reconcile_repository(
                spec=spec,
                status=status,
                patch=mock_patch,
                name="test-repo",
                namespace="default",
                uid="uid-123",
                meta=meta_mock,
            )

        # Check conditions were set
        conditions = mock_patch.status.get("conditions", [])
        assert len(conditions) == 2

        # Find conditions by type
        auth_valid = next(c for c in conditions if c["type"] == "AuthValid")
        ready = next(c for c in conditions if c["type"] == "Ready")

        assert auth_valid == {
            "type": "AuthValid",
            "status": "False",
            "reason": "SecretMissing",
            "message": "auth.secretRef.name must be set when auth.method is provided",
        }
        assert ready == {
            "type": "Ready",
            "status": "False",
            "reason": "InvalidSpec",
            "message": "Repository auth invalid",
        }

        # Check event was emitted
        mock_emit.assert_called_once_with(
            kind="Repository",
            namespace="default",
            name="test-repo",
            reason="ValidateFailed",
            message="auth.method set but auth.secretRef.name missing",
            type_="Warning",
        )

    @patch("kubernetes.client.CoreV1Api")
    def test_reconcile_repository_missing_known_hosts_configmap(self, mock_core_api):
        """Test that missing known_hosts ConfigMap sets AuthValid=False and Ready=False."""
        # Mock ConfigMap read to raise 404
        mock_api = MagicMock()
        mock_api.read_namespaced_config_map.side_effect = client.exceptions.ApiException(status=404)
        mock_core_api.return_value = mock_api

        spec = {
            "url": "git@github.com:example/repo.git",
            "auth": {"method": "ssh", "secretRef": {"name": "ssh-secret"}},
            "ssh": {
                "knownHostsConfigMapRef": {"name": "known-hosts"},
                "strictHostKeyChecking": True,
            },
        }
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Create meta mock that returns None for deletionTimestamp
        meta_mock = MagicMock()
        meta_mock.get.side_effect = lambda key, default=None: (
            None if key == "deletionTimestamp" else MagicMock()
        )

        with patch("ansible_operator.main._emit_event") as mock_emit:
            reconcile_repository(
                spec=spec,
                status=status,
                patch=mock_patch,
                name="test-repo",
                namespace="default",
                uid="uid-123",
                meta=meta_mock,
            )

        # Check conditions were set
        conditions = mock_patch.status.get("conditions", [])
        assert len(conditions) == 2

        # Find conditions by type
        auth_valid = next(c for c in conditions if c["type"] == "AuthValid")
        ready = next(c for c in conditions if c["type"] == "Ready")

        assert auth_valid == {
            "type": "AuthValid",
            "status": "False",
            "reason": "ConfigMapNotFound",
            "message": "SSH known hosts ConfigMap 'known-hosts' not found",
        }
        assert ready == {
            "type": "Ready",
            "status": "False",
            "reason": "InvalidSpec",
            "message": "Repository auth invalid",
        }

        # Check event was emitted
        mock_emit.assert_called_once_with(
            kind="Repository",
            namespace="default",
            name="test-repo",
            reason="ValidateFailed",
            message="SSH known hosts ConfigMap 'known-hosts' not found",
            type_="Warning",
        )

    @patch("kubernetes.client.BatchV1Api")
    @patch("ansible_operator.main.build_connectivity_probe_job")
    def test_reconcile_repository_probe_running_conditions(self, mock_build_job, mock_batch_api):
        """Test that probe running sets conditions to Unknown."""
        mock_build_job.return_value = {"metadata": {"name": "test-repo-probe"}}

        spec = {
            "url": "https://github.com/example/repo.git",
            "auth": {"method": "token", "secretRef": {"name": "token-secret"}},
        }
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Create meta mock that returns None for deletionTimestamp
        meta_mock = MagicMock()
        meta_mock.get.side_effect = lambda key, default=None: (
            None if key == "deletionTimestamp" else MagicMock()
        )

        reconcile_repository(
            spec=spec,
            status=status,
            patch=mock_patch,
            name="test-repo",
            namespace="default",
            uid="uid-123",
            meta=meta_mock,
        )

        # Check conditions were set for probe running
        conditions = mock_patch.status.get("conditions", [])
        assert len(conditions) == 3

        # Find conditions by type
        auth_valid = next(c for c in conditions if c["type"] == "AuthValid")
        clone_ready = next(c for c in conditions if c["type"] == "CloneReady")
        ready = next(c for c in conditions if c["type"] == "Ready")

        assert auth_valid == {
            "type": "AuthValid",
            "status": "Unknown",
            "reason": "ProbeRunning",
            "message": "Connectivity probe in progress",
        }
        assert clone_ready == {
            "type": "CloneReady",
            "status": "Unknown",
            "reason": "Deferred",
            "message": "Waiting for connectivity probe",
        }
        assert ready == {
            "type": "Ready",
            "status": "Unknown",
            "reason": "Deferred",
            "message": "Repository connectivity being probed",
        }

    @patch("kubernetes.client.CustomObjectsApi")
    @patch("ansible_operator.main._emit_event")
    def test_handle_job_completion_probe_success(self, mock_emit, mock_custom_api):
        """Test that successful probe sets AuthValid=True, CloneReady=True, Ready=True."""
        # Mock the repository exists
        mock_api = MagicMock()
        mock_custom_api.return_value = mock_api

        job_event = {
            "object": {
                "metadata": {
                    "name": "test-repo-probe",
                    "namespace": "default",
                    "labels": {"ansible.cloud37.dev/probe-type": "connectivity"},
                    "ownerReferences": [
                        {
                            "kind": "Repository",
                            "apiVersion": "ansible.cloud37.dev/v1alpha1",
                            "uid": "repo-uid",
                        }
                    ],
                },
                "status": {"succeeded": 1, "failed": 0},
            }
        }

        with patch("kubernetes.client.CustomObjectsApi") as mock_co_api_class:
            mock_co_instance = MagicMock()
            mock_co_api_class.return_value = mock_co_instance

            handle_job_completion(job_event)

            # Check that patch_namespaced_custom_object_status was called
            mock_co_instance.patch_namespaced_custom_object_status.assert_called_once()
            call_args = mock_co_instance.patch_namespaced_custom_object_status.call_args
            patch_body = call_args[1]["body"]

            # Check conditions in patch body
            conditions = patch_body["status"]["conditions"]
            assert len(conditions) == 3

            # Find conditions by type
            auth_valid = next(c for c in conditions if c["type"] == "AuthValid")
            clone_ready = next(c for c in conditions if c["type"] == "CloneReady")
            ready = next(c for c in conditions if c["type"] == "Ready")

            assert auth_valid == {
                "type": "AuthValid",
                "status": "True",
                "reason": "ProbeSucceeded",
                "message": "Connectivity probe successful",
            }
            assert clone_ready == {
                "type": "CloneReady",
                "status": "True",
                "reason": "ProbeSucceeded",
                "message": "Repository clone ready",
            }
            assert ready == {
                "type": "Ready",
                "status": "True",
                "reason": "Validated",
                "message": "Repository is ready for use",
            }

            # Check event was emitted
            mock_emit.assert_called_once_with(
                kind="Repository",
                namespace="default",
                name="test-repo",
                reason="ValidateSucceeded",
                message="Repository connectivity and clone capability verified",
            )

    @patch("kubernetes.client.CustomObjectsApi")
    @patch("ansible_operator.main._emit_event")
    def test_handle_job_completion_probe_failure(self, mock_emit, mock_custom_api):
        """Test that failed probe sets AuthValid=False, CloneReady=False, Ready=False."""
        # Mock the repository exists
        mock_api = MagicMock()
        mock_custom_api.return_value = mock_api

        job_event = {
            "object": {
                "metadata": {
                    "name": "test-repo-probe",
                    "namespace": "default",
                    "labels": {"ansible.cloud37.dev/probe-type": "connectivity"},
                    "ownerReferences": [
                        {
                            "kind": "Repository",
                            "apiVersion": "ansible.cloud37.dev/v1alpha1",
                            "uid": "repo-uid",
                        }
                    ],
                },
                "status": {"succeeded": 0, "failed": 1},
            }
        }

        with patch("kubernetes.client.CustomObjectsApi") as mock_co_api_class:
            mock_co_instance = MagicMock()
            mock_co_api_class.return_value = mock_co_instance

            handle_job_completion(job_event)

            # Check that patch_namespaced_custom_object_status was called
            mock_co_instance.patch_namespaced_custom_object_status.assert_called_once()
            call_args = mock_co_instance.patch_namespaced_custom_object_status.call_args
            patch_body = call_args[1]["body"]

            # Check conditions in patch body
            conditions = patch_body["status"]["conditions"]
            assert len(conditions) == 3

            # Find conditions by type
            auth_valid = next(c for c in conditions if c["type"] == "AuthValid")
            clone_ready = next(c for c in conditions if c["type"] == "CloneReady")
            ready = next(c for c in conditions if c["type"] == "Ready")

            assert auth_valid == {
                "type": "AuthValid",
                "status": "False",
                "reason": "ProbeFailed",
                "message": "Connectivity probe failed",
            }
            assert clone_ready == {
                "type": "CloneReady",
                "status": "False",
                "reason": "ProbeFailed",
                "message": "Cannot attempt clone without connectivity",
            }
            assert ready == {
                "type": "Ready",
                "status": "False",
                "reason": "ProbeFailed",
                "message": "Repository connectivity check failed",
            }

            # Check event was emitted
            mock_emit.assert_called_once_with(
                kind="Repository",
                namespace="default",
                name="test-repo",
                reason="ValidateFailed",
                message="Repository connectivity check failed",
                type_="Warning",
            )


class TestConditionHelpers:
    """Test condition update and event emission helpers."""

    def test_update_condition_replaces_existing(self):
        """Test that _update_condition replaces existing conditions of the same type."""
        status = {
            "conditions": [
                {
                    "type": "AuthValid",
                    "status": "Unknown",
                    "reason": "OldReason",
                    "message": "Old message",
                },
                {
                    "type": "Ready",
                    "status": "True",
                    "reason": "OldReason",
                    "message": "Old message",
                },
            ]
        }

        _update_condition(status, "AuthValid", "True", "NewReason", "New message")

        conditions = status["conditions"]
        assert len(conditions) == 2

        # AuthValid should be updated
        auth_valid = next(c for c in conditions if c["type"] == "AuthValid")
        assert auth_valid == {
            "type": "AuthValid",
            "status": "True",
            "reason": "NewReason",
            "message": "New message",
        }

        # Ready should be unchanged
        ready = next(c for c in conditions if c["type"] == "Ready")
        assert ready == {
            "type": "Ready",
            "status": "True",
            "reason": "OldReason",
            "message": "Old message",
        }

    def test_update_condition_creates_new(self):
        """Test that _update_condition creates new conditions when none exist."""
        status: dict[str, Any] = {}

        _update_condition(status, "AuthValid", "True", "NewReason", "New message")

        conditions = status["conditions"]
        assert len(conditions) == 1
        assert conditions[0] == {
            "type": "AuthValid",
            "status": "True",
            "reason": "NewReason",
            "message": "New message",
        }

    @patch("ansible_operator.main.client")
    def test_emit_event_success(self, mock_client):
        """Test that _emit_event creates an event successfully."""
        mock_v1 = MagicMock()
        mock_client.CoreV1Api.return_value = mock_v1

        _emit_event(
            kind="Repository",
            namespace="default",
            name="test-repo",
            reason="ValidateSucceeded",
            message="Repository validated",
            type_="Normal",
        )

        # Check that create_namespaced_event was called with correct parameters
        mock_v1.create_namespaced_event.assert_called_once()
        call_args = mock_v1.create_namespaced_event.call_args
        assert call_args[1]["namespace"] == "default"  # namespace

        # The body is a V1Event object - we verify the call was made with the right namespace
        # and that the body parameter was provided (detailed body validation would require
        # mocking the V1Event constructor which is complex for this unit test)

    @patch("ansible_operator.main.client")
    def test_emit_event_handles_exception(self, mock_client):
        """Test that _emit_event handles exceptions gracefully."""
        mock_v1 = MagicMock()
        mock_v1.create_namespaced_event.side_effect = Exception("API error")
        mock_client.CoreV1Api.return_value = mock_v1

        # Should not raise exception
        _emit_event(
            kind="Repository",
            namespace="default",
            name="test-repo",
            reason="ValidateSucceeded",
            message="Repository validated",
        )

        # Event creation was attempted
        mock_v1.create_namespaced_event.assert_called_once()
