"""Unit tests for executor ServiceAccount functionality."""

import os
from unittest.mock import patch

import pytest

from ansible_operator.builders.cronjob_builder import build_cronjob
from ansible_operator.builders.job_builder import (
    build_connectivity_probe_job,
    build_manual_run_job,
)
from ansible_operator.main import _get_executor_service_account


class TestExecutorServiceAccount:
    """Test executor ServiceAccount functionality."""

    def test_get_executor_service_account_from_env(self):
        """Test retrieving executor ServiceAccount from environment variable."""
        with patch.dict(os.environ, {"EXECUTOR_SERVICE_ACCOUNT": "test-executor-sa"}):
            result = _get_executor_service_account()
            assert result == "test-executor-sa"

    def test_get_executor_service_account_none_when_unset(self):
        """Test that None is returned when environment variable is not set."""
        with patch.dict(os.environ, {}, clear=True):
            result = _get_executor_service_account()
            assert result is None

    def test_connectivity_probe_job_with_executor_service_account(self):
        """Test connectivity probe job includes executor ServiceAccount when provided."""
        job_manifest = build_connectivity_probe_job(
            repository_name="test-repo",
            namespace="test-namespace",
            repository_spec={"url": "https://github.com/test/repo.git"},
            owner_uid="test-uid",
            executor_service_account="test-executor-sa",
        )

        assert job_manifest["spec"]["template"]["spec"]["serviceAccountName"] == "test-executor-sa"

    def test_connectivity_probe_job_without_executor_service_account(self):
        """Test connectivity probe job omits ServiceAccount when not provided."""
        job_manifest = build_connectivity_probe_job(
            repository_name="test-repo",
            namespace="test-namespace",
            repository_spec={"url": "https://github.com/test/repo.git"},
            owner_uid="test-uid",
            executor_service_account=None,
        )

        assert "serviceAccountName" not in job_manifest["spec"]["template"]["spec"]

    def test_manual_run_job_with_executor_service_account(self):
        """Test manual run job includes executor ServiceAccount when provided."""
        job_manifest = build_manual_run_job(
            playbook_name="test-playbook",
            namespace="test-namespace",
            playbook_spec={"playbookPath": "test.yml"},
            run_id="test-run-id",
            owner_uid="test-uid",
            executor_service_account="test-executor-sa",
        )

        assert job_manifest["spec"]["template"]["spec"]["serviceAccountName"] == "test-executor-sa"

    def test_manual_run_job_without_executor_service_account(self):
        """Test manual run job omits ServiceAccount when not provided."""
        job_manifest = build_manual_run_job(
            playbook_name="test-playbook",
            namespace="test-namespace",
            playbook_spec={"playbookPath": "test.yml"},
            run_id="test-run-id",
            owner_uid="test-uid",
            executor_service_account=None,
        )

        assert "serviceAccountName" not in job_manifest["spec"]["template"]["spec"]

    def test_cronjob_with_executor_service_account(self):
        """Test cronjob includes executor ServiceAccount when provided."""
        cronjob_manifest = build_cronjob(
            schedule_name="test-schedule",
            namespace="test-namespace",
            computed_schedule="0 0 * * *",
            playbook={"spec": {"playbookPath": "test.yml"}},
            schedule_spec={},
            owner_uid="test-uid",
            executor_service_account="test-executor-sa",
        )

        assert (
            cronjob_manifest["spec"]["jobTemplate"]["spec"]["template"]["spec"][
                "serviceAccountName"
            ]
            == "test-executor-sa"
        )

    def test_cronjob_without_executor_service_account(self):
        """Test cronjob omits ServiceAccount when not provided."""
        cronjob_manifest = build_cronjob(
            schedule_name="test-schedule",
            namespace="test-namespace",
            computed_schedule="0 0 * * *",
            playbook={"spec": {"playbookPath": "test.yml"}},
            schedule_spec={},
            owner_uid="test-uid",
            executor_service_account=None,
        )

        assert (
            "serviceAccountName"
            not in cronjob_manifest["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        )

    def test_cronjob_playbook_service_account_takes_precedence(self):
        """Test that playbook-specified ServiceAccount takes precedence over executor ServiceAccount."""
        cronjob_manifest = build_cronjob(
            schedule_name="test-schedule",
            namespace="test-namespace",
            computed_schedule="0 0 * * *",
            playbook={
                "spec": {
                    "playbookPath": "test.yml",
                    "runtime": {"serviceAccountName": "playbook-sa"},
                }
            },
            schedule_spec={},
            owner_uid="test-uid",
            executor_service_account="executor-sa",
        )

        assert (
            cronjob_manifest["spec"]["jobTemplate"]["spec"]["template"]["spec"][
                "serviceAccountName"
            ]
            == "playbook-sa"
        )

    def test_cronjob_executor_service_account_fallback(self):
        """Test that executor ServiceAccount is used when playbook doesn't specify one."""
        cronjob_manifest = build_cronjob(
            schedule_name="test-schedule",
            namespace="test-namespace",
            computed_schedule="0 0 * * *",
            playbook={"spec": {"playbookPath": "test.yml"}},
            schedule_spec={},
            owner_uid="test-uid",
            executor_service_account="executor-sa",
        )

        assert (
            cronjob_manifest["spec"]["jobTemplate"]["spec"]["template"]["spec"][
                "serviceAccountName"
            ]
            == "executor-sa"
        )
