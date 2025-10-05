"""Unit tests for Schedule condition management and concurrency handling."""

from typing import Any
from unittest.mock import Mock, patch

import pytest
from kubernetes import client

from ansible_operator.constants import COND_BLOCKED_BY_CONCURRENCY, COND_READY
from ansible_operator.main import (
    _check_concurrent_jobs,
    _update_condition,
    _update_schedule_conditions,
)


class TestScheduleConditions:
    """Test Schedule condition management."""

    def test_update_condition_adds_new_condition(self):
        """Test that _update_condition adds a new condition."""
        status: dict[str, Any] = {"conditions": []}

        _update_condition(status, "TestCondition", "True", "TestReason", "Test message")

        assert len(status["conditions"]) == 1
        condition = status["conditions"][0]
        assert condition["type"] == "TestCondition"
        assert condition["status"] == "True"
        assert condition["reason"] == "TestReason"
        assert condition["message"] == "Test message"

    def test_update_condition_replaces_existing_condition(self):
        """Test that _update_condition replaces existing condition of same type."""
        status = {
            "conditions": [
                {
                    "type": "TestCondition",
                    "status": "False",
                    "reason": "OldReason",
                    "message": "Old message",
                },
                {
                    "type": "OtherCondition",
                    "status": "True",
                    "reason": "OtherReason",
                    "message": "Other message",
                },
            ]
        }

        _update_condition(status, "TestCondition", "True", "NewReason", "New message")

        assert len(status["conditions"]) == 2
        test_condition = next(c for c in status["conditions"] if c["type"] == "TestCondition")
        assert test_condition["status"] == "True"
        assert test_condition["reason"] == "NewReason"
        assert test_condition["message"] == "New message"

        other_condition = next(c for c in status["conditions"] if c["type"] == "OtherCondition")
        assert other_condition["status"] == "True"  # Unchanged

    @patch("ansible_operator.main.client.BatchV1Api")
    def test_check_concurrent_jobs_no_active_jobs(self, mock_batch_api):
        """Test _check_concurrent_jobs when no active jobs exist."""
        mock_api_instance = Mock()
        mock_batch_api.return_value = mock_api_instance

        # Mock empty job list
        mock_job_list = Mock()
        mock_job_list.items = []
        mock_api_instance.list_namespaced_job.return_value = mock_job_list

        has_concurrent, reason = _check_concurrent_jobs("test-ns", "test-schedule", "test-uid")

        assert has_concurrent is False
        assert reason == ""
        mock_api_instance.list_namespaced_job.assert_called_once_with(
            namespace="test-ns",
            label_selector="ansible.cloud37.dev/owner-uid=test-uid",
        )

    @patch("ansible_operator.main.client.BatchV1Api")
    def test_check_concurrent_jobs_with_active_jobs(self, mock_batch_api):
        """Test _check_concurrent_jobs when active jobs exist."""
        mock_api_instance = Mock()
        mock_batch_api.return_value = mock_api_instance

        # Mock job with active status
        mock_job = Mock()
        mock_job.metadata.name = "test-job-1"
        mock_job.status.active = 1
        mock_job.status.succeeded = None
        mock_job.status.failed = None

        mock_job_list = Mock()
        mock_job_list.items = [mock_job]
        mock_api_instance.list_namespaced_job.return_value = mock_job_list

        has_concurrent, reason = _check_concurrent_jobs("test-ns", "test-schedule", "test-uid")

        assert has_concurrent is True
        assert "test-job-1" in reason

    @patch("ansible_operator.main.client.BatchV1Api")
    def test_check_concurrent_jobs_with_pending_jobs(self, mock_batch_api):
        """Test _check_concurrent_jobs when jobs are pending (not completed)."""
        mock_api_instance = Mock()
        mock_batch_api.return_value = mock_api_instance

        # Mock job that's pending (no active, succeeded, or failed)
        mock_job = Mock()
        mock_job.metadata.name = "test-job-2"
        mock_job.status.active = None
        mock_job.status.succeeded = None
        mock_job.status.failed = None

        mock_job_list = Mock()
        mock_job_list.items = [mock_job]
        mock_api_instance.list_namespaced_job.return_value = mock_job_list

        has_concurrent, reason = _check_concurrent_jobs("test-ns", "test-schedule", "test-uid")

        assert has_concurrent is True
        assert "test-job-2" in reason

    @patch("ansible_operator.main.client.BatchV1Api")
    def test_check_concurrent_jobs_with_completed_jobs(self, mock_batch_api):
        """Test _check_concurrent_jobs when jobs are completed."""
        mock_api_instance = Mock()
        mock_batch_api.return_value = mock_api_instance

        # Mock completed job
        mock_job = Mock()
        mock_job.metadata.name = "test-job-3"
        mock_job.status.active = 0
        mock_job.status.succeeded = 1
        mock_job.status.failed = None

        mock_job_list = Mock()
        mock_job_list.items = [mock_job]
        mock_api_instance.list_namespaced_job.return_value = mock_job_list

        has_concurrent, reason = _check_concurrent_jobs("test-ns", "test-schedule", "test-uid")

        assert has_concurrent is False
        assert reason == ""

    @patch("ansible_operator.main.client.BatchV1Api")
    def test_check_concurrent_jobs_api_exception(self, mock_batch_api):
        """Test _check_concurrent_jobs handles API exceptions gracefully."""
        mock_api_instance = Mock()
        mock_batch_api.return_value = mock_api_instance
        mock_api_instance.list_namespaced_job.side_effect = Exception("API Error")

        has_concurrent, reason = _check_concurrent_jobs("test-ns", "test-schedule", "test-uid")

        # Should fail open (no blocking)
        assert has_concurrent is False
        assert reason == ""

    def test_update_schedule_conditions_ready_state(self):
        """Test _update_schedule_conditions for ready state."""
        patch_status: dict[str, Any] = {}
        spec = {"concurrencyPolicy": "Forbid"}

        with patch("ansible_operator.main._check_concurrent_jobs", return_value=(False, "")):
            with patch("ansible_operator.main._emit_event") as mock_emit:
                _update_schedule_conditions(
                    patch_status, "test-ns", "test-schedule", "test-uid", spec, True, True
                )

        conditions = patch_status["conditions"]
        assert len(conditions) == 2

        ready_condition = next(c for c in conditions if c["type"] == COND_READY)
        assert ready_condition["status"] == "True"
        assert ready_condition["reason"] == "Ready"

        blocked_condition = next(c for c in conditions if c["type"] == COND_BLOCKED_BY_CONCURRENCY)
        assert blocked_condition["status"] == "False"
        assert blocked_condition["reason"] == "NoConcurrentJobs"

        # Should emit events for both conditions
        assert mock_emit.call_count == 2

    def test_update_schedule_conditions_cronjob_missing(self):
        """Test _update_schedule_conditions when CronJob is missing."""
        patch_status: dict[str, Any] = {}
        spec = {"concurrencyPolicy": "Forbid"}

        with patch("ansible_operator.main._check_concurrent_jobs", return_value=(False, "")):
            _update_schedule_conditions(
                patch_status, "test-ns", "test-schedule", "test-uid", spec, False, True
            )

        conditions = patch_status["conditions"]
        ready_condition = next(c for c in conditions if c["type"] == COND_READY)
        assert ready_condition["status"] == "False"
        assert ready_condition["reason"] == "CronJobMissing"

    def test_update_schedule_conditions_playbook_not_ready(self):
        """Test _update_schedule_conditions when Playbook is not ready."""
        patch_status: dict[str, Any] = {}
        spec = {"concurrencyPolicy": "Forbid"}

        with patch("ansible_operator.main._check_concurrent_jobs", return_value=(False, "")):
            _update_schedule_conditions(
                patch_status, "test-ns", "test-schedule", "test-uid", spec, True, False
            )

        conditions = patch_status["conditions"]
        ready_condition = next(c for c in conditions if c["type"] == COND_READY)
        assert ready_condition["status"] == "False"
        assert ready_condition["reason"] == "PlaybookNotReady"

    def test_update_schedule_conditions_blocked_by_concurrency(self):
        """Test _update_schedule_conditions when blocked by concurrency."""
        patch_status: dict[str, Any] = {}
        spec = {"concurrencyPolicy": "Forbid"}

        with patch(
            "ansible_operator.main._check_concurrent_jobs",
            return_value=(True, "Active Jobs: job-1"),
        ):
            with patch("ansible_operator.main._emit_event") as mock_emit:
                _update_schedule_conditions(
                    patch_status, "test-ns", "test-schedule", "test-uid", spec, True, True
                )

        conditions = patch_status["conditions"]

        ready_condition = next(c for c in conditions if c["type"] == COND_READY)
        assert ready_condition["status"] == "False"
        assert ready_condition["reason"] == "BlockedByConcurrency"
        assert "job-1" in ready_condition["message"]

        blocked_condition = next(c for c in conditions if c["type"] == COND_BLOCKED_BY_CONCURRENCY)
        assert blocked_condition["status"] == "True"
        assert blocked_condition["reason"] == "ConcurrentJobsRunning"
        assert "job-1" in blocked_condition["message"]

        # Should emit events for both conditions
        assert mock_emit.call_count == 2

        # Check that Warning events are emitted for blocked conditions
        warning_calls = [call for call in mock_emit.call_args_list if call[1]["type_"] == "Warning"]
        assert len(warning_calls) == 2

    def test_update_schedule_conditions_allow_concurrency_policy(self):
        """Test _update_schedule_conditions with Allow concurrency policy."""
        patch_status: dict[str, Any] = {}
        spec = {"concurrencyPolicy": "Allow"}

        with patch(
            "ansible_operator.main._check_concurrent_jobs",
            return_value=(True, "Active Jobs: job-1"),
        ):
            _update_schedule_conditions(
                patch_status, "test-ns", "test-schedule", "test-uid", spec, True, True
            )

        conditions = patch_status["conditions"]

        # With Allow policy, concurrent jobs should not block Ready condition
        ready_condition = next(c for c in conditions if c["type"] == COND_READY)
        assert ready_condition["status"] == "True"
        assert ready_condition["reason"] == "Ready"

        # But BlockedByConcurrency should still reflect the concurrent state
        blocked_condition = next(c for c in conditions if c["type"] == COND_BLOCKED_BY_CONCURRENCY)
        assert blocked_condition["status"] == "True"
        assert blocked_condition["reason"] == "ConcurrentJobsRunning"

    def test_update_schedule_conditions_replace_concurrency_policy(self):
        """Test _update_schedule_conditions with Replace concurrency policy."""
        patch_status: dict[str, Any] = {}
        spec = {"concurrencyPolicy": "Replace"}

        with patch(
            "ansible_operator.main._check_concurrent_jobs",
            return_value=(True, "Active Jobs: job-1"),
        ):
            _update_schedule_conditions(
                patch_status, "test-ns", "test-schedule", "test-uid", spec, True, True
            )

        conditions = patch_status["conditions"]

        # With Replace policy, concurrent jobs should not block Ready condition
        ready_condition = next(c for c in conditions if c["type"] == COND_READY)
        assert ready_condition["status"] == "True"
        assert ready_condition["reason"] == "Ready"

        # But BlockedByConcurrency should still reflect the concurrent state
        blocked_condition = next(c for c in conditions if c["type"] == COND_BLOCKED_BY_CONCURRENCY)
        assert blocked_condition["status"] == "True"
        assert blocked_condition["reason"] == "ConcurrentJobsRunning"

    def test_update_schedule_conditions_default_concurrency_policy(self):
        """Test _update_schedule_conditions with default (Forbid) concurrency policy."""
        patch_status: dict[str, Any] = {}
        spec: dict[str, Any] = {}  # No concurrencyPolicy specified, should default to Forbid

        with patch(
            "ansible_operator.main._check_concurrent_jobs",
            return_value=(True, "Active Jobs: job-1"),
        ):
            _update_schedule_conditions(
                patch_status, "test-ns", "test-schedule", "test-uid", spec, True, True
            )

        conditions = patch_status["conditions"]

        # Should behave like Forbid policy
        ready_condition = next(c for c in conditions if c["type"] == COND_READY)
        assert ready_condition["status"] == "False"
        assert ready_condition["reason"] == "BlockedByConcurrency"

    def test_update_schedule_conditions_no_event_on_no_change(self):
        """Test _update_schedule_conditions doesn't emit events when conditions don't change."""
        patch_status: dict[str, Any] = {}
        spec = {"concurrencyPolicy": "Forbid"}

        # Simulate existing conditions that match what we would set
        current_status = {
            "conditions": [
                {
                    "type": COND_READY,
                    "status": "True",
                    "reason": "Ready",
                    "message": "Schedule is ready",
                },
                {
                    "type": COND_BLOCKED_BY_CONCURRENCY,
                    "status": "False",
                    "reason": "NoConcurrentJobs",
                    "message": "No concurrent Jobs running",
                },
            ]
        }

        with patch("ansible_operator.main._check_concurrent_jobs", return_value=(False, "")):
            with patch("ansible_operator.main._emit_event") as mock_emit:
                _update_schedule_conditions(
                    patch_status,
                    "test-ns",
                    "test-schedule",
                    "test-uid",
                    spec,
                    True,
                    True,
                    current_status,
                )

        # Should not emit any events since conditions didn't change
        assert mock_emit.call_count == 0

        # Conditions should not be updated since they didn't change
        assert "conditions" not in patch_status
