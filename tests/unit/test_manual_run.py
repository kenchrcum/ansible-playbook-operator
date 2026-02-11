"""Unit tests for manual run functionality."""

from typing import Any
from unittest.mock import Mock, patch

import pytest
from kubernetes import client

from ansible_operator.builders.job_builder import build_manual_run_job
from ansible_operator.constants import ANNOTATION_RUN_NOW, LABEL_RUN_ID
from ansible_operator.services.manual_run import ManualRunService


class TestManualRunService:
    """Test manual run service functionality."""

    def test_detect_manual_run_request_with_annotation(self):
        """Test detection of manual run request via annotation."""
        service = ManualRunService()
        annotations = {ANNOTATION_RUN_NOW: "test-run-123"}

        run_id = service.detect_manual_run_request(annotations)

        assert run_id == "test-run-123"

    def test_detect_manual_run_request_without_annotation(self):
        """Test detection when no manual run annotation is present."""
        service = ManualRunService()
        annotations: dict[str, Any] = {}

        run_id = service.detect_manual_run_request(annotations)

        assert run_id is None

    def test_detect_manual_run_request_empty_annotation(self):
        """Test detection when annotation is empty."""
        service = ManualRunService()
        annotations = {ANNOTATION_RUN_NOW: ""}

        run_id = service.detect_manual_run_request(annotations)

        assert run_id == ""

    @patch("ansible_operator.services.manual_run.client.BatchV1Api")
    def test_create_manual_run_job(self, mock_batch_api):
        """Test creation of manual run Job."""
        service = ManualRunService()
        mock_api_instance = Mock()
        mock_batch_api.return_value = mock_api_instance

        playbook_spec = {
            "playbookPath": "site.yml",
            "inventoryPath": "inventory/hosts",
            "execution": {
                "tags": ["deploy"],
                "checkMode": True,
            },
        }

        repository_obj = {
            "spec": {
                "url": "https://github.com/example/repo.git",
                "auth": {
                    "method": "ssh",
                    "secretRef": {"name": "ssh-key"},
                },
            }
        }

        job_name = service.create_manual_run_job(
            playbook_name="test-playbook",
            namespace="test-ns",
            playbook_spec=playbook_spec,
            repository_obj=repository_obj,
            run_id="test-run-123",
            owner_uid="test-uid",
            known_hosts_available=True,
        )

        assert job_name.startswith("test-playbook-manual-")
        mock_api_instance.create_namespaced_job.assert_called_once()

        # Verify Job manifest structure
        call_args = mock_api_instance.create_namespaced_job.call_args
        job_manifest = call_args[1]["body"]

        assert job_manifest["metadata"]["labels"][LABEL_RUN_ID] == "test-run-123"
        assert job_manifest["metadata"]["labels"]["ansible.cloud37.dev/run-type"] == "manual"
        assert job_manifest["spec"]["template"]["spec"]["containers"][0]["name"] == "ansible-runner"

    @patch("ansible_operator.services.manual_run.client.CustomObjectsApi")
    def test_update_playbook_manual_run_status(self, mock_custom_api):
        """Test updating Playbook status with manual run information."""
        service = ManualRunService()
        mock_api_instance = Mock()
        mock_custom_api.return_value = mock_api_instance

        service.update_playbook_manual_run_status(
            playbook_name="test-playbook",
            namespace="test-ns",
            run_id="test-run-123",
            job_name="test-job",
            status="Running",
            reason="ManualRunStarted",
            message="Job created",
        )

        mock_api_instance.patch_namespaced_custom_object_status.assert_called_once()

        # Verify status update structure
        call_args = mock_api_instance.patch_namespaced_custom_object_status.call_args
        patch_body = call_args[1]["body"]

        assert "lastManualRun" in patch_body["status"]
        manual_run = patch_body["status"]["lastManualRun"]
        assert manual_run["runId"] == "test-run-123"
        assert manual_run["jobRef"] == "test-ns/test-job"
        assert manual_run["status"] == "Running"
        assert manual_run["reason"] == "ManualRunStarted"
        assert manual_run["message"] == "Job created"

    @patch("ansible_operator.services.manual_run.client.CustomObjectsApi")
    def test_update_playbook_manual_run_status_with_completion_time(self, mock_custom_api):
        """Test updating Playbook status with completion time."""
        service = ManualRunService()
        mock_api_instance = Mock()
        mock_custom_api.return_value = mock_api_instance

        service.update_playbook_manual_run_status(
            playbook_name="test-playbook",
            namespace="test-ns",
            run_id="test-run-123",
            job_name="test-job",
            status="Succeeded",
            reason="JobSucceeded",
            message="Job completed",
            completion_time="2024-01-01T12:00:00Z",
        )

        # Verify completion time is included
        call_args = mock_api_instance.patch_namespaced_custom_object_status.call_args
        patch_body = call_args[1]["body"]

        manual_run = patch_body["status"]["lastManualRun"]
        assert manual_run["completionTime"] == "2024-01-01T12:00:00Z"

    @patch("ansible_operator.services.manual_run.client.CustomObjectsApi")
    def test_clear_manual_run_annotation(self, mock_custom_api):
        """Test clearing manual run annotation."""
        service = ManualRunService()
        mock_api_instance = Mock()
        mock_custom_api.return_value = mock_api_instance

        service.clear_manual_run_annotation("test-playbook", "test-ns")

        mock_api_instance.patch_namespaced_custom_object.assert_called_once()

        # Verify annotation is set to None
        call_args = mock_api_instance.patch_namespaced_custom_object.call_args
        patch_body = call_args[1]["body"]

        assert patch_body["metadata"]["annotations"][ANNOTATION_RUN_NOW] is None

    @patch("ansible_operator.services.manual_run.client.BatchV1Api")
    def test_create_schedule_manual_run_job(self, mock_batch_api):
        """Test creation of manual run Job for Schedule."""
        service = ManualRunService()
        mock_api_instance = Mock()
        mock_batch_api.return_value = mock_api_instance

        playbook_obj = {
            "spec": {
                "playbookPath": "site.yml",
                "inventoryPath": "inventory/hosts",
                "execution": {
                    "tags": ["deploy"],
                    "checkMode": True,
                },
            }
        }

        repository_obj = {
            "spec": {
                "url": "https://github.com/example/repo.git",
                "auth": {
                    "method": "ssh",
                    "secretRef": {"name": "ssh-key"},
                },
            }
        }

        job_name = service.create_schedule_manual_run_job(
            schedule_name="test-schedule",
            namespace="test-ns",
            playbook_obj=playbook_obj,
            repository_obj=repository_obj,
            run_id="test-run-456",
            owner_uid="schedule-uid",
            known_hosts_available=True,
        )

        assert job_name.startswith("test-schedule-manual-")
        mock_api_instance.create_namespaced_job.assert_called_once()

        # Verify Job manifest structure
        call_args = mock_api_instance.create_namespaced_job.call_args
        job_manifest = call_args[1]["body"]

        assert job_manifest["metadata"]["labels"][LABEL_RUN_ID] == "test-run-456"
        assert job_manifest["metadata"]["labels"]["ansible.cloud37.dev/run-type"] == "manual"
        # Verify owner is Schedule, not Playbook
        owner_refs = job_manifest["metadata"]["ownerReferences"]
        assert owner_refs[0]["kind"] == "Schedule"
        assert owner_refs[0]["name"] == "test-schedule"

    @patch("ansible_operator.services.manual_run.client.CustomObjectsApi")
    def test_update_schedule_manual_run_status(self, mock_custom_api):
        """Test updating Schedule status with manual run information."""
        service = ManualRunService()
        mock_api_instance = Mock()
        mock_custom_api.return_value = mock_api_instance

        service.update_schedule_manual_run_status(
            schedule_name="test-schedule",
            namespace="test-ns",
            run_id="test-run-456",
            job_name="test-job",
            status="Running",
            reason="ManualRunStarted",
            message="Job created",
        )

        mock_api_instance.patch_namespaced_custom_object_status.assert_called_once()

        # Verify status update structure
        call_args = mock_api_instance.patch_namespaced_custom_object_status.call_args
        assert call_args[1]["plural"] == "schedules"
        patch_body = call_args[1]["body"]

        assert "lastManualRun" in patch_body["status"]
        manual_run = patch_body["status"]["lastManualRun"]
        assert manual_run["runId"] == "test-run-456"
        assert manual_run["jobRef"] == "test-ns/test-job"
        assert manual_run["status"] == "Running"
        assert manual_run["reason"] == "ManualRunStarted"
        assert manual_run["message"] == "Job created"

    @patch("ansible_operator.services.manual_run.client.CustomObjectsApi")
    def test_update_schedule_manual_run_status_with_completion_time(self, mock_custom_api):
        """Test updating Schedule status with completion time."""
        service = ManualRunService()
        mock_api_instance = Mock()
        mock_custom_api.return_value = mock_api_instance

        service.update_schedule_manual_run_status(
            schedule_name="test-schedule",
            namespace="test-ns",
            run_id="test-run-456",
            job_name="test-job",
            status="Succeeded",
            reason="JobSucceeded",
            message="Job completed",
            completion_time="2024-01-01T12:00:00Z",
        )

        # Verify completion time is included
        call_args = mock_api_instance.patch_namespaced_custom_object_status.call_args
        patch_body = call_args[1]["body"]

        manual_run = patch_body["status"]["lastManualRun"]
        assert manual_run["completionTime"] == "2024-01-01T12:00:00Z"

    @patch("ansible_operator.services.manual_run.client.CustomObjectsApi")
    def test_clear_schedule_manual_run_annotation(self, mock_custom_api):
        """Test clearing manual run annotation from Schedule."""
        service = ManualRunService()
        mock_api_instance = Mock()
        mock_custom_api.return_value = mock_api_instance

        service.clear_schedule_manual_run_annotation("test-schedule", "test-ns")

        mock_api_instance.patch_namespaced_custom_object.assert_called_once()

        # Verify annotation is set to None and plural is schedules
        call_args = mock_api_instance.patch_namespaced_custom_object.call_args
        assert call_args[1]["plural"] == "schedules"
        patch_body = call_args[1]["body"]

        assert patch_body["metadata"]["annotations"][ANNOTATION_RUN_NOW] is None


