"""Unit tests for image pinning functionality."""

from __future__ import annotations

import pytest

from ansible_operator.builders.cronjob_builder import build_cronjob
from ansible_operator.builders.job_builder import (
    build_connectivity_probe_job,
    build_manual_run_job,
)


class TestImagePinning:
    """Test image pinning functionality in builders."""

    def test_connectivity_probe_job_with_digest(self):
        """Test connectivity probe job with digest pinning."""
        manifest = build_connectivity_probe_job(
            repository_name="test-repo",
            namespace="default",
            repository_spec={"url": "https://github.com/test/repo.git"},
            owner_uid="test-uid",
            image_default="kenchrcum/ansible-runner:latest",
            image_digest="sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        )

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        expected_image = "kenchrcum/ansible-runner@sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        assert container["image"] == expected_image

    def test_connectivity_probe_job_without_digest(self):
        """Test connectivity probe job without digest pinning."""
        manifest = build_connectivity_probe_job(
            repository_name="test-repo",
            namespace="default",
            repository_spec={"url": "https://github.com/test/repo.git"},
            owner_uid="test-uid",
            image_default="kenchrcum/ansible-runner:latest",
            image_digest=None,
        )

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        assert container["image"] == "kenchrcum/ansible-runner:latest"

    def test_connectivity_probe_job_empty_digest(self):
        """Test connectivity probe job with empty digest."""
        manifest = build_connectivity_probe_job(
            repository_name="test-repo",
            namespace="default",
            repository_spec={"url": "https://github.com/test/repo.git"},
            owner_uid="test-uid",
            image_default="kenchrcum/ansible-runner:latest",
            image_digest="",
        )

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        assert container["image"] == "kenchrcum/ansible-runner:latest"

    def test_manual_run_job_with_digest(self):
        """Test manual run job with digest pinning."""
        manifest = build_manual_run_job(
            playbook_name="test-playbook",
            namespace="default",
            playbook_spec={"playbookPath": "playbook.yml"},
            run_id="test-run-id",
            owner_uid="test-uid",
            image_default="kenchrcum/ansible-runner:latest",
            image_digest="sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        )

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        expected_image = "kenchrcum/ansible-runner@sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        assert container["image"] == expected_image

    def test_manual_run_job_without_digest(self):
        """Test manual run job without digest pinning."""
        manifest = build_manual_run_job(
            playbook_name="test-playbook",
            namespace="default",
            playbook_spec={"playbookPath": "playbook.yml"},
            run_id="test-run-id",
            owner_uid="test-uid",
            image_default="kenchrcum/ansible-runner:latest",
            image_digest=None,
        )

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        assert container["image"] == "kenchrcum/ansible-runner:latest"

    def test_manual_run_job_custom_image_with_digest(self):
        """Test manual run job with custom image and digest pinning."""
        manifest = build_manual_run_job(
            playbook_name="test-playbook",
            namespace="default",
            playbook_spec={
                "playbookPath": "playbook.yml",
                "runtime": {"image": "custom/ansible-runner:v1.0"},
            },
            run_id="test-run-id",
            owner_uid="test-uid",
            image_default="kenchrcum/ansible-runner:latest",
            image_digest="sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        )

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        expected_image = "custom/ansible-runner@sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        assert container["image"] == expected_image

    def test_manual_run_job_custom_image_with_existing_digest(self):
        """Test manual run job with custom image that already has a digest."""
        manifest = build_manual_run_job(
            playbook_name="test-playbook",
            namespace="default",
            playbook_spec={
                "playbookPath": "playbook.yml",
                "runtime": {
                    "image": "custom/ansible-runner@sha256:existing1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
                },
            },
            run_id="test-run-id",
            owner_uid="test-uid",
            image_default="kenchrcum/ansible-runner:latest",
            image_digest="sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        )

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        # Should not override existing digest
        expected_image = "custom/ansible-runner@sha256:existing1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        assert container["image"] == expected_image

    def test_cronjob_with_digest(self):
        """Test cronjob with digest pinning."""
        manifest = build_cronjob(
            schedule_name="test-schedule",
            namespace="default",
            computed_schedule="0 0 * * *",
            playbook={"spec": {"playbookPath": "playbook.yml"}},
            schedule_spec={},
            owner_uid="test-uid",
            image_default="kenchrcum/ansible-runner:latest",
            image_digest="sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        )

        container = manifest["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
        expected_image = "kenchrcum/ansible-runner@sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        assert container["image"] == expected_image

    def test_cronjob_without_digest(self):
        """Test cronjob without digest pinning."""
        manifest = build_cronjob(
            schedule_name="test-schedule",
            namespace="default",
            computed_schedule="0 0 * * *",
            playbook={"spec": {"playbookPath": "playbook.yml"}},
            schedule_spec={},
            owner_uid="test-uid",
            image_default="kenchrcum/ansible-runner:latest",
            image_digest=None,
        )

        container = manifest["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
        assert container["image"] == "kenchrcum/ansible-runner:latest"

    def test_cronjob_custom_image_with_digest(self):
        """Test cronjob with custom image and digest pinning."""
        manifest = build_cronjob(
            schedule_name="test-schedule",
            namespace="default",
            computed_schedule="0 0 * * *",
            playbook={
                "spec": {
                    "playbookPath": "playbook.yml",
                    "runtime": {"image": "custom/ansible-runner:v1.0"},
                }
            },
            schedule_spec={},
            owner_uid="test-uid",
            image_default="kenchrcum/ansible-runner:latest",
            image_digest="sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        )

        container = manifest["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
        expected_image = "custom/ansible-runner@sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        assert container["image"] == expected_image

    def test_cronjob_custom_image_with_existing_digest(self):
        """Test cronjob with custom image that already has a digest."""
        manifest = build_cronjob(
            schedule_name="test-schedule",
            namespace="default",
            computed_schedule="0 0 * * *",
            playbook={
                "spec": {
                    "playbookPath": "playbook.yml",
                    "runtime": {
                        "image": "custom/ansible-runner@sha256:existing1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
                    },
                }
            },
            schedule_spec={},
            owner_uid="test-uid",
            image_default="kenchrcum/ansible-runner:latest",
            image_digest="sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        )

        container = manifest["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
        # Should not override existing digest
        expected_image = "custom/ansible-runner@sha256:existing1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        assert container["image"] == expected_image

    def test_digest_format_validation(self):
        """Test that digest format is properly handled."""
        # Test valid digest format
        manifest = build_connectivity_probe_job(
            repository_name="test-repo",
            namespace="default",
            repository_spec={"url": "https://github.com/test/repo.git"},
            owner_uid="test-uid",
            image_default="kenchrcum/ansible-runner:latest",
            image_digest="sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        )

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        assert container["image"].startswith("kenchrcum/ansible-runner@sha256:")
        assert len(container["image"].split("@")[1]) == 71  # sha256: + 64 hex chars

    def test_image_reference_parsing(self):
        """Test that image reference parsing works correctly."""
        # Test with tag
        manifest = build_connectivity_probe_job(
            repository_name="test-repo",
            namespace="default",
            repository_spec={"url": "https://github.com/test/repo.git"},
            owner_uid="test-uid",
            image_default="kenchrcum/ansible-runner:latest",
            image_digest="sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        )

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        assert (
            container["image"]
            == "kenchrcum/ansible-runner@sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        )

        # Test with custom registry
        manifest = build_connectivity_probe_job(
            repository_name="test-repo",
            namespace="default",
            repository_spec={"url": "https://github.com/test/repo.git"},
            owner_uid="test-uid",
            image_default="registry.example.com/ansible-runner:v1.0",
            image_digest="sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        )

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        assert (
            container["image"]
            == "registry.example.com/ansible-runner@sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        )

    def test_edge_cases(self):
        """Test edge cases for image pinning."""
        # Test with empty string digest
        manifest = build_connectivity_probe_job(
            repository_name="test-repo",
            namespace="default",
            repository_spec={"url": "https://github.com/test/repo.git"},
            owner_uid="test-uid",
            image_default="kenchrcum/ansible-runner:latest",
            image_digest="",
        )

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        assert container["image"] == "kenchrcum/ansible-runner:latest"

        # Test with None digest
        manifest = build_connectivity_probe_job(
            repository_name="test-repo",
            namespace="default",
            repository_spec={"url": "https://github.com/test/repo.git"},
            owner_uid="test-uid",
            image_default="kenchrcum/ansible-runner:latest",
            image_digest=None,
        )

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        assert container["image"] == "kenchrcum/ansible-runner:latest"
