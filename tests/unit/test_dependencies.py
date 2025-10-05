"""Unit tests for cross-resource dependency management."""

from typing import Any
from unittest.mock import Mock, patch

import pytest

from ansible_operator.services.dependencies import DependencyService


class TestDependencyService:
    """Test dependency service functionality."""

    def test_index_repository_dependencies(self):
        """Test indexing Repository -> Playbook dependencies."""
        service = DependencyService()

        # Mock API response
        mock_playbooks = {
            "items": [
                {
                    "metadata": {"name": "playbook-1"},
                    "spec": {
                        "repositoryRef": {
                            "name": "repo-1",
                            "namespace": "test-ns",
                        }
                    },
                },
                {
                    "metadata": {"name": "playbook-2"},
                    "spec": {
                        "repositoryRef": {
                            "name": "repo-2",
                            "namespace": "test-ns",
                        }
                    },
                },
                {
                    "metadata": {"name": "playbook-3"},
                    "spec": {
                        "repositoryRef": {
                            "name": "repo-1",
                            "namespace": "test-ns",
                        }
                    },
                },
            ]
        }

        with patch("ansible_operator.services.dependencies.client.CustomObjectsApi") as mock_api:
            mock_api_instance = Mock()
            mock_api.return_value = mock_api_instance
            mock_api_instance.list_namespaced_custom_object.return_value = mock_playbooks

            service.index_repository_dependencies("test-ns", "repo-1")

        # Verify dependencies are indexed correctly
        dependent_playbooks = service.get_dependent_playbooks("test-ns", "repo-1")
        assert len(dependent_playbooks) == 2
        assert "playbook-1" in dependent_playbooks
        assert "playbook-3" in dependent_playbooks
        assert "playbook-2" not in dependent_playbooks

    def test_index_playbook_dependencies(self):
        """Test indexing Playbook -> Schedule dependencies."""
        service = DependencyService()

        # Mock API response
        mock_schedules = {
            "items": [
                {
                    "metadata": {"name": "schedule-1"},
                    "spec": {
                        "playbookRef": {
                            "name": "playbook-1",
                            "namespace": "test-ns",
                        }
                    },
                },
                {
                    "metadata": {"name": "schedule-2"},
                    "spec": {
                        "playbookRef": {
                            "name": "playbook-2",
                            "namespace": "test-ns",
                        }
                    },
                },
                {
                    "metadata": {"name": "schedule-3"},
                    "spec": {
                        "playbookRef": {
                            "name": "playbook-1",
                            "namespace": "test-ns",
                        }
                    },
                },
            ]
        }

        with patch("ansible_operator.services.dependencies.client.CustomObjectsApi") as mock_api:
            mock_api_instance = Mock()
            mock_api.return_value = mock_api_instance
            mock_api_instance.list_namespaced_custom_object.return_value = mock_schedules

            service.index_playbook_dependencies("test-ns", "playbook-1")

        # Verify dependencies are indexed correctly
        dependent_schedules = service.get_dependent_schedules("test-ns", "playbook-1")
        assert len(dependent_schedules) == 2
        assert "schedule-1" in dependent_schedules
        assert "schedule-3" in dependent_schedules
        assert "schedule-2" not in dependent_schedules

    def test_index_repository_dependencies_cross_namespace(self):
        """Test that cross-namespace references are ignored."""
        service = DependencyService()

        # Mock API response with cross-namespace reference
        mock_playbooks = {
            "items": [
                {
                    "metadata": {"name": "playbook-1"},
                    "spec": {
                        "repositoryRef": {
                            "name": "repo-1",
                            "namespace": "test-ns",
                        }
                    },
                },
                {
                    "metadata": {"name": "playbook-2"},
                    "spec": {
                        "repositoryRef": {
                            "name": "repo-1",
                            "namespace": "other-ns",  # Different namespace
                        }
                    },
                },
            ]
        }

        with patch("ansible_operator.services.dependencies.client.CustomObjectsApi") as mock_api:
            mock_api_instance = Mock()
            mock_api.return_value = mock_api_instance
            mock_api_instance.list_namespaced_custom_object.return_value = mock_playbooks

            service.index_repository_dependencies("test-ns", "repo-1")

        # Verify only same-namespace dependencies are indexed
        dependent_playbooks = service.get_dependent_playbooks("test-ns", "repo-1")
        assert len(dependent_playbooks) == 1
        assert "playbook-1" in dependent_playbooks
        assert "playbook-2" not in dependent_playbooks

    def test_index_repository_dependencies_api_exception(self):
        """Test that API exceptions are handled gracefully."""
        service = DependencyService()

        with patch("ansible_operator.services.dependencies.client.CustomObjectsApi") as mock_api:
            mock_api_instance = Mock()
            mock_api.return_value = mock_api_instance
            mock_api_instance.list_namespaced_custom_object.side_effect = Exception("API Error")

            # Should not raise exception
            service.index_repository_dependencies("test-ns", "repo-1")

        # Verify index is cleared on failure
        dependent_playbooks = service.get_dependent_playbooks("test-ns", "repo-1")
        assert len(dependent_playbooks) == 0

    @patch("ansible_operator.services.dependencies.client.CustomObjectsApi")
    def test_requeue_dependent_playbooks(self, mock_custom_api):
        """Test triggering reconciliation of dependent Playbooks."""
        service = DependencyService()
        mock_api_instance = Mock()
        mock_custom_api.return_value = mock_api_instance

        # Set up dependencies
        service._repo_to_playbooks["test-ns"] = {"repo-1": ["playbook-1", "playbook-2"]}

        service.requeue_dependent_playbooks("test-ns", "repo-1")

        # Verify API calls
        assert mock_api_instance.patch_namespaced_custom_object.call_count == 2

        # Check patch arguments
        call_args_list = mock_api_instance.patch_namespaced_custom_object.call_args_list
        patched_playbooks = [call[1]["name"] for call in call_args_list]
        assert "playbook-1" in patched_playbooks
        assert "playbook-2" in patched_playbooks

        # Check patch parameters
        for call in call_args_list:
            assert call[1]["namespace"] == "test-ns"
            assert call[1]["plural"] == "playbooks"
            assert (
                "ansible.cloud37.dev/trigger-reconcile"
                in call[1]["body"]["metadata"]["annotations"]
            )

    @patch("ansible_operator.services.dependencies.client.CustomObjectsApi")
    def test_requeue_dependent_schedules(self, mock_custom_api):
        """Test triggering reconciliation of dependent Schedules."""
        service = DependencyService()
        mock_api_instance = Mock()
        mock_custom_api.return_value = mock_api_instance

        # Set up dependencies
        service._playbook_to_schedules["test-ns"] = {"playbook-1": ["schedule-1", "schedule-2"]}

        service.requeue_dependent_schedules("test-ns", "playbook-1")

        # Verify API calls
        assert mock_api_instance.patch_namespaced_custom_object.call_count == 2

        # Check patch arguments
        call_args_list = mock_api_instance.patch_namespaced_custom_object.call_args_list
        patched_schedules = [call[1]["name"] for call in call_args_list]
        assert "schedule-1" in patched_schedules
        assert "schedule-2" in patched_schedules

        # Check patch parameters
        for call in call_args_list:
            assert call[1]["namespace"] == "test-ns"
            assert call[1]["plural"] == "schedules"
            assert (
                "ansible.cloud37.dev/trigger-reconcile"
                in call[1]["body"]["metadata"]["annotations"]
            )

    @patch("ansible_operator.services.dependencies.client.CustomObjectsApi")
    def test_requeue_rate_limiting(self, mock_custom_api):
        """Test that requeue operations are rate-limited."""
        service = DependencyService()
        mock_api_instance = Mock()
        mock_custom_api.return_value = mock_api_instance

        # Set up dependencies
        service._repo_to_playbooks["test-ns"] = {"repo-1": ["playbook-1"]}

        # First requeue should work
        service.requeue_dependent_playbooks("test-ns", "repo-1")
        assert mock_api_instance.patch_namespaced_custom_object.call_count == 1

        # Second requeue within cooldown period should be ignored
        service.requeue_dependent_playbooks("test-ns", "repo-1")
        assert (
            mock_api_instance.patch_namespaced_custom_object.call_count == 1
        )  # No additional calls

    @patch("ansible_operator.services.dependencies.client.CustomObjectsApi")
    def test_requeue_handles_exceptions(self, mock_custom_api):
        """Test that requeue exceptions are handled gracefully."""
        service = DependencyService()
        mock_api_instance = Mock()
        mock_custom_api.return_value = mock_api_instance

        # Set up dependencies
        service._repo_to_playbooks["test-ns"] = {"repo-1": ["playbook-1", "playbook-2"]}

        # Make API raise exception for one call
        mock_api_instance.patch_namespaced_custom_object.side_effect = [
            Exception("API failed"),
            None,
        ]

        # Should not raise exception
        service.requeue_dependent_playbooks("test-ns", "repo-1")

        # Should still attempt both patches
        assert mock_api_instance.patch_namespaced_custom_object.call_count == 2

    def test_cleanup_dependencies_repository(self):
        """Test cleanup of Repository dependencies."""
        service = DependencyService()

        # Set up dependencies
        service._repo_to_playbooks["test-ns"] = {"repo-1": ["playbook-1", "playbook-2"]}

        service.cleanup_dependencies("test-ns", "repository", "repo-1")

        # Verify dependencies are cleaned up
        dependent_playbooks = service.get_dependent_playbooks("test-ns", "repo-1")
        assert len(dependent_playbooks) == 0

    def test_cleanup_dependencies_playbook(self):
        """Test cleanup of Playbook dependencies."""
        service = DependencyService()

        # Set up dependencies
        service._playbook_to_schedules["test-ns"] = {"playbook-1": ["schedule-1", "schedule-2"]}
        service._repo_to_playbooks["test-ns"] = {"repo-1": ["playbook-1", "playbook-2"]}

        service.cleanup_dependencies("test-ns", "playbook", "playbook-1")

        # Verify Playbook -> Schedule dependencies are cleaned up
        dependent_schedules = service.get_dependent_schedules("test-ns", "playbook-1")
        assert len(dependent_schedules) == 0

        # Verify Playbook is removed from Repository dependencies
        dependent_playbooks = service.get_dependent_playbooks("test-ns", "repo-1")
        assert "playbook-1" not in dependent_playbooks
        assert "playbook-2" in dependent_playbooks

    def test_get_dependent_playbooks_empty(self):
        """Test getting dependent Playbooks when none exist."""
        service = DependencyService()

        dependent_playbooks = service.get_dependent_playbooks("test-ns", "repo-1")
        assert len(dependent_playbooks) == 0

    def test_get_dependent_schedules_empty(self):
        """Test getting dependent Schedules when none exist."""
        service = DependencyService()

        dependent_schedules = service.get_dependent_schedules("test-ns", "playbook-1")
        assert len(dependent_schedules) == 0

    def test_dependency_service_singleton(self):
        """Test that dependency service is a singleton."""
        from ansible_operator.services.dependencies import dependency_service

        # Import again to verify it's the same instance
        from ansible_operator.services.dependencies import dependency_service as service2

        assert dependency_service is service2
