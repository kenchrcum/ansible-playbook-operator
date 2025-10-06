"""
Integration tests for Ansible Playbook Operator using kind cluster.

These tests deploy the operator, create CRs, and verify CronJob materialization,
Job success/failure paths, authentication matrix, and pod security defaults.
"""

import os
import time
import subprocess
import tempfile
from typing import Dict, Any, Optional
import pytest
from kubernetes import client, config
from kubernetes.client.rest import ApiException


class KindCluster:
    """Helper class for managing kind cluster operations."""

    def __init__(self, cluster_name: str = "ansible-operator-test"):
        self.cluster_name = cluster_name
        self.kubeconfig_path: Optional[str] = None

    def create(self) -> None:
        """Create a kind cluster."""
        print(f"Creating kind cluster: {self.cluster_name}")
        result = subprocess.run(
            ["kind", "create", "cluster", "--name", self.cluster_name, "--config", "-"],
            input=self._get_kind_config(),
            text=True,
            capture_output=True,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to create kind cluster: {result.stderr}")

        # Get kubeconfig
        result = subprocess.run(
            ["kind", "get", "kubeconfig", "--name", self.cluster_name],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to get kubeconfig: {result.stderr}")

        # Write kubeconfig to temp file
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".yaml") as f:
            f.write(result.stdout)
            self.kubeconfig_path = f.name

        # Load kubeconfig
        config.load_kube_config(config_file=self.kubeconfig_path)

    def delete(self) -> None:
        """Delete the kind cluster."""
        if self.kubeconfig_path is not None and os.path.exists(self.kubeconfig_path):
            os.unlink(self.kubeconfig_path)

        subprocess.run(
            ["kind", "delete", "cluster", "--name", self.cluster_name], capture_output=True
        )

    def _get_kind_config(self) -> str:
        """Get kind cluster configuration."""
        return """
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: ClusterConfiguration
    apiServer:
      extraArgs:
        "feature-gates": "PodSecurity=true"
    - |
      kind: KubeletConfiguration
      featureGates:
        PodSecurity: true
"""


@pytest.fixture(scope="session")
def kind_cluster():
    """Create and manage a kind cluster for integration tests."""
    cluster = KindCluster()
    cluster.create()
    yield cluster
    cluster.delete()


@pytest.fixture(scope="session")
def operator_deployed(kind_cluster):
    """Deploy the operator to the kind cluster."""
    # Build and load operator image
    subprocess.run(
        [
            "kind",
            "load",
            "docker-image",
            "kenchrcum/ansible-playbook-operator:0.1.0",
            "--name",
            kind_cluster.cluster_name,
        ],
        check=True,
    )

    # Deploy operator via Helm
    subprocess.run(
        [
            "helm",
            "install",
            "ansible-operator",
            "./helm/ansible-playbook-operator",
            "--set",
            "operator.image.digest=",
            "--set",
            "operator.image.tag=0.1.0",
            "--set",
            "operator.watch.scope=all",
            "--set",
            "operator.metrics.enabled=true",
            "--create-namespace",
            "--namespace",
            "ansible-operator-system",
        ],
        check=True,
    )

    # Wait for operator to be ready
    v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()

    # Wait for deployment to be ready
    while True:
        try:
            deployment = apps_v1.read_namespaced_deployment(
                name="ansible-operator", namespace="ansible-operator-system"
            )
            if deployment.status.ready_replicas and deployment.status.ready_replicas >= 1:
                break
        except ApiException:
            pass
        time.sleep(2)

    return True


@pytest.fixture
def test_namespace():
    """Create a test namespace for each test."""
    v1 = client.CoreV1Api()
    namespace_name = f"test-{int(time.time())}"

    namespace = client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace_name))

    v1.create_namespace(namespace)
    yield namespace_name

    # Cleanup
    try:
        v1.delete_namespace(name=namespace_name)
    except ApiException:
        pass


