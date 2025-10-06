"""
Pytest configuration and fixtures for integration tests.
"""

import os
import subprocess
import tempfile
import time
from typing import Generator, Optional
import pytest
from kubernetes import client, config


@pytest.fixture(scope="session")
def kind_available():
    """Check if kind is available."""
    try:
        subprocess.run(["kind", "version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("kind not available")


@pytest.fixture(scope="session")
def helm_available():
    """Check if helm is available."""
    try:
        subprocess.run(["helm", "version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("helm not available")


@pytest.fixture(scope="session")
def docker_available():
    """Check if docker is available."""
    try:
        subprocess.run(["docker", "version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("docker not available")


def wait_for_deployment_ready(name: str, namespace: str, timeout: int = 300) -> bool:
    """Wait for a deployment to be ready."""
    apps_v1 = client.AppsV1Api()
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            deployment = apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
            if deployment.status.ready_replicas and deployment.status.ready_replicas >= 1:
                return True
        except client.exceptions.ApiException:
            pass
        time.sleep(2)

    return False


def wait_for_custom_resource_condition(
    group: str,
    version: str,
    namespace: str,
    plural: str,
    name: str,
    condition_type: str,
    timeout: int = 60,
) -> bool:
    """Wait for a custom resource to have a specific condition."""
    custom_api = client.CustomObjectsApi()
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            resource = custom_api.get_namespaced_custom_object(
                group=group, version=version, namespace=namespace, plural=plural, name=name
            )

            conditions = resource.get("status", {}).get("conditions", [])
            for condition in conditions:
                if condition.get("type") == condition_type and condition.get("status") == "True":
                    return True
        except client.exceptions.ApiException:
            pass
        time.sleep(2)

    return False


def create_test_secret(
    name: str, namespace: str, secret_type: str = "Opaque", data: Optional[dict] = None
) -> client.V1Secret:
    """Create a test secret."""
    if data is None:
        data = {"test-key": "dGVzdC12YWx1ZQ=="}  # base64 encoded "test-value"

    secret = client.V1Secret(
        metadata=client.V1ObjectMeta(name=name, namespace=namespace), type=secret_type, data=data
    )

    v1 = client.CoreV1Api()
    return v1.create_namespaced_secret(namespace=namespace, body=secret)


def create_test_configmap(
    name: str, namespace: str, data: Optional[dict] = None
) -> client.V1ConfigMap:
    """Create a test configmap."""
    if data is None:
        data = {"test-key": "test-value"}

    configmap = client.V1ConfigMap(
        metadata=client.V1ObjectMeta(name=name, namespace=namespace), data=data
    )

    v1 = client.CoreV1Api()
    return v1.create_namespaced_config_map(namespace=namespace, body=configmap)


def verify_pod_security_defaults(pod_spec: client.V1PodSpec) -> bool:
    """Verify that pod security defaults are enforced."""
    # Check pod security context
    if not pod_spec.security_context:
        return False

    security_context = pod_spec.security_context

    # Check required security context fields
    if (
        security_context.run_as_non_root is not True
        or security_context.run_as_user != 1000
        or security_context.run_as_group != 1000
    ):
        return False

    # Check container security context
    if not pod_spec.containers:
        return False

    container = pod_spec.containers[0]
    if not container.security_context:
        return False

    container_security = container.security_context

    # Check required container security fields
    if (
        container_security.allow_privilege_escalation is not False
        or container_security.read_only_root_filesystem is not True
        or not container_security.seccomp_profile
        or container_security.seccomp_profile.type != "RuntimeDefault"
        or not container_security.capabilities
        or container_security.capabilities.drop != ["ALL"]
    ):
        return False

    return True
