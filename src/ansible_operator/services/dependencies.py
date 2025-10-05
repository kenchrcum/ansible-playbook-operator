"""Cross-resource dependency management service."""

from __future__ import annotations

import time
from typing import Any

from kubernetes import client

from ..constants import API_GROUP, API_GROUP_VERSION


class DependencyService:
    """Service for managing cross-resource dependencies and triggers."""

    def __init__(self) -> None:
        # In-memory dependency indices
        # Format: {namespace: {resource_name: [dependent_resource_names]}}
        self._repo_to_playbooks: dict[str, dict[str, list[str]]] = {}
        self._playbook_to_schedules: dict[str, dict[str, list[str]]] = {}

        # Rate limiting tracking
        # Format: {resource_key: last_requeue_time}
        self._last_requeue_times: dict[str, float] = {}
        self._requeue_cooldown = 5.0  # seconds

    def index_repository_dependencies(self, namespace: str, repo_name: str) -> None:
        """Index Repository -> Playbook dependencies by scanning all Playbooks."""
        try:
            api = client.CustomObjectsApi()
            playbooks = api.list_namespaced_custom_object(
                group=API_GROUP,
                version="v1alpha1",
                namespace=namespace,
                plural="playbooks",
            )

            dependent_playbooks = []
            for playbook in playbooks.get("items", []):
                playbook_name = playbook["metadata"]["name"]
                spec = playbook.get("spec", {})
                repo_ref = spec.get("repositoryRef", {})

                if repo_ref.get("name") == repo_name:
                    # Handle cross-namespace references
                    repo_namespace = repo_ref.get("namespace", namespace)
                    if repo_namespace == namespace:
                        dependent_playbooks.append(playbook_name)

            # Update index
            if namespace not in self._repo_to_playbooks:
                self._repo_to_playbooks[namespace] = {}
            self._repo_to_playbooks[namespace][repo_name] = dependent_playbooks

        except Exception:
            # If indexing fails, clear the index to avoid stale data
            if namespace in self._repo_to_playbooks:
                self._repo_to_playbooks[namespace].pop(repo_name, None)

    def index_playbook_dependencies(self, namespace: str, playbook_name: str) -> None:
        """Index Playbook -> Schedule dependencies by scanning all Schedules."""
        try:
            api = client.CustomObjectsApi()
            schedules = api.list_namespaced_custom_object(
                group=API_GROUP,
                version="v1alpha1",
                namespace=namespace,
                plural="schedules",
            )

            dependent_schedules = []
            for schedule in schedules.get("items", []):
                schedule_name = schedule["metadata"]["name"]
                spec = schedule.get("spec", {})
                playbook_ref = spec.get("playbookRef", {})

                if playbook_ref.get("name") == playbook_name:
                    # Handle cross-namespace references
                    playbook_namespace = playbook_ref.get("namespace", namespace)
                    if playbook_namespace == namespace:
                        dependent_schedules.append(schedule_name)

            # Update index
            if namespace not in self._playbook_to_schedules:
                self._playbook_to_schedules[namespace] = {}
            self._playbook_to_schedules[namespace][playbook_name] = dependent_schedules

        except Exception:
            # If indexing fails, clear the index to avoid stale data
            if namespace in self._playbook_to_schedules:
                self._playbook_to_schedules[namespace].pop(playbook_name, None)

    def requeue_dependent_playbooks(self, namespace: str, repo_name: str) -> None:
        """Trigger reconciliation of all Playbooks that depend on the given Repository."""
        resource_key = f"repo:{namespace}:{repo_name}"
        current_time = time.time()

        # Check rate limiting
        last_requeue = self._last_requeue_times.get(resource_key, 0)
        if current_time - last_requeue < self._requeue_cooldown:
            return

        # Get dependent playbooks
        dependent_playbooks = self._repo_to_playbooks.get(namespace, {}).get(repo_name, [])

        if dependent_playbooks:
            # Trigger reconciliation by adding annotation to dependent playbooks
            api = client.CustomObjectsApi()
            for playbook_name in dependent_playbooks:
                try:
                    # Add annotation to trigger reconciliation
                    patch_body = {
                        "metadata": {
                            "annotations": {
                                "ansible.cloud37.dev/trigger-reconcile": str(current_time),
                            }
                        }
                    }
                    api.patch_namespaced_custom_object(
                        group=API_GROUP,
                        version="v1alpha1",
                        namespace=namespace,
                        plural="playbooks",
                        name=playbook_name,
                        body=patch_body,
                        field_manager="ansible-operator",
                    )
                except Exception:
                    # Trigger failures are non-critical
                    pass

            # Update rate limiting
            self._last_requeue_times[resource_key] = current_time

    def requeue_dependent_schedules(self, namespace: str, playbook_name: str) -> None:
        """Trigger reconciliation of all Schedules that depend on the given Playbook."""
        resource_key = f"playbook:{namespace}:{playbook_name}"
        current_time = time.time()

        # Check rate limiting
        last_requeue = self._last_requeue_times.get(resource_key, 0)
        if current_time - last_requeue < self._requeue_cooldown:
            return

        # Get dependent schedules
        dependent_schedules = self._playbook_to_schedules.get(namespace, {}).get(playbook_name, [])

        if dependent_schedules:
            # Trigger reconciliation by adding annotation to dependent schedules
            api = client.CustomObjectsApi()
            for schedule_name in dependent_schedules:
                try:
                    # Add annotation to trigger reconciliation
                    patch_body = {
                        "metadata": {
                            "annotations": {
                                "ansible.cloud37.dev/trigger-reconcile": str(current_time),
                            }
                        }
                    }
                    api.patch_namespaced_custom_object(
                        group=API_GROUP,
                        version="v1alpha1",
                        namespace=namespace,
                        plural="schedules",
                        name=schedule_name,
                        body=patch_body,
                        field_manager="ansible-operator",
                    )
                except Exception:
                    # Trigger failures are non-critical
                    pass

            # Update rate limiting
            self._last_requeue_times[resource_key] = current_time

    def cleanup_dependencies(self, namespace: str, resource_type: str, resource_name: str) -> None:
        """Clean up dependencies when a resource is deleted."""
        if resource_type == "repository":
            # Remove from repository index
            if namespace in self._repo_to_playbooks:
                self._repo_to_playbooks[namespace].pop(resource_name, None)
        elif resource_type == "playbook":
            # Remove from playbook index
            if namespace in self._playbook_to_schedules:
                self._playbook_to_schedules[namespace].pop(resource_name, None)

            # Also remove from repository index if this playbook was dependent
            if namespace in self._repo_to_playbooks:
                for repo_name, playbooks in self._repo_to_playbooks[namespace].items():
                    if resource_name in playbooks:
                        playbooks.remove(resource_name)

    def get_dependent_playbooks(self, namespace: str, repo_name: str) -> list[str]:
        """Get list of Playbooks that depend on the given Repository."""
        return self._repo_to_playbooks.get(namespace, {}).get(repo_name, [])

    def get_dependent_schedules(self, namespace: str, playbook_name: str) -> list[str]:
        """Get list of Schedules that depend on the given Playbook."""
        return self._playbook_to_schedules.get(namespace, {}).get(playbook_name, [])


# Global instance
dependency_service = DependencyService()