class TestRepositoryIntegration:
    """Test Repository CR functionality."""

    def test_repository_ssh_auth(self, operator_deployed, test_namespace):
        """Test Repository with SSH authentication."""
        # Create SSH secret
        ssh_secret = client.V1Secret(
            metadata=client.V1ObjectMeta(name="ssh-credentials", namespace=test_namespace),
            type="kubernetes.io/ssh-auth",
            data={"ssh-privatekey": "LS0tLS1CRUdJTi..."},  # Mock SSH key
        )

        v1 = client.CoreV1Api()
        v1.create_namespaced_secret(namespace=test_namespace, body=ssh_secret)

        # Create known_hosts ConfigMap
        known_hosts_cm = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(name="github-known-hosts", namespace=test_namespace),
            data={"known_hosts": "github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC..."},
        )

        v1.create_namespaced_config_map(namespace=test_namespace, body=known_hosts_cm)

        # Create Repository CR
        repo_manifest = {
            "apiVersion": "ansible.cloud37.dev/v1alpha1",
            "kind": "Repository",
            "metadata": {"name": "test-ssh-repo", "namespace": test_namespace},
            "spec": {
                "url": "git@github.com:example/test-repo.git",
                "branch": "main",
                "auth": {"method": "ssh", "secretRef": {"name": "ssh-credentials"}},
                "ssh": {
                    "knownHostsConfigMapRef": {"name": "github-known-hosts"},
                    "strictHostKeyChecking": True,
                },
            },
        }

        # Apply Repository CR
        custom_api = client.CustomObjectsApi()
        custom_api.create_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=test_namespace,
            plural="repositories",
            body=repo_manifest,
        )

        # Wait for Repository to be processed
        time.sleep(5)

        # Check Repository status
        repo = custom_api.get_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=test_namespace,
            plural="repositories",
            name="test-ssh-repo",
        )

        # Verify conditions
        conditions = repo.get("status", {}).get("conditions", [])
        assert len(conditions) > 0

        # Check for connectivity probe job
        batch_v1 = client.BatchV1Api()
        jobs = batch_v1.list_namespaced_job(namespace=test_namespace)
        probe_jobs = [
            job
            for job in jobs.items
            if job.metadata.labels.get("ansible.cloud37.dev/probe-type") == "connectivity"
        ]
        assert len(probe_jobs) > 0

        # Verify probe job security context
        probe_job = probe_jobs[0]
        pod_template = probe_job.spec.template.spec
        security_context = pod_template.security_context

        assert security_context.run_as_non_root is True
        assert security_context.run_as_user == 1000
        assert security_context.run_as_group == 1000

        # Check container security context
        container = pod_template.containers[0]
        container_security = container.security_context

        assert container_security.allow_privilege_escalation is False
        assert container_security.read_only_root_filesystem is True
        assert container_security.seccomp_profile.type == "RuntimeDefault"
        assert container_security.capabilities.drop == ["ALL"]

    def test_repository_https_token_auth(self, operator_deployed, test_namespace):
        """Test Repository with HTTPS token authentication."""
        # Create token secret
        token_secret = client.V1Secret(
            metadata=client.V1ObjectMeta(name="repo-token", namespace=test_namespace),
            type="Opaque",
            data={"token": "Z2hwX1Rva2Vu..."},  # Mock GitHub token
        )

        v1 = client.CoreV1Api()
        v1.create_namespaced_secret(namespace=test_namespace, body=token_secret)

        # Create Repository CR
        repo_manifest = {
            "apiVersion": "ansible.cloud37.dev/v1alpha1",
            "kind": "Repository",
            "metadata": {"name": "test-https-repo", "namespace": test_namespace},
            "spec": {
                "url": "https://github.com/example/test-repo.git",
                "branch": "main",
                "auth": {"method": "token", "secretRef": {"name": "repo-token"}},
            },
        }

        # Apply Repository CR
        custom_api = client.CustomObjectsApi()
        custom_api.create_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=test_namespace,
            plural="repositories",
            body=repo_manifest,
        )

        # Wait for Repository to be processed
        time.sleep(5)

        # Check Repository status
        repo = custom_api.get_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=test_namespace,
            plural="repositories",
            name="test-https-repo",
        )

        # Verify conditions
        conditions = repo.get("status", {}).get("conditions", [])
        assert len(conditions) > 0


