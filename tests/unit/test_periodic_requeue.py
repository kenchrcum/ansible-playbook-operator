"""Unit tests for periodic Schedule requeue functionality."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock, patch
from typing import Any

import pytest

from ansible_operator.constants import API_GROUP
from ansible_operator.main import periodic_schedule_requeue


class TestPeriodicScheduleRequeue:
    """Test cases for periodic Schedule requeue functionality."""

    @patch("ansible_operator.main.client.BatchV1Api")
    @patch("ansible_operator.main.client.CustomObjectsApi")
    def test_periodic_requeue_updates_next_run_time(
        self, mock_custom_api_class: Mock, mock_batch_api_class: Mock
    ) -> None:
        """Test that periodic requeue updates nextRunTime when it differs."""
        mock_batch_api = Mock()
        mock_batch_api_class.return_value = mock_batch_api

        mock_custom_api = Mock()
        mock_custom_api_class.return_value = mock_custom_api

        # Mock CronJob with nextScheduleTime
        next_schedule_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        cronjob_status = Mock()
        cronjob_status.next_schedule_time = next_schedule_time

        cronjob = Mock()
        cronjob.status = cronjob_status
        mock_batch_api.read_namespaced_cron_job.return_value = cronjob

        # Mock Schedule with different nextRunTime
        schedule_status = {"nextRunTime": "2024-01-01T12:00:00Z"}

        # Call the periodic requeue function
        periodic_schedule_requeue(
            name="test-schedule",
            namespace="test-namespace",
            uid="schedule-uid-123",
            spec={},
            status=schedule_status,
        )

        # Verify CronJob was read
        mock_batch_api.read_namespaced_cron_job.assert_called_once_with(
            "schedule-test-schedule", "test-namespace"
        )

        # Verify Schedule status was updated
        mock_custom_api.patch_namespaced_custom_object_status.assert_called_once()
        call_args = mock_custom_api.patch_namespaced_custom_object_status.call_args

        assert call_args[1]["group"] == API_GROUP
        assert call_args[1]["version"] == "v1alpha1"
        assert call_args[1]["namespace"] == "test-namespace"
        assert call_args[1]["plural"] == "schedules"
        assert call_args[1]["name"] == "test-schedule"
        assert call_args[1]["field_manager"] == "ansible-operator"

        # Verify the patch body
        patch_body = call_args[1]["body"]
        assert patch_body["status"]["nextRunTime"] == "2024-01-01T13:00:00+00:00Z"

    @patch("ansible_operator.main.client.BatchV1Api")
    @patch("ansible_operator.main.client.CustomObjectsApi")
    def test_periodic_requeue_skips_update_when_next_run_time_matches(
        self, mock_custom_api_class: Mock, mock_batch_api_class: Mock
    ) -> None:
        """Test that periodic requeue skips update when nextRunTime matches."""
        mock_batch_api = Mock()
        mock_batch_api_class.return_value = mock_batch_api

        mock_custom_api = Mock()
        mock_custom_api_class.return_value = mock_custom_api

        # Mock CronJob with nextScheduleTime
        next_schedule_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        cronjob_status = Mock()
        cronjob_status.next_schedule_time = next_schedule_time

        cronjob = Mock()
        cronjob.status = cronjob_status
        mock_batch_api.read_namespaced_cron_job.return_value = cronjob

        # Mock Schedule with matching nextRunTime
        schedule_status = {"nextRunTime": "2024-01-01T13:00:00+00:00Z"}

        # Call the periodic requeue function
        periodic_schedule_requeue(
            name="test-schedule",
            namespace="test-namespace",
            uid="schedule-uid-123",
            spec={},
            status=schedule_status,
        )

        # Verify CronJob was read
        mock_batch_api.read_namespaced_cron_job.assert_called_once_with(
            "schedule-test-schedule", "test-namespace"
        )

        # Verify Schedule status was NOT updated
        mock_custom_api.patch_namespaced_custom_object_status.assert_not_called()

    @patch("ansible_operator.main.client.BatchV1Api")
    @patch("ansible_operator.main.client.CustomObjectsApi")
    def test_periodic_requeue_handles_cronjob_not_found(
        self, mock_custom_api_class: Mock, mock_batch_api_class: Mock
    ) -> None:
        """Test that periodic requeue handles CronJob not found gracefully."""
        mock_batch_api = Mock()
        mock_batch_api_class.return_value = mock_batch_api

        mock_custom_api = Mock()
        mock_custom_api_class.return_value = mock_custom_api

        # Mock CronJob not found (404)
        from kubernetes.client.exceptions import ApiException

        mock_batch_api.read_namespaced_cron_job.side_effect = ApiException(status=404)

        # Call the periodic requeue function
        periodic_schedule_requeue(
            name="test-schedule",
            namespace="test-namespace",
            uid="schedule-uid-123",
            spec={},
            status={},
        )

        # Verify CronJob was attempted to be read
        mock_batch_api.read_namespaced_cron_job.assert_called_once_with(
            "schedule-test-schedule", "test-namespace"
        )

        # Verify Schedule status was NOT updated
        mock_custom_api.patch_namespaced_custom_object_status.assert_not_called()

    @patch("ansible_operator.main.client.BatchV1Api")
    @patch("ansible_operator.main.client.CustomObjectsApi")
    def test_periodic_requeue_handles_cronjob_without_next_schedule_time(
        self, mock_custom_api_class: Mock, mock_batch_api_class: Mock
    ) -> None:
        """Test that periodic requeue handles CronJob without nextScheduleTime."""
        mock_batch_api = Mock()
        mock_batch_api_class.return_value = mock_batch_api

        mock_custom_api = Mock()
        mock_custom_api_class.return_value = mock_custom_api

        # Mock CronJob without nextScheduleTime
        cronjob_status = Mock()
        cronjob_status.next_schedule_time = None

        cronjob = Mock()
        cronjob.status = cronjob_status
        mock_batch_api.read_namespaced_cron_job.return_value = cronjob

        # Call the periodic requeue function
        periodic_schedule_requeue(
            name="test-schedule",
            namespace="test-namespace",
            uid="schedule-uid-123",
            spec={},
            status={},
        )

        # Verify CronJob was read
        mock_batch_api.read_namespaced_cron_job.assert_called_once_with(
            "schedule-test-schedule", "test-namespace"
        )

        # Verify Schedule status was NOT updated
        mock_custom_api.patch_namespaced_custom_object_status.assert_not_called()

    @patch("ansible_operator.main.client.BatchV1Api")
    @patch("ansible_operator.main.client.CustomObjectsApi")
    def test_periodic_requeue_handles_api_exception(
        self, mock_custom_api_class: Mock, mock_batch_api_class: Mock
    ) -> None:
        """Test that periodic requeue handles API exceptions gracefully."""
        mock_batch_api = Mock()
        mock_batch_api_class.return_value = mock_batch_api

        mock_custom_api = Mock()
        mock_custom_api_class.return_value = mock_custom_api

        # Mock API exception (non-404)
        from kubernetes.client.exceptions import ApiException

        mock_batch_api.read_namespaced_cron_job.side_effect = ApiException(status=500)

        # Call the periodic requeue function
        periodic_schedule_requeue(
            name="test-schedule",
            namespace="test-namespace",
            uid="schedule-uid-123",
            spec={},
            status={},
        )

        # Verify CronJob was attempted to be read
        mock_batch_api.read_namespaced_cron_job.assert_called_once_with(
            "schedule-test-schedule", "test-namespace"
        )

        # Verify Schedule status was NOT updated
        mock_custom_api.patch_namespaced_custom_object_status.assert_not_called()

    @patch("ansible_operator.main.client.BatchV1Api")
    @patch("ansible_operator.main.client.CustomObjectsApi")
    def test_periodic_requeue_handles_general_exception(
        self, mock_custom_api_class: Mock, mock_batch_api_class: Mock
    ) -> None:
        """Test that periodic requeue handles general exceptions gracefully."""
        mock_batch_api = Mock()
        mock_batch_api_class.return_value = mock_batch_api

        mock_custom_api = Mock()
        mock_custom_api_class.return_value = mock_custom_api

        # Mock general exception
        mock_batch_api.read_namespaced_cron_job.side_effect = Exception("Test error")

        # Call the periodic requeue function
        periodic_schedule_requeue(
            name="test-schedule",
            namespace="test-namespace",
            uid="schedule-uid-123",
            spec={},
            status={},
        )

        # Verify CronJob was attempted to be read
        mock_batch_api.read_namespaced_cron_job.assert_called_once_with(
            "schedule-test-schedule", "test-namespace"
        )

        # Verify Schedule status was NOT updated
        mock_custom_api.patch_namespaced_custom_object_status.assert_not_called()
