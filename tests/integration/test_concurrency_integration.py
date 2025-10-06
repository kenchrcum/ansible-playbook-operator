"""
Integration tests for concurrency and race condition scenarios using kind cluster.

These tests deploy the operator and create multiple schedules to test:
- Overlapping schedules with different concurrency policies
- Many schedules using random macros
- Operator restart scenarios
"""

import os
import time
import subprocess
import tempfile
from typing import Dict, Any, List, Optional, Union
import pytest
from kubernetes import client, config
from kubernetes.client.rest import ApiException


class KindCluster:
    """Helper class for managing kind cluster operations."""

    def __init__(self, cluster_name: str = "ansible-operator-concurrency-test"):
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
def concurrency_kind_cluster():
    """Create and manage a kind cluster for concurrency integration tests."""
    cluster = KindCluster()
    cluster.create()
    yield cluster
    cluster.delete()


@pytest.fixture(scope="session")
def concurrency_operator_deployed(concurrency_kind_cluster):
    """Deploy the operator to the kind cluster."""
    # Build and load operator image
    subprocess.run(
        [
            "kind",
            "load",
            "docker-image",
            "kenchrcum/ansible-playbook-operator:0.1.1",
            "--name",
            concurrency_kind_cluster.cluster_name,
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
            "operator.image.tag=0.1.1",
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
def concurrency_test_namespace():
    """Create a test namespace for each concurrency test."""
    v1 = client.CoreV1Api()
    namespace_name = f"concurrency-test-{int(time.time())}"

    namespace = client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace_name))

    v1.create_namespace(namespace)
    yield namespace_name

    # Cleanup
    try:
        v1.delete_namespace(name=namespace_name)
    except ApiException:
        pass