class TestPlaybookIntegration:
    """Test Playbook CR functionality."""

    def test_playbook_creation(self, operator_deployed, test_namespace):
        """Test Playbook CR creation and validation."""
        # First create a Repository
        repo_manifest = {
            "apiVersion": "ansible.cloud37.dev/v1alpha1",
            "kind": "Repository",
            "metadata": {"name": "test-repo", "namespace": test_namespace},
            "spec": {"url": "https://github.com/example/test-repo.git", "branch": "main"},
        }

        custom_api = client.CustomObjectsApi()
        custom_api.create_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=test_namespace,
            plural="repositories",
            body=repo_manifest,
        )

        # Wait for Repository to be ready
        time.sleep(3)

        # Create Playbook CR
        playbook_manifest = {
            "apiVersion": "ansible.cloud37.dev/v1alpha1",
            "kind": "Playbook",
            "metadata": {"name": "test-playbook", "namespace": test_namespace},
            "spec": {
                "repositoryRef": {"name": "test-repo"},
                "playbookPath": "playbooks/test.yml",
                "inventoryPath": "inventory/hosts",
                "execution": {"tags": ["deploy"], "checkMode": False, "verbosity": 1},
            },
        }

        custom_api.create_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=test_namespace,
            plural="playbooks",
            body=playbook_manifest,
        )

        # Wait for Playbook to be processed
        time.sleep(3)

        # Check Playbook status
        playbook = custom_api.get_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=test_namespace,
            plural="playbooks",
            name="test-playbook",
        )

        # Verify conditions
        conditions = playbook.get("status", {}).get("conditions", [])
        assert len(conditions) > 0


class TestScheduleIntegration:
    """Test Schedule CR functionality."""

    def test_schedule_cronjob_materialization(self, operator_deployed, test_namespace):
        """Test Schedule CR creates CronJob."""
        # Create Repository
        repo_manifest = {
            "apiVersion": "ansible.cloud37.dev/v1alpha1",
            "kind": "Repository",
            "metadata": {"name": "test-repo", "namespace": test_namespace},
            "spec": {"url": "https://github.com/example/test-repo.git", "branch": "main"},
        }

        custom_api = client.CustomObjectsApi()
        custom_api.create_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=test_namespace,
            plural="repositories",
            body=repo_manifest,
        )

        time.sleep(3)

        # Create Playbook
        playbook_manifest = {
            "apiVersion": "ansible.cloud37.dev/v1alpha1",
            "kind": "Playbook",
            "metadata": {"name": "test-playbook", "namespace": test_namespace},
            "spec": {
                "repositoryRef": {"name": "test-repo"},
                "playbookPath": "playbooks/test.yml",
                "inventoryPath": "inventory/hosts",
            },
        }

        custom_api.create_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=test_namespace,
            plural="playbooks",
            body=playbook_manifest,
        )

        time.sleep(3)

        # Create Schedule
        schedule_manifest = {
            "apiVersion": "ansible.cloud37.dev/v1alpha1",
            "kind": "Schedule",
            "metadata": {"name": "test-schedule", "namespace": test_namespace},
            "spec": {
                "playbookRef": {"name": "test-playbook"},
                "schedule": "*/5 * * * *",  # Every 5 minutes
                "concurrencyPolicy": "Forbid",
                "backoffLimit": 3,
                "successfulJobsHistoryLimit": 1,
                "failedJobsHistoryLimit": 1,
                "ttlSecondsAfterFinished": 3600,
            },
        }

        custom_api.create_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=test_namespace,
            plural="schedules",
            body=schedule_manifest,
        )

        # Wait for Schedule to be processed
        time.sleep(5)

        # Check that CronJob was created
        batch_v1 = client.BatchV1Api()
        cronjobs = batch_v1.list_namespaced_cron_job(namespace=test_namespace)

        # Find the CronJob created by our Schedule
        schedule_cronjobs = [
            cj
            for cj in cronjobs.items
            if cj.metadata.owner_references and cj.metadata.owner_references[0].kind == "Schedule"
        ]

        assert len(schedule_cronjobs) > 0

        cronjob = schedule_cronjobs[0]

        # Verify CronJob properties
        assert cronjob.spec.schedule == "*/5 * * * *"
        assert cronjob.spec.concurrency_policy == "Forbid"
        assert cronjob.spec.successful_jobs_history_limit == 1
        assert cronjob.spec.failed_jobs_history_limit == 1

        # Verify Job template security context
        job_template = cronjob.spec.job_template.spec.template.spec
        security_context = job_template.security_context

        assert security_context.run_as_non_root is True
        assert security_context.run_as_user == 1000
        assert security_context.run_as_group == 1000

        # Check container security context
        container = job_template.containers[0]
        container_security = container.security_context

        assert container_security.allow_privilege_escalation is False
        assert container_security.read_only_root_filesystem is True
        assert container_security.seccomp_profile.type == "RuntimeDefault"
        assert container_security.capabilities.drop == ["ALL"]

        # Check Schedule status
        schedule = custom_api.get_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=test_namespace,
            plural="schedules",
            name="test-schedule",
        )

        # Verify Schedule status
        status = schedule.get("status", {})
        assert status.get("computedSchedule") == "*/5 * * * *"
        assert status.get("conditions") is not None

        conditions = status.get("conditions", [])
        ready_condition = next((c for c in conditions if c["type"] == "Ready"), None)
        assert ready_condition is not None


