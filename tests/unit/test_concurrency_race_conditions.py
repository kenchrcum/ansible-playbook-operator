"""Unit tests for concurrency and race condition scenarios.

Tests overlapping schedules with Forbid/Replace policies, many schedules using random macros,
and operator restarts (on.resume) scenarios.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest
from kubernetes import client

from ansible_operator.constants import COND_BLOCKED_BY_CONCURRENCY, COND_READY
from ansible_operator.main import (
    _check_concurrent_jobs,
    _update_schedule_conditions,
    reconcile_schedule,
)
from ansible_operator.utils.schedule import compute_computed_schedule


class TestConcurrencyRaceConditions:
    """Test concurrency and race condition scenarios."""

    def test_concurrent_schedule_reconciliation_forbid_policy(self):
        """Test concurrent schedule reconciliation with Forbid policy."""
        # Simulate multiple schedules trying to reconcile simultaneously
        namespace = "test-ns"
        schedule_names = [f"schedule-{i}" for i in range(5)]
        uids = [f"uid-{i}" for i in range(5)]

        # Mock concurrent job check to return different results
        def mock_check_concurrent_jobs(ns: str, name: str, uid: str) -> tuple[bool, str]:
            # Simulate some schedules having concurrent jobs
            if "schedule-1" in name or "schedule-3" in name:
                return True, f"Active Jobs: job-{name}"
            return False, ""

        with patch(
            "ansible_operator.main._check_concurrent_jobs", side_effect=mock_check_concurrent_jobs
        ):
            with patch("ansible_operator.main._emit_event") as mock_emit:
                results = []

                def reconcile_single_schedule(name: str, uid: str):
                    patch_status: dict[str, Any] = {}
                    spec = {"concurrencyPolicy": "Forbid"}
                    _update_schedule_conditions(
                        patch_status, namespace, name, uid, spec, True, True
                    )
                    return name, patch_status

                # Run reconciliations concurrently
                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = [
                        executor.submit(reconcile_single_schedule, name, uid)
                        for name, uid in zip(schedule_names, uids)
                    ]

                    for future in as_completed(futures):
                        name, patch_status = future.result()
                        results.append((name, patch_status))

                # Verify all schedules were processed
                assert len(results) == 5

                # Check that schedules with concurrent jobs are blocked
                for name, patch_status in results:
                    conditions = patch_status["conditions"]
                    ready_condition = next(c for c in conditions if c["type"] == COND_READY)

                    if "schedule-1" in name or "schedule-3" in name:
                        assert ready_condition["status"] == "False"
                        assert ready_condition["reason"] == "BlockedByConcurrency"
                    else:
                        assert ready_condition["status"] == "True"
                        assert ready_condition["reason"] == "Ready"

    def test_concurrent_schedule_reconciliation_replace_policy(self):
        """Test concurrent schedule reconciliation with Replace policy."""
        namespace = "test-ns"
        schedule_names = [f"schedule-{i}" for i in range(3)]
        uids = [f"uid-{i}" for i in range(3)]

        # Mock concurrent job check to return concurrent jobs for all
        def mock_check_concurrent_jobs(ns: str, name: str, uid: str) -> tuple[bool, str]:
            return True, f"Active Jobs: job-{name}"

        with patch(
            "ansible_operator.main._check_concurrent_jobs", side_effect=mock_check_concurrent_jobs
        ):
            results = []

            def reconcile_single_schedule(name: str, uid: str):
                patch_status: dict[str, Any] = {}
                spec = {"concurrencyPolicy": "Replace"}
                _update_schedule_conditions(patch_status, namespace, name, uid, spec, True, True)
                return name, patch_status

            # Run reconciliations concurrently
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = [
                    executor.submit(reconcile_single_schedule, name, uid)
                    for name, uid in zip(schedule_names, uids)
                ]

                for future in as_completed(futures):
                    name, patch_status = future.result()
                    results.append((name, patch_status))

            # Verify all schedules are ready despite concurrent jobs (Replace policy)
            for name, patch_status in results:
                conditions = patch_status["conditions"]
                ready_condition = next(c for c in conditions if c["type"] == COND_READY)
                assert ready_condition["status"] == "True"
                assert ready_condition["reason"] == "Ready"

                # But BlockedByConcurrency should still reflect concurrent state
                blocked_condition = next(
                    c for c in conditions if c["type"] == COND_BLOCKED_BY_CONCURRENCY
                )
                assert blocked_condition["status"] == "True"
                assert blocked_condition["reason"] == "ConcurrentJobsRunning"

    def test_many_schedules_random_macros_deterministic(self):
        """Test many schedules using random macros maintain deterministic behavior."""
        # Create many schedules with random macros
        schedules = []
        for i in range(100):
            uid = f"schedule-{i:03d}-uid"
            schedules.append(uid)

        # Test all random macro types
        macro_types = [
            "@hourly-random",
            "@daily-random",
            "@weekly-random",
            "@monthly-random",
            "@yearly-random",
        ]

        results = {}

        for macro in macro_types:
            macro_results = []
            for uid in schedules:
                computed, used_macro = compute_computed_schedule(macro, uid)
                macro_results.append((uid, computed, used_macro))

            # Verify all results are deterministic (same input = same output)
            for uid in schedules:
                computed1, used1 = compute_computed_schedule(macro, uid)
                computed2, used2 = compute_computed_schedule(macro, uid)
                assert computed1 == computed2
                assert used1 == used2
                assert used1 is True

            results[macro] = macro_results

        # Verify no collisions in computed schedules for different UIDs
        for macro, macro_results in results.items():
            computed_schedules = [result[1] for result in macro_results]
            # For hourly-random, we expect some collisions since there are only 60 possible minutes
            # For other macros, we expect unique schedules
            if macro == "@hourly-random":
                # Should have reasonable distribution (not all the same)
                unique_count = len(set(computed_schedules))
                assert unique_count > 10  # At least 10 different minutes
                assert unique_count <= 60  # At most 60 different minutes
            else:
                # Should have unique schedules (no collisions) - allow for occasional collisions due to hash distribution
                unique_count = len(set(computed_schedules))
                # Should have very few collisions (at least 95% unique)
                assert unique_count >= len(computed_schedules) * 0.95

        # Verify macro-specific constraints
        for macro, macro_results in results.items():
            for uid, computed, used in macro_results:
                parts = computed.split()

                if macro == "@hourly-random":
                    # minute * * * *
                    assert len(parts) == 5
                    assert 0 <= int(parts[0]) <= 59
                    assert parts[1] == "*"
                elif macro == "@daily-random":
                    # minute hour * * *
                    assert len(parts) == 5
                    assert 0 <= int(parts[0]) <= 59
                    assert 0 <= int(parts[1]) <= 23
                    assert parts[2] == "*"
                elif macro == "@weekly-random":
                    # minute hour * * day_of_week
                    assert len(parts) == 5
                    assert 0 <= int(parts[0]) <= 59
                    assert 0 <= int(parts[1]) <= 23
                    assert parts[2] == "*"
                    assert 0 <= int(parts[4]) <= 6
                elif macro == "@monthly-random":
                    # minute hour day_of_month * *
                    assert len(parts) == 5
                    assert 0 <= int(parts[0]) <= 59
                    assert 0 <= int(parts[1]) <= 23
                    assert 1 <= int(parts[2]) <= 28
                    assert parts[3] == "*"
                elif macro == "@yearly-random":
                    # minute hour day_of_month month *
                    assert len(parts) == 5
                    assert 0 <= int(parts[0]) <= 59
                    assert 0 <= int(parts[1]) <= 23
                    assert 1 <= int(parts[2]) <= 28
                    assert 1 <= int(parts[3]) <= 12

    def test_random_macro_concurrent_computation(self):
        """Test random macro computation under concurrent access."""
        uid = "test-uid-123"
        macro = "@daily-random"

        # Test concurrent computation of the same macro/UID
        results = []

        def compute_macro():
            computed, used = compute_computed_schedule(macro, uid)
            return computed, used

        # Run many concurrent computations
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(compute_macro) for _ in range(100)]

            for future in as_completed(futures):
                computed, used = future.result()
                results.append((computed, used))

        # All results should be identical (deterministic)
        assert len(results) == 100
        first_result = results[0]
        for computed, used in results:
            assert computed == first_result[0]
            assert used == first_result[1]
            assert used is True

    def test_operator_restart_dependency_rebuild(self):
        """Test operator restart and dependency index rebuilding."""
        # Mock the dependency service
        mock_dependency_service = Mock()

        with patch("ansible_operator.main.dependency_service", mock_dependency_service):
            with patch("ansible_operator.main.client.CustomObjectsApi") as mock_api:
                with patch("ansible_operator.main.client.CoreV1Api") as mock_v1:
                    # Mock namespace listing
                    mock_ns_list = Mock()
                    mock_namespaces = []
                    for i in range(3):
                        mock_ns = Mock()
                        mock_ns.metadata.name = f"ns-{i}"
                        mock_namespaces.append(mock_ns)
                    mock_ns_list.items = mock_namespaces
                    mock_v1.return_value.list_namespace.return_value = mock_ns_list

                    # Mock environment variables
                    with patch.dict("os.environ", {"WATCH_SCOPE": "all"}):
                        # Import and call the startup function
                        from ansible_operator.main import rebuild_dependency_indices

                        rebuild_dependency_indices()

                    # Verify dependency service was called
                    mock_dependency_service.rebuild_all_indices.assert_called_once()
                    call_args = mock_dependency_service.rebuild_all_indices.call_args[0][0]
                    assert len(call_args) == 3
                    # Verify dependency service was called with list of namespace strings
                    assert isinstance(call_args, list)
                    assert len(call_args) == 3
                    assert "ns-0" in call_args
                    assert "ns-1" in call_args
                    assert "ns-2" in call_args

    def test_operator_restart_schedule_reconciliation(self):
        """Test schedule reconciliation after operator restart."""
        # Mock the reconcile_schedule function components
        with patch("ansible_operator.main.client.CustomObjectsApi") as mock_custom_api:
            with patch("ansible_operator.main.client.BatchV1Api") as mock_batch_api:
                with patch("ansible_operator.main.build_cronjob") as mock_build_cronjob:
                    with patch(
                        "ansible_operator.main._get_executor_service_account"
                    ) as mock_get_sa:
                        # Mock playbook and repository objects
                        mock_playbook = {
                            "spec": {
                                "repositoryRef": {"name": "test-repo"},
                                "playbookPath": "test.yml",
                            },
                            "status": {"conditions": [{"type": "Ready", "status": "True"}]},
                        }

                        mock_repository = {
                            "spec": {"url": "https://example.com/repo.git"},
                            "status": {"conditions": [{"type": "Ready", "status": "True"}]},
                        }

                        # Mock API responses
                        mock_custom_api.return_value.get_namespaced_custom_object.side_effect = [
                            mock_playbook,  # Playbook lookup
                            mock_repository,  # Repository lookup
                        ]

                        # Mock CronJob creation
                        mock_cronjob_manifest = {
                            "metadata": {"name": "test-schedule-cronjob"},
                            "spec": {"schedule": "0 0 * * *"},
                        }
                        mock_build_cronjob.return_value = mock_cronjob_manifest

                        # Mock successful CronJob creation
                        mock_batch_api.return_value.create_namespaced_cron_job.return_value = Mock()

                        # Mock service account
                        mock_get_sa.return_value = "test-sa"

                        # Test schedule reconciliation
                        spec = {
                            "playbookRef": {"name": "test-playbook"},
                            "schedule": "@daily-random",
                        }
                        status: dict[str, Any] = {}
                        patch_obj = Mock()
                        patch_obj.status = status
                        meta = Mock()
                        meta.get.return_value = {}

                        # Call reconcile_schedule
                        reconcile_schedule(
                            spec=spec,
                            status=status,
                            patch=patch_obj,
                            meta=meta,
                            name="test-schedule",
                            namespace="test-ns",
                            uid="test-uid",
                        )

                        # Verify CronJob was built and created
                        mock_build_cronjob.assert_called_once()
                        mock_batch_api.return_value.create_namespaced_cron_job.assert_called_once()

                        # Verify computed schedule was set
                        assert "computedSchedule" in status
                        computed_schedule = status["computedSchedule"]
                        assert computed_schedule != "@daily-random"  # Should be expanded
                        assert " " in computed_schedule  # Should be cron format

    def test_concurrent_job_check_race_condition(self):
        """Test _check_concurrent_jobs for race conditions."""
        namespace = "test-ns"
        schedule_name = "test-schedule"
        owner_uid = "test-uid"

        # Mock job list that changes between calls (simulating race condition)
        job_states = [
            [],  # First call: no jobs
            [
                Mock(
                    metadata=Mock(name="job-1"), status=Mock(active=1, succeeded=None, failed=None)
                )
            ],  # Second call: active job
            [],  # Third call: job completed
        ]

        call_count = 0

        def mock_list_jobs(*args, **kwargs):
            nonlocal call_count
            if call_count < len(job_states):
                jobs = job_states[call_count]
                call_count += 1
            else:
                jobs = []

            mock_job_list = Mock()
            mock_job_list.items = jobs
            return mock_job_list

        with patch("ansible_operator.main.client.BatchV1Api") as mock_batch_api:
            mock_api_instance = Mock()
            mock_batch_api.return_value = mock_api_instance
            mock_api_instance.list_namespaced_job.side_effect = mock_list_jobs

            # Test multiple concurrent calls
            results = []

            def check_jobs():
                has_concurrent, reason = _check_concurrent_jobs(namespace, schedule_name, owner_uid)
                return has_concurrent, reason

            # Run concurrent checks
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = [executor.submit(check_jobs) for _ in range(3)]

                for future in as_completed(futures):
                    result = future.result()
                    results.append(result)

            # Verify results (may vary due to race conditions)
            assert len(results) == 3
            # At least one should detect no concurrent jobs initially
            no_concurrent_found = any(not result[0] for result in results)
            assert no_concurrent_found

    def test_schedule_condition_update_race_condition(self):
        """Test schedule condition updates under race conditions."""
        namespace = "test-ns"
        schedule_name = "test-schedule"
        uid = "test-uid"
        spec = {"concurrencyPolicy": "Forbid"}

        # Mock concurrent job check to return different results
        concurrent_results = [
            (False, ""),  # No concurrent jobs
            (True, "Active Jobs: job-1"),  # Concurrent jobs
            (False, ""),  # Jobs completed
        ]

        call_count = 0

        def mock_check_concurrent_jobs(ns: str, name: str, owner_uid: str) -> tuple[bool, str]:
            nonlocal call_count
            if call_count < len(concurrent_results):
                result = concurrent_results[call_count]
                call_count += 1
                return result
            return False, ""

        with patch(
            "ansible_operator.main._check_concurrent_jobs", side_effect=mock_check_concurrent_jobs
        ):
            with patch("ansible_operator.main._emit_event") as mock_emit:
                results = []

                def update_conditions():
                    patch_status: dict[str, Any] = {}
                    _update_schedule_conditions(
                        patch_status, namespace, schedule_name, uid, spec, True, True
                    )
                    return patch_status

                # Run concurrent condition updates
                with ThreadPoolExecutor(max_workers=3) as executor:
                    futures = [executor.submit(update_conditions) for _ in range(3)]

                    for future in as_completed(futures):
                        patch_status = future.result()
                        results.append(patch_status)

                # Verify all updates completed
                assert len(results) == 3

                # Check that conditions were set appropriately
                for patch_status in results:
                    assert "conditions" in patch_status
                    conditions = patch_status["conditions"]

                    # Should have both Ready and BlockedByConcurrency conditions
                    condition_types = [c["type"] for c in conditions]
                    assert COND_READY in condition_types
                    assert COND_BLOCKED_BY_CONCURRENCY in condition_types

    def test_mixed_concurrency_policies_concurrent_reconciliation(self):
        """Test concurrent reconciliation of schedules with mixed concurrency policies."""
        namespace = "test-ns"
        schedules = [
            ("schedule-forbid", "uid-1", "Forbid"),
            ("schedule-allow", "uid-2", "Allow"),
            ("schedule-replace", "uid-3", "Replace"),
        ]

        # Mock concurrent job check to return concurrent jobs for all
        def mock_check_concurrent_jobs(ns: str, name: str, uid: str) -> tuple[bool, str]:
            return True, f"Active Jobs: job-{name}"

        with patch(
            "ansible_operator.main._check_concurrent_jobs", side_effect=mock_check_concurrent_jobs
        ):
            results = []

            def reconcile_schedule(name: str, uid: str, policy: str):
                patch_status: dict[str, Any] = {}
                spec = {"concurrencyPolicy": policy}
                _update_schedule_conditions(patch_status, namespace, name, uid, spec, True, True)
                return name, patch_status

            # Run reconciliations concurrently
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = [
                    executor.submit(reconcile_schedule, name, uid, policy)
                    for name, uid, policy in schedules
                ]

                for future in as_completed(futures):
                    name, patch_status = future.result()
                    results.append((name, patch_status))

            # Verify policy-specific behavior
            for name, patch_status in results:
                conditions = patch_status["conditions"]
                ready_condition = next(c for c in conditions if c["type"] == COND_READY)
                blocked_condition = next(
                    c for c in conditions if c["type"] == COND_BLOCKED_BY_CONCURRENCY
                )

                if "forbid" in name:
                    # Forbid policy should block Ready condition
                    assert ready_condition["status"] == "False"
                    assert ready_condition["reason"] == "BlockedByConcurrency"
                else:
                    # Allow and Replace policies should not block Ready condition
                    assert ready_condition["status"] == "True"
                    assert ready_condition["reason"] == "Ready"

                # All should show concurrent jobs in BlockedByConcurrency condition
                assert blocked_condition["status"] == "True"
                assert blocked_condition["reason"] == "ConcurrentJobsRunning"
