"""Unit tests for metrics functionality."""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from kubernetes import client

from ansible_operator import metrics
from ansible_operator.main import (
    handle_job_completion,
    handle_manual_run_job_completion,
    handle_schedule_job_event,
    reconcile_playbook,
    reconcile_repository,
    reconcile_schedule,
)


class MockPatch:
    """Mock Kopf patch object."""

    def __init__(self):
        self.status = {}
        self.meta = MagicMock()


class TestMetrics:
    """Test metrics collection and exposure."""

    def test_metrics_definitions(self):
        """Test that all required metrics are defined."""
        # Test that metrics are properly defined
        assert hasattr(metrics, "RECONCILE_TOTAL")
        assert hasattr(metrics, "RECONCILE_DURATION")
        assert hasattr(metrics, "WORKQUEUE_DEPTH")
        assert hasattr(metrics, "JOB_RUNS_TOTAL")
        assert hasattr(metrics, "JOB_RUN_DURATION")

        # Test metric types
        assert metrics.RECONCILE_TOTAL._type == "counter"
        assert metrics.RECONCILE_DURATION._type == "histogram"
        assert metrics.WORKQUEUE_DEPTH._type == "gauge"
        assert metrics.JOB_RUNS_TOTAL._type == "counter"
        assert metrics.JOB_RUN_DURATION._type == "histogram"

    def test_reconcile_metrics_repository_success(self):
        """Test that Repository reconciliation metrics are recorded on success."""
        spec: dict[str, Any] = {
            "url": "https://github.com/test/repo.git",
            "auth": {"type": "none"},
        }
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Create meta mock that returns None for deletionTimestamp
        meta_mock = MagicMock()
        meta_mock.get.side_effect = lambda key, default=None: (
            None if key == "deletionTimestamp" else MagicMock()
        )

        # Mock external dependencies
        with (
            patch("ansible_operator.main.client.CustomObjectsApi") as mock_api_class,
            patch("ansible_operator.main.client.BatchV1Api") as mock_batch_api_class,
            patch("ansible_operator.main._emit_event") as mock_emit,
        ):
            mock_api = MagicMock()
            mock_api_class.return_value = mock_api
            mock_batch_api = MagicMock()
            mock_batch_api_class.return_value = mock_batch_api

            # Mock successful repository creation
            mock_api.create_namespaced_custom_object.return_value = {
                "metadata": {"name": "test-repo"}
            }

            # Reset metrics before test
            metrics.RECONCILE_TOTAL.clear()
            metrics.RECONCILE_DURATION.clear()

            reconcile_repository(
                spec=spec,
                status=status,
                patch=mock_patch,
                name="test-repo",
                namespace="default",
                uid="uid-123",
                meta=meta_mock,
            )

        # Check that metrics were recorded
        reconcile_total_samples = metrics.RECONCILE_TOTAL.collect()[0].samples
        reconcile_duration_samples = metrics.RECONCILE_DURATION.collect()[0].samples

        # Find the samples for Repository kind
        started_sample = next(
            s
            for s in reconcile_total_samples
            if s.labels["kind"] == "Repository" and s.labels["result"] == "started"
        )
        success_sample = next(
            s
            for s in reconcile_total_samples
            if s.labels["kind"] == "Repository" and s.labels["result"] == "success"
        )
        duration_sample = next(
            s for s in reconcile_duration_samples if s.labels["kind"] == "Repository"
        )

        assert started_sample.value == 1.0
        assert success_sample.value == 1.0
        assert duration_sample.value > 0

    def test_reconcile_metrics_playbook_started(self):
        """Test that Playbook reconciliation metrics are recorded when started."""
        spec: dict[str, Any] = {
            "repositoryRef": {"name": "test-repo", "namespace": "default"},
            "playbookPath": "playbook.yml",
        }
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Create meta mock that returns None for deletionTimestamp
        meta_mock = MagicMock()
        meta_mock.get.side_effect = lambda key, default=None: (
            None if key == "deletionTimestamp" else MagicMock()
        )

        # Mock external dependencies
        with (
            patch("ansible_operator.main.client.CustomObjectsApi") as mock_api_class,
            patch("ansible_operator.main._emit_event") as mock_emit,
            patch("ansible_operator.services.git.GitService") as mock_git_service_class,
            patch(
                "ansible_operator.services.dependencies.DependencyService"
            ) as mock_dependency_service_class,
        ):
            mock_api = MagicMock()
            mock_api_class.return_value = mock_api
            mock_git_service = MagicMock()
            mock_git_service_class.return_value = mock_git_service
            mock_dependency_service = MagicMock()
            mock_dependency_service_class.return_value = mock_dependency_service

            # Mock successful repository lookup
            mock_api.get_namespaced_custom_object.return_value = {
                "status": {"conditions": [{"type": "Ready", "status": "True"}]}
            }

            # Mock successful repository readiness check
            mock_git_service.check_repository_readiness.return_value = (True, None)

            # Mock dependency service methods
            mock_dependency_service.index_playbook_dependencies.return_value = None
            mock_dependency_service.requeue_dependent_schedules.return_value = None

            # Reset metrics before test
            metrics.RECONCILE_TOTAL.clear()
            metrics.RECONCILE_DURATION.clear()

            reconcile_playbook(
                spec=spec,
                status=status,
                patch=mock_patch,
                name="test-playbook",
                namespace="default",
                uid="uid-123",
                meta=meta_mock,
            )

        # Check that started metrics were recorded
        reconcile_total_samples = metrics.RECONCILE_TOTAL.collect()[0].samples

        # Find the samples for Playbook kind
        started_sample = next(
            s
            for s in reconcile_total_samples
            if s.labels["kind"] == "Playbook" and s.labels["result"] == "started"
        )

        assert started_sample.value == 1.0

    def test_reconcile_metrics_schedule_success(self):
        """Test that Schedule reconciliation metrics are recorded on success."""
        spec: dict[str, Any] = {
            "playbookRef": {"name": "test-playbook", "namespace": "default"},
            "schedule": "0 0 * * *",
        }
        status: dict[str, Any] = {}
        mock_patch = MockPatch()

        # Mock external dependencies
        with (
            patch("ansible_operator.main.client.CustomObjectsApi") as mock_api_class,
            patch("ansible_operator.main.client.BatchV1Api") as mock_batch_api_class,
            patch("ansible_operator.main._emit_event") as mock_emit,
        ):
            mock_api = MagicMock()
            mock_api_class.return_value = mock_api
            mock_batch_api = MagicMock()
            mock_batch_api_class.return_value = mock_batch_api

            # Mock successful playbook lookup
            mock_api.get_namespaced_custom_object.return_value = {
                "status": {"conditions": [{"type": "Ready", "status": "True"}]}
            }

            # Mock successful CronJob creation
            mock_batch_api.create_namespaced_cron_job.return_value = {
                "metadata": {"name": "test-cronjob"}
            }

            # Reset metrics before test
            metrics.RECONCILE_TOTAL.clear()
            metrics.RECONCILE_DURATION.clear()

            meta = MagicMock()
            meta.get.return_value = {}

            reconcile_schedule(
                spec=spec,
                status=status,
                patch=mock_patch,
                meta=meta,
                name="test-schedule",
                namespace="default",
                uid="uid-123",
            )

        # Check that metrics were recorded
        reconcile_total_samples = metrics.RECONCILE_TOTAL.collect()[0].samples
        reconcile_duration_samples = metrics.RECONCILE_DURATION.collect()[0].samples

        # Find the samples for Schedule kind
        started_sample = next(
            s
            for s in reconcile_total_samples
            if s.labels["kind"] == "Schedule" and s.labels["result"] == "started"
        )
        success_sample = next(
            s
            for s in reconcile_total_samples
            if s.labels["kind"] == "Schedule" and s.labels["result"] == "success"
        )
        duration_sample = next(
            s for s in reconcile_duration_samples if s.labels["kind"] == "Schedule"
        )

        assert started_sample.value == 1.0
        assert success_sample.value == 1.0
        assert duration_sample.value > 0

    def test_job_completion_metrics_repository_success(self):
        """Test that Repository job completion metrics are recorded on success."""
        # Reset metrics before test
        metrics.JOB_RUNS_TOTAL.clear()
        metrics.JOB_RUN_DURATION.clear()

        # Mock successful job completion event
        job_event = {
            "object": {
                "metadata": {
                    "name": "test-repo-probe",
                    "namespace": "default",
                    "ownerReferences": [
                        {
                            "kind": "Repository",
                            "apiVersion": "ansible.cloud37.dev/v1alpha1",
                            "uid": "repo-uid",
                        }
                    ],
                    "labels": {"ansible.cloud37.dev/probe-type": "connectivity"},
                },
                "status": {
                    "succeeded": 1,
                    "startTime": "2024-01-01T12:00:00Z",
                    "completionTime": "2024-01-01T12:01:00Z",
                },
            }
        }

        with patch("ansible_operator.main.client.CustomObjectsApi") as mock_api_class:
            mock_api = MagicMock()
            mock_api_class.return_value = mock_api

            # Mock repository exists
            mock_api.get_namespaced_custom_object.return_value = {"metadata": {"name": "test-repo"}}

            handle_job_completion(job_event)

        # Check that metrics were recorded
        job_runs_samples = metrics.JOB_RUNS_TOTAL.collect()[0].samples
        job_duration_samples = metrics.JOB_RUN_DURATION.collect()[0].samples

        # Find the samples for Repository kind
        success_sample = next(
            s
            for s in job_runs_samples
            if s.labels["kind"] == "Repository" and s.labels["result"] == "success"
        )

        # Check histogram buckets for duration (60 seconds should fall in the 60+ bucket)
        duration_samples = [s for s in job_duration_samples if s.labels["kind"] == "Repository"]
        duration_count_sample = next(s for s in duration_samples if s.name.endswith("_count"))
        duration_sum_sample = next(s for s in duration_samples if s.name.endswith("_sum"))

        assert success_sample.value == 1.0
        assert duration_count_sample.value == 1.0
        assert duration_sum_sample.value == 60.0  # 1 minute duration

    def test_job_completion_metrics_repository_failure(self):
        """Test that Repository job completion metrics are recorded on failure."""
        # Reset metrics before test
        metrics.JOB_RUNS_TOTAL.clear()
        metrics.JOB_RUN_DURATION.clear()

        # Mock failed job completion event
        job_event = {
            "object": {
                "metadata": {
                    "name": "test-repo-probe",
                    "namespace": "default",
                    "ownerReferences": [
                        {
                            "kind": "Repository",
                            "apiVersion": "ansible.cloud37.dev/v1alpha1",
                            "uid": "repo-uid",
                        }
                    ],
                    "labels": {"ansible.cloud37.dev/probe-type": "connectivity"},
                },
                "status": {
                    "failed": 1,
                    "startTime": "2024-01-01T12:00:00Z",
                    "completionTime": "2024-01-01T12:00:30Z",
                },
            }
        }

        with patch("ansible_operator.main.client.CustomObjectsApi") as mock_api_class:
            mock_api = MagicMock()
            mock_api_class.return_value = mock_api

            # Mock repository exists
            mock_api.get_namespaced_custom_object.return_value = {"metadata": {"name": "test-repo"}}

            handle_job_completion(job_event)

        # Check that metrics were recorded
        job_runs_samples = metrics.JOB_RUNS_TOTAL.collect()[0].samples
        job_duration_samples = metrics.JOB_RUN_DURATION.collect()[0].samples

        # Find the samples for Repository kind
        failure_sample = next(
            s
            for s in job_runs_samples
            if s.labels["kind"] == "Repository" and s.labels["result"] == "failure"
        )

        # Check histogram buckets for duration (30 seconds should fall in the 30+ bucket)
        duration_samples = [s for s in job_duration_samples if s.labels["kind"] == "Repository"]
        duration_count_sample = next(s for s in duration_samples if s.name.endswith("_count"))
        duration_sum_sample = next(s for s in duration_samples if s.name.endswith("_sum"))

        assert failure_sample.value == 1.0
        assert duration_count_sample.value == 1.0
        assert duration_sum_sample.value == 30.0  # 30 seconds duration

    def test_manual_run_job_completion_metrics(self):
        """Test that manual run job completion metrics are recorded."""
        # Reset metrics before test
        metrics.JOB_RUNS_TOTAL.clear()
        metrics.JOB_RUN_DURATION.clear()

        # Mock successful manual run job completion event
        job_event = {
            "object": {
                "metadata": {
                    "name": "manual-run-job",
                    "namespace": "default",
                    "labels": {
                        "ansible.cloud37.dev/run-type": "manual",
                        "ansible.cloud37.dev/run-id": "run-123",
                        "ansible.cloud37.dev/owner-uid": "playbook-uid",
                        "ansible.cloud37.dev/owner-name": "default.test-playbook",
                    },
                },
                "status": {
                    "succeeded": 1,
                    "startTime": "2024-01-01T12:00:00Z",
                    "completionTime": "2024-01-01T12:02:00Z",
                },
            }
        }

        with patch("ansible_operator.main.client.CustomObjectsApi") as mock_api_class:
            mock_api = MagicMock()
            mock_api_class.return_value = mock_api

            # Mock playbook exists
            mock_api.get_namespaced_custom_object.return_value = {
                "metadata": {"name": "test-playbook"}
            }

            handle_manual_run_job_completion(job_event)

        # Check that metrics were recorded
        job_runs_samples = metrics.JOB_RUNS_TOTAL.collect()[0].samples
        job_duration_samples = metrics.JOB_RUN_DURATION.collect()[0].samples

        # Find the samples for Playbook kind
        success_sample = next(
            s
            for s in job_runs_samples
            if s.labels["kind"] == "Playbook" and s.labels["result"] == "success"
        )

        # Check histogram buckets for duration (120 seconds should fall in the 120+ bucket)
        duration_samples = [s for s in job_duration_samples if s.labels["kind"] == "Playbook"]
        duration_count_sample = next(s for s in duration_samples if s.name.endswith("_count"))
        duration_sum_sample = next(s for s in duration_samples if s.name.endswith("_sum"))

        assert success_sample.value == 1.0
        assert duration_count_sample.value == 1.0
        assert duration_sum_sample.value == 120.0  # 2 minutes duration

    def test_schedule_job_event_metrics(self):
        """Test that Schedule job event metrics are recorded."""
        # Reset metrics before test
        metrics.JOB_RUNS_TOTAL.clear()
        metrics.JOB_RUN_DURATION.clear()

        # Mock successful schedule job event
        job_event = {
            "object": {
                "metadata": {
                    "name": "schedule-job",
                    "namespace": "default",
                    "labels": {
                        "ansible.cloud37.dev/managed-by": "ansible-operator",
                        "ansible.cloud37.dev/owner-uid": "schedule-uid",
                        "ansible.cloud37.dev/owner-name": "default.test-schedule",
                    },
                },
                "status": {
                    "succeeded": 1,
                    "startTime": "2024-01-01T12:00:00Z",
                    "completionTime": "2024-01-01T12:05:00Z",
                },
            }
        }

        with patch("ansible_operator.main.client.CustomObjectsApi") as mock_api_class:
            mock_api = MagicMock()
            mock_api_class.return_value = mock_api

            # Mock schedule exists
            mock_api.get_namespaced_custom_object.return_value = {
                "metadata": {"name": "test-schedule"},
                "spec": {"concurrencyPolicy": "Forbid"},
            }

            handle_schedule_job_event(job_event)

        # Check that metrics were recorded
        job_runs_samples = metrics.JOB_RUNS_TOTAL.collect()[0].samples
        job_duration_samples = metrics.JOB_RUN_DURATION.collect()[0].samples

        # Find the samples for Schedule kind
        success_sample = next(
            s
            for s in job_runs_samples
            if s.labels["kind"] == "Schedule" and s.labels["result"] == "success"
        )

        # Check histogram buckets for duration (300 seconds should fall in the 300+ bucket)
        duration_samples = [s for s in job_duration_samples if s.labels["kind"] == "Schedule"]
        duration_count_sample = next(s for s in duration_samples if s.name.endswith("_count"))
        duration_sum_sample = next(s for s in duration_samples if s.name.endswith("_sum"))

        assert success_sample.value == 1.0
        assert duration_count_sample.value == 1.0
        assert duration_sum_sample.value == 300.0  # 5 minutes duration

    def test_job_duration_parsing_error_handling(self):
        """Test that job duration parsing errors are handled gracefully."""
        # Reset metrics before test
        metrics.JOB_RUNS_TOTAL.clear()
        metrics.JOB_RUN_DURATION.clear()

        # Mock job completion event with invalid timestamps
        job_event = {
            "object": {
                "metadata": {
                    "name": "test-repo-probe",
                    "namespace": "default",
                    "ownerReferences": [
                        {
                            "kind": "Repository",
                            "apiVersion": "ansible.cloud37.dev/v1alpha1",
                            "uid": "repo-uid",
                        }
                    ],
                    "labels": {"ansible.cloud37.dev/probe-type": "connectivity"},
                },
                "status": {
                    "succeeded": 1,
                    "startTime": "invalid-timestamp",
                    "completionTime": "invalid-timestamp",
                },
            }
        }

        with patch("ansible_operator.main.client.CustomObjectsApi") as mock_api_class:
            mock_api = MagicMock()
            mock_api_class.return_value = mock_api

            # Mock repository exists
            mock_api.get_namespaced_custom_object.return_value = {"metadata": {"name": "test-repo"}}

            # Should not raise an exception
            handle_job_completion(job_event)

        # Check that job run metric was recorded but duration was not
        job_runs_samples = metrics.JOB_RUNS_TOTAL.collect()[0].samples
        job_duration_samples = metrics.JOB_RUN_DURATION.collect()[0].samples

        # Find the samples for Repository kind
        success_sample = next(
            s
            for s in job_runs_samples
            if s.labels["kind"] == "Repository" and s.labels["result"] == "success"
        )

        # Duration should not be recorded due to parsing error
        duration_samples = [s for s in job_duration_samples if s.labels["kind"] == "Repository"]

        assert success_sample.value == 1.0
        assert len(duration_samples) == 0

    def test_workqueue_depth_metric_available(self):
        """Test that workqueue depth metric is available for future use."""
        # The workqueue depth metric is defined but not yet implemented
        # This test ensures it's available for future implementation
        assert hasattr(metrics, "WORKQUEUE_DEPTH")
        assert metrics.WORKQUEUE_DEPTH._type == "gauge"

        # Test that we can set and get values
        metrics.WORKQUEUE_DEPTH.labels(kind="Repository").set(5)
        metrics.WORKQUEUE_DEPTH.labels(kind="Playbook").set(3)
        metrics.WORKQUEUE_DEPTH.labels(kind="Schedule").set(2)

        # Collect and verify
        samples = metrics.WORKQUEUE_DEPTH.collect()[0].samples
        repo_sample = next(s for s in samples if s.labels["kind"] == "Repository")
        playbook_sample = next(s for s in samples if s.labels["kind"] == "Playbook")
        schedule_sample = next(s for s in samples if s.labels["kind"] == "Schedule")

        assert repo_sample.value == 5.0
        assert playbook_sample.value == 3.0
        assert schedule_sample.value == 2.0