class TestJobExecution:
    """Test Job execution paths."""

    def test_manual_run_success(self, operator_deployed, test_namespace):
        """Test manual run annotation creates Job."""
        # Create Repository
        repo_manifest = {
            "apiVersion": "ansible.cloud37.dev/v1alpha1",
            "kind": "Repository",
            "metadata": {"name": "test-repo", "namespace": test_namespace},
            "spec": {"url": "https://github.com/example/test-repo.git", "branch": "main"},
        }

        custom_api = client.CustomObjectsApi()
        custom_api.create_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=test_namespace,
            plural="repositories",
            body=repo_manifest,
        )

        time.sleep(3)

        # Create Playbook
        playbook_manifest = {
            "apiVersion": "ansible.cloud37.dev/v1alpha1",
            "kind": "Playbook",
            "metadata": {"name": "test-playbook", "namespace": test_namespace},
            "spec": {
                "repositoryRef": {"name": "test-repo"},
                "playbookPath": "playbooks/test.yml",
                "inventoryPath": "inventory/hosts",
            },
        }

        custom_api.create_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=test_namespace,
            plural="playbooks",
            body=playbook_manifest,
        )

        time.sleep(3)

        # Add manual run annotation
        run_id = f"manual-{int(time.time())}"
        patch_body = {"metadata": {"annotations": {"ansible.cloud37.dev/run-now": run_id}}}

        custom_api.patch_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=test_namespace,
            plural="playbooks",
            name="test-playbook",
            body=patch_body,
        )

        # Wait for Job to be created
        time.sleep(5)

        # Check that Job was created
        batch_v1 = client.BatchV1Api()
        jobs = batch_v1.list_namespaced_job(namespace=test_namespace)

        # Find the Job created by manual run
        manual_jobs = [
            job
            for job in jobs.items
            if job.metadata.labels.get("ansible.cloud37.dev/run-id") == run_id
        ]

        assert len(manual_jobs) > 0

        job = manual_jobs[0]

        # Verify Job properties
        assert job.metadata.labels["ansible.cloud37.dev/run-id"] == run_id

        # Check Playbook status for manual run info
        playbook = custom_api.get_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=test_namespace,
            plural="playbooks",
            name="test-playbook",
        )

        status = playbook.get("status", {})
        last_manual_run = status.get("lastManualRun", {})

        assert last_manual_run.get("runId") == run_id
        assert last_manual_run.get("status") == "Running"