class TestManualRunJobBuilder:
    """Test manual run Job builder functionality."""

    def test_build_manual_run_job_basic(self):
        """Test building basic manual run Job."""
        playbook_spec = {
            "playbookPath": "site.yml",
            "inventoryPath": "inventory/hosts",
        }

        job_manifest = build_manual_run_job(
            playbook_name="test-playbook",
            namespace="test-ns",
            playbook_spec=playbook_spec,
            repository=None,
            known_hosts_available=False,
            run_id="test-run-123",
            owner_uid="test-uid",
        )

        assert job_manifest["metadata"]["name"].startswith("test-playbook-manual-")
        assert job_manifest["metadata"]["labels"][LABEL_RUN_ID] == "test-run-123"
        assert job_manifest["metadata"]["labels"]["ansible.cloud37.dev/run-type"] == "manual"

        # Verify command includes playbook path
        command = job_manifest["spec"]["template"]["spec"]["containers"][0]["command"]
        assert "site.yml" in " ".join(command)

    def test_build_manual_run_job_with_execution_options(self):
        """Test building manual run Job with execution options."""
        playbook_spec = {
            "playbookPath": "site.yml",
            "inventoryPath": "inventory/hosts",
            "execution": {
                "tags": ["deploy", "config"],
                "skipTags": ["test"],
                "checkMode": True,
                "diff": True,
                "verbosity": 2,
                "limit": "web-servers",
                "connectionTimeout": 30,
                "forks": 5,
                "strategy": "free",
                "flushCache": True,
                "forceHandlers": True,
                "startAtTask": "Install packages",
                "step": True,
            },
        }

        job_manifest = build_manual_run_job(
            playbook_name="test-playbook",
            namespace="test-ns",
            playbook_spec=playbook_spec,
            repository=None,
            known_hosts_available=False,
            run_id="test-run-123",
            owner_uid="test-uid",
        )

        # Verify command includes execution options
        command = job_manifest["spec"]["template"]["spec"]["containers"][0]["command"]
        command_str = " ".join(command)

        assert "--tags deploy,config" in command_str
        assert "--skip-tags test" in command_str
        assert "--check" in command_str
        assert "--diff" in command_str
        assert "-vv" in command_str
        assert "--limit web-servers" in command_str
        assert "--timeout 30" in command_str
        assert "--forks 5" in command_str
        assert "--strategy free" in command_str
        assert "--flush-cache" in command_str
        assert "--force-handlers" in command_str
        assert "--start-at-task Install packages" in command_str
        assert "--step" in command_str

    def test_build_manual_run_job_with_vault_password(self):
        """Test building manual run Job with vault password."""
        playbook_spec = {
            "playbookPath": "site.yml",
            "inventoryPath": "inventory/hosts",
            "secrets": {
                "vaultPasswordSecretRef": {"name": "vault-password"},
            },
        }

        job_manifest = build_manual_run_job(
            playbook_name="test-playbook",
            namespace="test-ns",
            playbook_spec=playbook_spec,
            repository=None,
            known_hosts_available=False,
            run_id="test-run-123",
            owner_uid="test-uid",
        )

        # Verify vault password volume and mount
        volumes = job_manifest["spec"]["template"]["spec"]["volumes"]
        volume_mounts = job_manifest["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]

        vault_volume = next((v for v in volumes if v["name"] == "vault-password"), None)
        assert vault_volume is not None
        assert vault_volume["secret"]["secretName"] == "vault-password"

        vault_mount = next((m for m in volume_mounts if m["name"] == "vault-password"), None)
        assert vault_mount is not None
        assert vault_mount["mountPath"] == "/vault-password"

        # Verify command includes vault password file
        command = job_manifest["spec"]["template"]["spec"]["containers"][0]["command"]
        command_str = " ".join(command)
        assert "--vault-password-file /vault-password/password" in command_str

    def test_build_manual_run_job_with_ssh_auth(self):
        """Test building manual run Job with SSH authentication."""
        playbook_spec = {
            "playbookPath": "site.yml",
            "inventoryPath": "inventory/hosts",
        }

        repository_obj = {
            "spec": {
                "url": "git@github.com:example/repo.git",
                "auth": {
                    "method": "ssh",
                    "secretRef": {"name": "ssh-key"},
                },
                "ssh": {
                    "knownHostsConfigMapRef": {"name": "known-hosts"},
                    "strictHostKeyChecking": True,
                },
            }
        }

        job_manifest = build_manual_run_job(
            playbook_name="test-playbook",
            namespace="test-ns",
            playbook_spec=playbook_spec,
            repository=repository_obj,
            known_hosts_available=True,
            run_id="test-run-123",
            owner_uid="test-uid",
        )

        # Verify SSH volumes and mounts
        volumes = job_manifest["spec"]["template"]["spec"]["volumes"]
        volume_mounts = job_manifest["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]

        ssh_volume = next((v for v in volumes if v["name"] == "ssh-auth"), None)
        assert ssh_volume is not None
        assert ssh_volume["secret"]["secretName"] == "ssh-key"

        known_hosts_volume = next((v for v in volumes if v["name"] == "ssh-known"), None)
        assert known_hosts_volume is not None
        assert known_hosts_volume["configMap"]["name"] == "known-hosts"

        ssh_mount = next((m for m in volume_mounts if m["name"] == "ssh-auth"), None)
        assert ssh_mount is not None
        assert ssh_mount["mountPath"] == "/ssh-auth"

    def test_build_manual_run_job_with_multiple_inventories(self):
        """Test building manual run Job with multiple inventory paths."""
        playbook_spec = {
            "playbookPath": "site.yml",
            "inventoryPaths": ["inventory/hosts", "inventory/prod"],
        }

        job_manifest = build_manual_run_job(
            playbook_name="test-playbook",
            namespace="test-ns",
            playbook_spec=playbook_spec,
            repository=None,
            known_hosts_available=False,
            run_id="test-run-123",
            owner_uid="test-uid",
        )

        # Verify command includes multiple inventory paths
        command = job_manifest["spec"]["template"]["spec"]["containers"][0]["command"]
        command_str = " ".join(command)
        assert "inventory/hosts,inventory/prod" in command_str

    def test_build_manual_run_job_security_context(self):
        """Test that manual run Job has proper security context."""
        playbook_spec = {
            "playbookPath": "site.yml",
            "inventoryPath": "inventory/hosts",
        }

        job_manifest = build_manual_run_job(
            playbook_name="test-playbook",
            namespace="test-ns",
            playbook_spec=playbook_spec,
            repository=None,
            known_hosts_available=False,
            run_id="test-run-123",
            owner_uid="test-uid",
        )

        # Verify pod security context
        pod_security = job_manifest["spec"]["template"]["spec"]["securityContext"]
        assert pod_security["runAsNonRoot"] is True
        assert pod_security["runAsUser"] == 1000
        assert pod_security["runAsGroup"] == 1000
        assert pod_security["fsGroup"] == 1000

        # Verify container security context
        container_security = job_manifest["spec"]["template"]["spec"]["containers"][0][
            "securityContext"
        ]
        assert container_security["allowPrivilegeEscalation"] is False
        assert container_security["readOnlyRootFilesystem"] is True
        assert container_security["seccompProfile"]["type"] == "RuntimeDefault"
        assert container_security["capabilities"]["drop"] == ["ALL"]

    def test_build_manual_run_job_owner_references(self):
        """Test that manual run Job has proper owner references."""
        playbook_spec = {
            "playbookPath": "site.yml",
            "inventoryPath": "inventory/hosts",
        }

        job_manifest = build_manual_run_job(
            playbook_name="test-playbook",
            namespace="test-ns",
            playbook_spec=playbook_spec,
            repository=None,
            known_hosts_available=False,
            run_id="test-run-123",
            owner_uid="test-uid",
            owner_api_version="ansible.cloud37.dev/v1alpha1",
            owner_kind="Playbook",
            owner_name="test-playbook",
        )

        # Verify owner references
        owner_refs = job_manifest["metadata"]["ownerReferences"]
        assert len(owner_refs) == 1

        owner_ref = owner_refs[0]
        assert owner_ref["apiVersion"] == "ansible.cloud37.dev/v1alpha1"
        assert owner_ref["kind"] == "Playbook"
        assert owner_ref["name"] == "test-playbook"
        assert owner_ref["uid"] == "test-uid"
        assert owner_ref["controller"] is True
        assert owner_ref["blockOwnerDeletion"] is False

    def test_manual_run_builder_file_mounts(self):
        """Test that fileMounts are correctly mounted in the manual run Job."""
        playbook_spec = {
            "playbookPath": "site.yml",
            "secrets": {
                "fileMounts": [
                    {
                        "secretRef": {"name": "manual-secret"},
                        "mountPath": "/etc/manual/secret",
                    }
                ]
            },
        }

        job = build_manual_run_job(
            playbook_name="test-playbook",
            namespace="test-ns",
            playbook_spec=playbook_spec,
            run_id="test-run-123",
            owner_uid="test-uid",
        )

        volumes = job["spec"]["template"]["spec"]["volumes"]
        container = job["spec"]["template"]["spec"]["containers"][0]
        volume_mounts = container["volumeMounts"]

        # Verify file mount
        vol = next((v for v in volumes if v["name"] == "secret-mount-0"), None)
        assert vol is not None
        assert vol["secret"]["secretName"] == "manual-secret"

        mount = next((m for m in volume_mounts if m["name"] == "secret-mount-0"), None)
        assert mount is not None
        assert mount["mountPath"] == "/etc/manual/secret"
        assert mount["readOnly"] is True