class TestConcurrencyIntegration:
    """Test concurrency scenarios in integration environment."""

    def test_overlapping_schedules_different_policies(
        self, concurrency_operator_deployed, concurrency_test_namespace
    ):
        """Test overlapping schedules with different concurrency policies."""
        namespace = concurrency_test_namespace
        custom_api = client.CustomObjectsApi()
        batch_v1 = client.BatchV1Api()

        # Create Repository
        repo_manifest = {
            "apiVersion": "ansible.cloud37.dev/v1alpha1",
            "kind": "Repository",
            "metadata": {"name": "test-repo", "namespace": namespace},
            "spec": {"url": "https://github.com/example/test-repo.git", "branch": "main"},
        }

        custom_api.create_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=namespace,
            plural="repositories",
            body=repo_manifest,
        )

        time.sleep(3)

        # Create Playbook
        playbook_manifest = {
            "apiVersion": "ansible.cloud37.dev/v1alpha1",
            "kind": "Playbook",
            "metadata": {"name": "test-playbook", "namespace": namespace},
            "spec": {
                "repositoryRef": {"name": "test-repo"},
                "playbookPath": "playbooks/test.yml",
                "inventoryPath": "inventory/hosts",
            },
        }

        custom_api.create_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=namespace,
            plural="playbooks",
            body=playbook_manifest,
        )

        time.sleep(3)

        # Create multiple schedules with different concurrency policies
        schedules = [
            {
                "name": "schedule-forbid",
                "policy": "Forbid",
                "schedule": "*/2 * * * *",  # Every 2 minutes
            },
            {
                "name": "schedule-allow",
                "policy": "Allow",
                "schedule": "*/3 * * * *",  # Every 3 minutes
            },
            {
                "name": "schedule-replace",
                "policy": "Replace",
                "schedule": "*/4 * * * *",  # Every 4 minutes
            },
        ]

        # Create all schedules
        for schedule_config in schedules:
            schedule_manifest = {
                "apiVersion": "ansible.cloud37.dev/v1alpha1",
                "kind": "Schedule",
                "metadata": {"name": schedule_config["name"], "namespace": namespace},
                "spec": {
                    "playbookRef": {"name": "test-playbook"},
                    "schedule": schedule_config["schedule"],
                    "concurrencyPolicy": schedule_config["policy"],
                    "backoffLimit": 1,
                    "successfulJobsHistoryLimit": 1,
                    "failedJobsHistoryLimit": 1,
                    "ttlSecondsAfterFinished": 60,
                },
            }

            custom_api.create_namespaced_custom_object(
                group="ansible.cloud37.dev",
                version="v1alpha1",
                namespace=namespace,
                plural="schedules",
                body=schedule_manifest,
            )

        # Wait for all schedules to be processed
        time.sleep(10)

        # Verify all CronJobs were created
        cronjobs = batch_v1.list_namespaced_cron_job(namespace=namespace)
        schedule_cronjobs = [
            cj
            for cj in cronjobs.items
            if cj.metadata.owner_references and cj.metadata.owner_references[0].kind == "Schedule"
        ]

        assert len(schedule_cronjobs) == 3

        # Verify each CronJob has the correct concurrency policy
        for cronjob in schedule_cronjobs:
            schedule_name = cronjob.metadata.owner_references[0].name
            expected_policy = next(s["policy"] for s in schedules if s["name"] == schedule_name)
            assert cronjob.spec.concurrency_policy == expected_policy

        # Verify Schedule statuses
        for schedule_config in schedules:
            schedule = custom_api.get_namespaced_custom_object(
                group="ansible.cloud37.dev",
                version="v1alpha1",
                namespace=namespace,
                plural="schedules",
                name=schedule_config["name"],
            )

            status = schedule.get("status", {})
            assert status.get("computedSchedule") == schedule_config["schedule"]

            conditions = status.get("conditions", [])
            ready_condition = next((c for c in conditions if c["type"] == "Ready"), None)
            assert ready_condition is not None
            assert ready_condition["status"] == "True"

    def test_many_schedules_random_macros(
        self, concurrency_operator_deployed, concurrency_test_namespace
    ):
        """Test many schedules using random macros."""
        namespace = concurrency_test_namespace
        custom_api = client.CustomObjectsApi()
        batch_v1 = client.BatchV1Api()

        # Create Repository
        repo_manifest = {
            "apiVersion": "ansible.cloud37.dev/v1alpha1",
            "kind": "Repository",
            "metadata": {"name": "test-repo", "namespace": namespace},
            "spec": {"url": "https://github.com/example/test-repo.git", "branch": "main"},
        }

        custom_api.create_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=namespace,
            plural="repositories",
            body=repo_manifest,
        )

        time.sleep(3)

        # Create Playbook
        playbook_manifest = {
            "apiVersion": "ansible.cloud37.dev/v1alpha1",
            "kind": "Playbook",
            "metadata": {"name": "test-playbook", "namespace": namespace},
            "spec": {
                "repositoryRef": {"name": "test-repo"},
                "playbookPath": "playbooks/test.yml",
                "inventoryPath": "inventory/hosts",
            },
        }

        custom_api.create_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=namespace,
            plural="playbooks",
            body=playbook_manifest,
        )

        time.sleep(3)

        # Create many schedules with random macros
        macro_types = [
            "@hourly-random",
            "@daily-random",
            "@weekly-random",
            "@monthly-random",
            "@yearly-random",
        ]
        schedules_created = []

        for i, macro in enumerate(macro_types):
            for j in range(5):  # 5 schedules per macro type
                schedule_name = f"schedule-{macro.replace('@', '').replace('-', '')}-{j}"
                schedule_manifest = {
                    "apiVersion": "ansible.cloud37.dev/v1alpha1",
                    "kind": "Schedule",
                    "metadata": {"name": schedule_name, "namespace": namespace},
                    "spec": {
                        "playbookRef": {"name": "test-playbook"},
                        "schedule": macro,
                        "concurrencyPolicy": "Forbid",
                        "backoffLimit": 1,
                        "successfulJobsHistoryLimit": 1,
                        "failedJobsHistoryLimit": 1,
                        "ttlSecondsAfterFinished": 60,
                    },
                }

                custom_api.create_namespaced_custom_object(
                    group="ansible.cloud37.dev",
                    version="v1alpha1",
                    namespace=namespace,
                    plural="schedules",
                    body=schedule_manifest,
                )
                schedules_created.append(schedule_name)

        # Wait for all schedules to be processed
        time.sleep(15)

        # Verify all CronJobs were created
        cronjobs = batch_v1.list_namespaced_cron_job(namespace=namespace)
        schedule_cronjobs = [
            cj
            for cj in cronjobs.items
            if cj.metadata.owner_references and cj.metadata.owner_references[0].kind == "Schedule"
        ]

        assert len(schedule_cronjobs) == len(schedules_created)

        # Verify all schedules have computed schedules (not macros)
        for schedule_name in schedules_created:
            schedule = custom_api.get_namespaced_custom_object(
                group="ansible.cloud37.dev",
                version="v1alpha1",
                namespace=namespace,
                plural="schedules",
                name=schedule_name,
            )

            status = schedule.get("status", {})
            computed_schedule = status.get("computedSchedule")
            assert computed_schedule is not None
            assert not computed_schedule.startswith("@")  # Should be expanded

            # Verify computed schedule is valid cron format
            parts = computed_schedule.split()
            assert len(parts) == 5

            # Verify ranges are valid
            minute, hour, dom, month, dow = parts
            assert 0 <= int(minute) <= 59
            assert 0 <= int(hour) <= 23
            assert 1 <= int(dom) <= 28  # Using 28 for universal validity
            assert 1 <= int(month) <= 12
            assert 0 <= int(dow) <= 6

        # Verify no duplicate computed schedules (deterministic uniqueness)
        computed_schedules = []
        for schedule_name in schedules_created:
            schedule = custom_api.get_namespaced_custom_object(
                group="ansible.cloud37.dev",
                version="v1alpha1",
                namespace=namespace,
                plural="schedules",
                name=schedule_name,
            )
            computed_schedule = schedule.get("status", {}).get("computedSchedule")
            computed_schedules.append(computed_schedule)

        # All computed schedules should be unique
        assert len(set(computed_schedules)) == len(computed_schedules)

    def test_operator_restart_recovery(
        self, concurrency_operator_deployed, concurrency_test_namespace
    ):
        """Test operator restart and recovery of schedules."""
        namespace = concurrency_test_namespace
        custom_api = client.CustomObjectsApi()
        batch_v1 = client.BatchV1Api()
        apps_v1 = client.AppsV1Api()

        # Create Repository
        repo_manifest = {
            "apiVersion": "ansible.cloud37.dev/v1alpha1",
            "kind": "Repository",
            "metadata": {"name": "test-repo", "namespace": namespace},
            "spec": {"url": "https://github.com/example/test-repo.git", "branch": "main"},
        }

        custom_api.create_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=namespace,
            plural="repositories",
            body=repo_manifest,
        )

        time.sleep(3)

        # Create Playbook
        playbook_manifest = {
            "apiVersion": "ansible.cloud37.dev/v1alpha1",
            "kind": "Playbook",
            "metadata": {"name": "test-playbook", "namespace": namespace},
            "spec": {
                "repositoryRef": {"name": "test-repo"},
                "playbookPath": "playbooks/test.yml",
                "inventoryPath": "inventory/hosts",
            },
        }

        custom_api.create_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=namespace,
            plural="playbooks",
            body=playbook_manifest,
        )

        time.sleep(3)

        # Create multiple schedules
        schedules = [
            {"name": "schedule-1", "schedule": "*/5 * * * *", "policy": "Forbid"},
            {"name": "schedule-2", "schedule": "@daily-random", "policy": "Allow"},
            {"name": "schedule-3", "schedule": "*/10 * * * *", "policy": "Replace"},
        ]

        for schedule_config in schedules:
            schedule_manifest = {
                "apiVersion": "ansible.cloud37.dev/v1alpha1",
                "kind": "Schedule",
                "metadata": {"name": schedule_config["name"], "namespace": namespace},
                "spec": {
                    "playbookRef": {"name": "test-playbook"},
                    "schedule": schedule_config["schedule"],
                    "concurrencyPolicy": schedule_config["policy"],
                    "backoffLimit": 1,
                    "successfulJobsHistoryLimit": 1,
                    "failedJobsHistoryLimit": 1,
                    "ttlSecondsAfterFinished": 60,
                },
            }

            custom_api.create_namespaced_custom_object(
                group="ansible.cloud37.dev",
                version="v1alpha1",
                namespace=namespace,
                plural="schedules",
                body=schedule_manifest,
            )

        # Wait for initial processing
        time.sleep(10)

        # Verify initial CronJobs were created
        cronjobs_before = batch_v1.list_namespaced_cron_job(namespace=namespace)
        schedule_cronjobs_before = [
            cj
            for cj in cronjobs_before.items
            if cj.metadata.owner_references and cj.metadata.owner_references[0].kind == "Schedule"
        ]
        assert len(schedule_cronjobs_before) == 3

        # Restart the operator
        print("Restarting operator...")
        deployment = apps_v1.read_namespaced_deployment(
            name="ansible-operator", namespace="ansible-operator-system"
        )

        # Scale down to 0
        deployment.spec.replicas = 0
        apps_v1.patch_namespaced_deployment(
            name="ansible-operator",
            namespace="ansible-operator-system",
            body=deployment,
        )

        # Wait for scale down
        time.sleep(5)

        # Scale back up to 1
        deployment.spec.replicas = 1
        apps_v1.patch_namespaced_deployment(
            name="ansible-operator",
            namespace="ansible-operator-system",
            body=deployment,
        )

        # Wait for operator to be ready
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

        # Wait for recovery
        time.sleep(15)

        # Verify CronJobs still exist and are managed
        cronjobs_after = batch_v1.list_namespaced_cron_job(namespace=namespace)
        schedule_cronjobs_after = [
            cj
            for cj in cronjobs_after.items
            if cj.metadata.owner_references and cj.metadata.owner_references[0].kind == "Schedule"
        ]
        assert len(schedule_cronjobs_after) == 3

        # Verify Schedule statuses are still correct
        for schedule_config in schedules:
            schedule = custom_api.get_namespaced_custom_object(
                group="ansible.cloud37.dev",
                version="v1alpha1",
                namespace=namespace,
                plural="schedules",
                name=schedule_config["name"],
            )

            status = schedule.get("status", {})
            conditions = status.get("conditions", [])
            ready_condition = next((c for c in conditions if c["type"] == "Ready"), None)
            assert ready_condition is not None
            assert ready_condition["status"] == "True"

            # Verify computed schedule is still set
            if schedule_config["schedule"].startswith("@"):
                assert status.get("computedSchedule") is not None
                assert not status.get("computedSchedule").startswith("@")

    def test_concurrent_schedule_creation(
        self, concurrency_operator_deployed, concurrency_test_namespace
    ):
        """Test concurrent creation of multiple schedules."""
        namespace = concurrency_test_namespace
        custom_api = client.CustomObjectsApi()
        batch_v1 = client.BatchV1Api()

        # Create Repository
        repo_manifest = {
            "apiVersion": "ansible.cloud37.dev/v1alpha1",
            "kind": "Repository",
            "metadata": {"name": "test-repo", "namespace": namespace},
            "spec": {"url": "https://github.com/example/test-repo.git", "branch": "main"},
        }

        custom_api.create_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=namespace,
            plural="repositories",
            body=repo_manifest,
        )

        time.sleep(3)

        # Create Playbook
        playbook_manifest = {
            "apiVersion": "ansible.cloud37.dev/v1alpha1",
            "kind": "Playbook",
            "metadata": {"name": "test-playbook", "namespace": namespace},
            "spec": {
                "repositoryRef": {"name": "test-repo"},
                "playbookPath": "playbooks/test.yml",
                "inventoryPath": "inventory/hosts",
            },
        }

        custom_api.create_namespaced_custom_object(
            group="ansible.cloud37.dev",
            version="v1alpha1",
            namespace=namespace,
            plural="playbooks",
            body=playbook_manifest,
        )

        time.sleep(3)

        # Create many schedules concurrently
        schedules_to_create = []
        for i in range(20):
            schedule_name = f"concurrent-schedule-{i}"
            schedule_manifest = {
                "apiVersion": "ansible.cloud37.dev/v1alpha1",
                "kind": "Schedule",
                "metadata": {"name": schedule_name, "namespace": namespace},
                "spec": {
                    "playbookRef": {"name": "test-playbook"},
                    "schedule": f"*/{5 + i} * * * *",  # Different schedules
                    "concurrencyPolicy": "Forbid",
                    "backoffLimit": 1,
                    "successfulJobsHistoryLimit": 1,
                    "failedJobsHistoryLimit": 1,
                    "ttlSecondsAfterFinished": 60,
                },
            }
            schedules_to_create.append((schedule_name, schedule_manifest))

        # Create all schedules concurrently
        import threading
        import queue

        results: queue.Queue[Union[tuple[str, str], tuple[str, str, str]]] = queue.Queue()

        def create_schedule(name: str, manifest: dict):
            try:
                custom_api.create_namespaced_custom_object(
                    group="ansible.cloud37.dev",
                    version="v1alpha1",
                    namespace=namespace,
                    plural="schedules",
                    body=manifest,
                )
                results.put(("success", name))
            except Exception as e:
                results.put(("error", name, str(e)))

        # Start all threads
        threads = []
        for name, manifest in schedules_to_create:
            thread = threading.Thread(target=create_schedule, args=(name, manifest))
            thread.start()
            threads.append(thread)

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Collect results
        successes = []
        errors = []
        while not results.empty():
            result = results.get()
            if result[0] == "success":
                successes.append(result[1])
            else:
                # Error case has 3 elements: ("error", name, error_message)
                if len(result) >= 3:
                    errors.append((result[1], result[2]))
                else:
                    errors.append((result[1], "unknown error"))

        # Verify all schedules were created successfully
        assert len(successes) == 20
        assert len(errors) == 0

        # Wait for processing
        time.sleep(20)

        # Verify all CronJobs were created
        cronjobs = batch_v1.list_namespaced_cron_job(namespace=namespace)
        schedule_cronjobs = [
            cj
            for cj in cronjobs.items
            if cj.metadata.owner_references and cj.metadata.owner_references[0].kind == "Schedule"
        ]

        assert len(schedule_cronjobs) == 20

        # Verify all schedules have correct status
        for schedule_name in successes:
            schedule = custom_api.get_namespaced_custom_object(
                group="ansible.cloud37.dev",
                version="v1alpha1",
                namespace=namespace,
                plural="schedules",
                name=schedule_name,
            )

            status = schedule.get("status", {})
            conditions = status.get("conditions", [])
            ready_condition = next((c for c in conditions if c["type"] == "Ready"), None)
            assert ready_condition is not None
            assert ready_condition["status"] == "True"
