"""Unit tests for dependency index rebuilding after operator restart."""

from unittest.mock import Mock, patch

import pytest

from ansible_operator.services.dependencies import DependencyService


class TestDependencyRebuild:
    """Test dependency index rebuilding functionality."""

    def test_rebuild_all_indices_empty_namespaces(self):
        """Test rebuilding indices with empty namespace list."""
        service = DependencyService()

        # Should not raise any exceptions
        service.rebuild_all_indices([])

        # Indices should remain empty
        assert service._repo_to_playbooks == {}
        assert service._playbook_to_schedules == {}

    def test_rebuild_all_indices_with_mock_api(self):
        """Test rebuilding indices with mocked API responses."""
        service = DependencyService()

        # Mock API responses - the service lists repositories first, then playbooks
        mock_api = Mock()
        mock_api.list_namespaced_custom_object.side_effect = [
            # Repository response (used to trigger indexing for each repo)
            {
                "items": [
                    {
                        "metadata": {"name": "repo1"},
                        "spec": {"url": "https://github.com/test/repo1.git"},
                    },
                    {
                        "metadata": {"name": "repo2"},
                        "spec": {"url": "https://github.com/test/repo2.git"},
                    },
                ]
            },
            # Playbook response (scanned for repo1 dependencies)
            {
                "items": [
                    {
                        "metadata": {"name": "playbook1"},
                        "spec": {"repositoryRef": {"name": "repo1"}, "playbookPath": "test.yml"},
                    },
                    {
                        "metadata": {"name": "playbook2"},
                        "spec": {"repositoryRef": {"name": "repo2"}, "playbookPath": "test.yml"},
                    },
                ]
            },
            # Playbook response (scanned for repo2 dependencies)
            {
                "items": [
                    {
                        "metadata": {"name": "playbook1"},
                        "spec": {"repositoryRef": {"name": "repo1"}, "playbookPath": "test.yml"},
                    },
                    {
                        "metadata": {"name": "playbook2"},
                        "spec": {"repositoryRef": {"name": "repo2"}, "playbookPath": "test.yml"},
                    },
                ]
            },
            # Playbook response (used to trigger indexing for each playbook)
            {
                "items": [
                    {
                        "metadata": {"name": "playbook1"},
                        "spec": {"repositoryRef": {"name": "repo1"}, "playbookPath": "test.yml"},
                    },
                    {
                        "metadata": {"name": "playbook2"},
                        "spec": {"repositoryRef": {"name": "repo2"}, "playbookPath": "test.yml"},
                    },
                ]
            },
            # Schedule response (scanned for playbook1 dependencies)
            {
                "items": [
                    {
                        "metadata": {"name": "schedule1"},
                        "spec": {"playbookRef": {"name": "playbook1"}, "schedule": "0 0 * * *"},
                    }
                ]
            },
            # Schedule response (scanned for playbook2 dependencies)
            {
                "items": [
                    {
                        "metadata": {"name": "schedule1"},
                        "spec": {"playbookRef": {"name": "playbook1"}, "schedule": "0 0 * * *"},
                    }
                ]
            },
        ]

        with patch(
            "ansible_operator.services.dependencies.client.CustomObjectsApi", return_value=mock_api
        ):
            service.rebuild_all_indices(["test-namespace"])

        # Verify indices were built
        assert "test-namespace" in service._repo_to_playbooks
        assert "repo1" in service._repo_to_playbooks["test-namespace"]
        assert "repo2" in service._repo_to_playbooks["test-namespace"]
        assert "playbook1" in service._repo_to_playbooks["test-namespace"]["repo1"]
        assert "playbook2" in service._repo_to_playbooks["test-namespace"]["repo2"]

        # Verify playbook -> schedule index
        assert "test-namespace" in service._playbook_to_schedules
        assert "playbook1" in service._playbook_to_schedules["test-namespace"]
        assert "schedule1" in service._playbook_to_schedules["test-namespace"]["playbook1"]

    def test_rebuild_all_indices_api_failure(self):
        """Test rebuilding indices when API calls fail."""
        service = DependencyService()

        # Mock API to raise exception
        mock_api = Mock()
        mock_api.list_namespaced_custom_object.side_effect = Exception("API Error")

        with patch(
            "ansible_operator.services.dependencies.client.CustomObjectsApi", return_value=mock_api
        ):
            # Should not raise exception
            service.rebuild_all_indices(["test-namespace"])

        # Indices should remain empty due to failure
        assert service._repo_to_playbooks == {}
        assert service._playbook_to_schedules == {}

    def test_rebuild_all_indices_partial_failure(self):
        """Test rebuilding indices when some namespaces fail."""
        service = DependencyService()

        # Mock API to succeed for first namespace, fail for second
        mock_api = Mock()
        mock_api.list_namespaced_custom_object.side_effect = [
            # Success for first namespace
            {
                "items": [
                    {
                        "metadata": {"name": "repo1"},
                        "spec": {"url": "https://github.com/test/repo1.git"},
                    }
                ]
            },
            {
                "items": [
                    {
                        "metadata": {"name": "playbook1"},
                        "spec": {"repositoryRef": {"name": "repo1"}, "playbookPath": "test.yml"},
                    }
                ]
            },
            # Failure for second namespace
            Exception("API Error"),
        ]

        with patch(
            "ansible_operator.services.dependencies.client.CustomObjectsApi", return_value=mock_api
        ):
            service.rebuild_all_indices(["namespace1", "namespace2"])

        # First namespace should be indexed, second should be empty
        assert "namespace1" in service._repo_to_playbooks
        assert "repo1" in service._repo_to_playbooks["namespace1"]
        assert "namespace2" not in service._repo_to_playbooks

    def test_rebuild_all_indices_multiple_namespaces(self):
        """Test rebuilding indices for multiple namespaces."""
        service = DependencyService()

        # Mock API responses for multiple namespaces
        mock_api = Mock()
        mock_api.list_namespaced_custom_object.side_effect = [
            # Namespace 1 repositories
            {
                "items": [
                    {
                        "metadata": {"name": "repo1"},
                        "spec": {"url": "https://github.com/test/repo1.git"},
                    }
                ]
            },
            # Namespace 1 playbooks (scanned for repo1 dependencies)
            {
                "items": [
                    {
                        "metadata": {"name": "playbook1"},
                        "spec": {"repositoryRef": {"name": "repo1"}, "playbookPath": "test.yml"},
                    }
                ]
            },
            # Namespace 1 playbooks (used to trigger indexing for each playbook)
            {
                "items": [
                    {
                        "metadata": {"name": "playbook1"},
                        "spec": {"repositoryRef": {"name": "repo1"}, "playbookPath": "test.yml"},
                    }
                ]
            },
            # Namespace 1 schedules (scanned for playbook1 dependencies)
            {
                "items": [
                    {
                        "metadata": {"name": "schedule1"},
                        "spec": {"playbookRef": {"name": "playbook1"}, "schedule": "0 0 * * *"},
                    }
                ]
            },
            # Namespace 2 repositories
            {
                "items": [
                    {
                        "metadata": {"name": "repo2"},
                        "spec": {"url": "https://github.com/test/repo2.git"},
                    }
                ]
            },
            # Namespace 2 playbooks (scanned for repo2 dependencies)
            {
                "items": [
                    {
                        "metadata": {"name": "playbook2"},
                        "spec": {"repositoryRef": {"name": "repo2"}, "playbookPath": "test.yml"},
                    }
                ]
            },
            # Namespace 2 playbooks (used to trigger indexing for each playbook)
            {
                "items": [
                    {
                        "metadata": {"name": "playbook2"},
                        "spec": {"repositoryRef": {"name": "repo2"}, "playbookPath": "test.yml"},
                    }
                ]
            },
            # Namespace 2 schedules (scanned for playbook2 dependencies)
            {
                "items": [
                    {
                        "metadata": {"name": "schedule2"},
                        "spec": {"playbookRef": {"name": "playbook2"}, "schedule": "0 0 * * *"},
                    }
                ]
            },
        ]

        with patch(
            "ansible_operator.services.dependencies.client.CustomObjectsApi", return_value=mock_api
        ):
            service.rebuild_all_indices(["namespace1", "namespace2"])

        # Both namespaces should be indexed
        assert "namespace1" in service._repo_to_playbooks
        assert "namespace2" in service._repo_to_playbooks
        assert "repo1" in service._repo_to_playbooks["namespace1"]
        assert "repo2" in service._repo_to_playbooks["namespace2"]
        assert "playbook1" in service._repo_to_playbooks["namespace1"]["repo1"]
        assert "playbook2" in service._repo_to_playbooks["namespace2"]["repo2"]

        # Verify playbook -> schedule indices
        assert "namespace1" in service._playbook_to_schedules
        assert "namespace2" in service._playbook_to_schedules
        assert "playbook1" in service._playbook_to_schedules["namespace1"]
        assert "playbook2" in service._playbook_to_schedules["namespace2"]
        assert "schedule1" in service._playbook_to_schedules["namespace1"]["playbook1"]
        assert "schedule2" in service._playbook_to_schedules["namespace2"]["playbook2"]
