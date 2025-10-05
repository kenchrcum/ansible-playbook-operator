"""Unit tests for Schedule status field updates from CronJob/Job observations."""

from __future__ import annotations

from unittest.mock import Mock, patch
from typing import Any

import pytest

from ansible_operator.constants import (
    API_GROUP,
    LABEL_MANAGED_BY,
    LABEL_OWNER_KIND,
    LABEL_OWNER_NAME,
    LABEL_OWNER_UID,
)
from ansible_operator.main import handle_cronjob_event, handle_schedule_job_event


class TestScheduleStatusUpdates:
    """Test cases for Schedule status field updates."""

    @patch("ansible_operator.main.client.CustomObjectsApi")
    def test_handle_cronjob_event_updates_status_fields(self, mock_api_class: Mock) -> None:
        """Test that CronJob events update Schedule status fields."""
        mock_api = Mock()
        mock_api_class.return_value = mock_api

        # Mock CronJob event
        cronjob_event = {
            "object": {
                "metadata": {
                    "labels": {
                        LABEL_MANAGED_BY: "ansible-operator",
                        LABEL_OWNER_UID: "schedule-uid-123",
                        LABEL_OWNER_NAME: "test-namespace.test-schedule",
                    }
                },
                "status": {
                    "lastScheduleTime": "2024-01-01T12:00:00Z",
                    "nextScheduleTime": "2024-01-01T13:00:00Z",
                },
            }
        }

        # Call the handler
        handle_cronjob_event(cronjob_event)

        # Verify API call
        mock_api.patch_namespaced_custom_object_status.assert_called_once()
        call_args = mock_api.patch_namespaced_custom_object_status.call_args

        assert call_args[1]["group"] == API_GROUP
        assert call_args[1]["version"] == "v1alpha1"
        assert call_args[1]["namespace"] == "test-namespace"
        assert call_args[1]["plural"] == "schedules"
        assert call_args[1]["name"] == "test-schedule"

        # Verify status fields
        patch_body = call_args[1]["body"]
        assert patch_body["status"]["lastRunTime"] == "2024-01-01T12:00:00Z"
        assert patch_body["status"]["nextRunTime"] == "2024-01-01T13:00:00Z"

    @patch("ansible_operator.main.client.CustomObjectsApi")
    def test_handle_cronjob_event_ignores_non_managed_cronjobs(self, mock_api_class: Mock) -> None:
        """Test that non-managed CronJobs are ignored."""
        mock_api = Mock()
        mock_api_class.return_value = mock_api

        # Mock CronJob event without ansible-operator label
        cronjob_event = {
            "object": {
                "metadata": {
                    "labels": {
                        LABEL_MANAGED_BY: "other-operator",
                        LABEL_OWNER_UID: "schedule-uid-123",
                        LABEL_OWNER_NAME: "test-namespace.test-schedule",
                    }
                },
                "status": {
                    "lastScheduleTime": "2024-01-01T12:00:00Z",
                },
            }
        }

        # Call the handler
        handle_cronjob_event(cronjob_event)

        # Verify no API call was made
        mock_api.patch_namespaced_custom_object_status.assert_not_called()

    @patch("ansible_operator.main.client.CustomObjectsApi")
    def test_handle_cronjob_event_handles_missing_labels(self, mock_api_class: Mock) -> None:
        """Test that CronJobs without required labels are ignored."""
        mock_api = Mock()
        mock_api_class.return_value = mock_api

        # Mock CronJob event without owner labels
        cronjob_event = {
            "object": {
                "metadata": {
                    "labels": {
                        LABEL_MANAGED_BY: "ansible-operator",
                    }
                },
                "status": {
                    "lastScheduleTime": "2024-01-01T12:00:00Z",
                },
            }
        }

        # Call the handler
        handle_cronjob_event(cronjob_event)

        # Verify no API call was made
        mock_api.patch_namespaced_custom_object_status.assert_not_called()

    @patch("ansible_operator.main.client.CustomObjectsApi")
    def test_handle_schedule_job_event_updates_status_fields(self, mock_api_class: Mock) -> None:
        """Test that Job events update Schedule status fields."""
        mock_api = Mock()
        mock_api_class.return_value = mock_api

        # Mock Job event
        job_event = {
            "object": {
                "metadata": {
                    "name": "test-schedule-1234567890",
                    "creationTimestamp": "2024-01-01T12:00:00Z",
                    "labels": {
                        LABEL_MANAGED_BY: "ansible-operator",
                        LABEL_OWNER_UID: "schedule-uid-123",
                        LABEL_OWNER_NAME: "test-namespace.test-schedule",
                    },
                    "annotations": {
                        "ansible.cloud37.dev/revision": "abc123def456",
                    },
                },
                "status": {
                    "succeeded": 1,
                },
            }
        }

        # Call the handler
        handle_schedule_job_event(job_event)

        # Verify API call
        mock_api.patch_namespaced_custom_object_status.assert_called_once()
        call_args = mock_api.patch_namespaced_custom_object_status.call_args

        assert call_args[1]["group"] == API_GROUP
        assert call_args[1]["version"] == "v1alpha1"
        assert call_args[1]["namespace"] == "test-namespace"
        assert call_args[1]["plural"] == "schedules"
        assert call_args[1]["name"] == "test-schedule"

        # Verify status fields
        patch_body = call_args[1]["body"]
        assert patch_body["status"]["lastJobRef"] == "test-namespace/test-schedule-1234567890"
        assert patch_body["status"]["lastRunTime"] == "2024-01-01T12:00:00Z"
        assert patch_body["status"]["lastRunRevision"] == "abc123def456"

    @patch("ansible_operator.main.client.CustomObjectsApi")
    def test_handle_schedule_job_event_ignores_connectivity_probe_jobs(
        self, mock_api_class: Mock
    ) -> None:
        """Test that connectivity probe Jobs are ignored."""
        mock_api = Mock()
        mock_api_class.return_value = mock_api

        # Mock Job event for connectivity probe
        job_event = {
            "object": {
                "metadata": {
                    "name": "test-repo-probe",
                    "labels": {
                        LABEL_MANAGED_BY: "ansible-operator",
                        "ansible.cloud37.dev/probe-type": "connectivity",
                        LABEL_OWNER_UID: "schedule-uid-123",
                        LABEL_OWNER_NAME: "test-namespace.test-schedule",
                    },
                }
            }
        }

        # Call the handler
        handle_schedule_job_event(job_event)

        # Verify no API call was made
        mock_api.patch_namespaced_custom_object_status.assert_not_called()

    @patch("ansible_operator.main.client.CustomObjectsApi")
    def test_handle_schedule_job_event_ignores_non_managed_jobs(self, mock_api_class: Mock) -> None:
        """Test that non-managed Jobs are ignored."""
        mock_api = Mock()
        mock_api_class.return_value = mock_api

        # Mock Job event without ansible-operator label
        job_event = {
            "object": {
                "metadata": {
                    "name": "test-schedule-1234567890",
                    "labels": {
                        LABEL_MANAGED_BY: "other-operator",
                        LABEL_OWNER_UID: "schedule-uid-123",
                        LABEL_OWNER_NAME: "test-namespace.test-schedule",
                    },
                }
            }
        }

        # Call the handler
        handle_schedule_job_event(job_event)

        # Verify no API call was made
        mock_api.patch_namespaced_custom_object_status.assert_not_called()

    @patch("ansible_operator.main.client.CustomObjectsApi")
    def test_handle_schedule_job_event_handles_missing_revision(self, mock_api_class: Mock) -> None:
        """Test that Jobs without revision annotation are handled gracefully."""
        mock_api = Mock()
        mock_api_class.return_value = mock_api

        # Mock Job event without revision annotation
        job_event = {
            "object": {
                "metadata": {
                    "name": "test-schedule-1234567890",
                    "creationTimestamp": "2024-01-01T12:00:00Z",
                    "labels": {
                        LABEL_MANAGED_BY: "ansible-operator",
                        LABEL_OWNER_UID: "schedule-uid-123",
                        LABEL_OWNER_NAME: "test-namespace.test-schedule",
                    },
                    "annotations": {},
                }
            }
        }

        # Call the handler
        handle_schedule_job_event(job_event)

        # Verify API call
        mock_api.patch_namespaced_custom_object_status.assert_called_once()
        call_args = mock_api.patch_namespaced_custom_object_status.call_args

        # Verify status fields (revision should be missing)
        patch_body = call_args[1]["body"]
        assert patch_body["status"]["lastJobRef"] == "test-namespace/test-schedule-1234567890"
        assert patch_body["status"]["lastRunTime"] == "2024-01-01T12:00:00Z"
        assert "lastRunRevision" not in patch_body["status"]

    @patch("ansible_operator.main.client.CustomObjectsApi")
    def test_handle_cronjob_event_handles_api_exception(self, mock_api_class: Mock) -> None:
        """Test that API exceptions are handled gracefully."""
        mock_api = Mock()
        mock_api_class.return_value = mock_api
        mock_api.patch_namespaced_custom_object_status.side_effect = Exception("API Error")

        # Mock CronJob event
        cronjob_event = {
            "object": {
                "metadata": {
                    "labels": {
                        LABEL_MANAGED_BY: "ansible-operator",
                        LABEL_OWNER_UID: "schedule-uid-123",
                        LABEL_OWNER_NAME: "test-namespace.test-schedule",
                    }
                },
                "status": {
                    "lastScheduleTime": "2024-01-01T12:00:00Z",
                },
            }
        }

        # Call the handler - should not raise exception
        handle_cronjob_event(cronjob_event)

        # Verify API call was attempted
        mock_api.patch_namespaced_custom_object_status.assert_called_once()

    @patch("ansible_operator.main.client.CustomObjectsApi")
    def test_handle_schedule_job_event_handles_api_exception(self, mock_api_class: Mock) -> None:
        """Test that API exceptions are handled gracefully."""
        mock_api = Mock()
        mock_api_class.return_value = mock_api
        mock_api.patch_namespaced_custom_object_status.side_effect = Exception("API Error")

        # Mock Job event
        job_event = {
            "object": {
                "metadata": {
                    "name": "test-schedule-1234567890",
                    "creationTimestamp": "2024-01-01T12:00:00Z",
                    "labels": {
                        LABEL_MANAGED_BY: "ansible-operator",
                        LABEL_OWNER_UID: "schedule-uid-123",
                        LABEL_OWNER_NAME: "test-namespace.test-schedule",
                    },
                }
            }
        }

        # Call the handler - should not raise exception
        handle_schedule_job_event(job_event)

        # Verify API call was attempted
        mock_api.patch_namespaced_custom_object_status.assert_called_once()
