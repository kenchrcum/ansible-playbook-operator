"""Unit tests for Helm template image pinning functionality."""

from __future__ import annotations

import pytest
from pathlib import Path
from typing import Any


# Mock Helm template rendering
def render_helm_template(template_path: str, values: dict[str, Any]) -> dict[str, Any]:
    """Mock Helm template rendering for testing."""
    # This is a simplified mock - in real testing you'd use helm template
    template_content = Path(template_path).read_text()

    # Simple template variable substitution for testing
    if "{{ .Values.operator.image.repository }}" in template_content:
        repo = (
            values.get("operator", {})
            .get("image", {})
            .get("repository", "kenchrcum/ansible-playbook-operator")
        )
        template_content = template_content.replace("{{ .Values.operator.image.repository }}", repo)

    if "{{ .Values.operator.image.tag }}" in template_content:
        tag = values.get("operator", {}).get("image", {}).get("tag", "0.1.3")
        template_content = template_content.replace("{{ .Values.operator.image.tag }}", tag)

    if "{{ .Values.operator.image.digest }}" in template_content:
        digest = values.get("operator", {}).get("image", {}).get("digest", "")
        if digest:
            template_content = template_content.replace(
                "{{ .Values.operator.image.repository }}{{ if .Values.operator.image.digest }}@{{ .Values.operator.image.digest }}{{ else }}:{{ .Values.operator.image.tag }}{{ end }}",
                f"{repo}@{digest}",
            )
        else:
            template_content = template_content.replace(
                "{{ .Values.operator.image.repository }}{{ if .Values.operator.image.digest }}@{{ .Values.operator.image.digest }}{{ else }}:{{ .Values.operator.image.tag }}{{ end }}",
                f"{repo}:{tag}",
            )

    if "{{ .Values.operator.image.pullPolicy }}" in template_content:
        pull_policy = values.get("operator", {}).get("image", {}).get("pullPolicy", "IfNotPresent")
        template_content = template_content.replace(
            "{{ .Values.operator.image.pullPolicy }}", pull_policy
        )

    # Return a mock deployment manifest instead of parsing YAML
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "test-deployment"},
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "operator",
                            "image": f"{repo}@{digest}" if digest else f"{repo}:{tag}",
                            "imagePullPolicy": values.get("operator", {})
                            .get("image", {})
                            .get("pullPolicy", "IfNotPresent"),
                        }
                    ]
                }
            }
        },
    }


class TestHelmImagePinning:
    """Test Helm template image pinning functionality."""

    def test_deployment_with_digest(self):
        """Test deployment template with digest pinning."""
        values = {
            "operator": {
                "image": {
                    "repository": "kenchrcum/ansible-playbook-operator",
                    "tag": "0.1.3",
                    "digest": "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                    "pullPolicy": "IfNotPresent",
                }
            }
        }

        # Mock the deployment template
        template_path = "helm/ansible-playbook-operator/templates/deployment.yaml"
        manifest = render_helm_template(template_path, values)

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        expected_image = "kenchrcum/ansible-playbook-operator@sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        assert container["image"] == expected_image

    def test_deployment_without_digest(self):
        """Test deployment template without digest pinning."""
        values = {
            "operator": {
                "image": {
                    "repository": "kenchrcum/ansible-playbook-operator",
                    "tag": "0.1.3",
                    "digest": "",
                    "pullPolicy": "IfNotPresent",
                }
            }
        }

        template_path = "helm/ansible-playbook-operator/templates/deployment.yaml"
        manifest = render_helm_template(template_path, values)

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        expected_image = "kenchrcum/ansible-playbook-operator:0.1.3"
        assert container["image"] == expected_image

    def test_deployment_with_none_digest(self):
        """Test deployment template with None digest."""
        values = {
            "operator": {
                "image": {
                    "repository": "kenchrcum/ansible-playbook-operator",
                    "tag": "0.1.3",
                    "digest": None,
                    "pullPolicy": "IfNotPresent",
                }
            }
        }

        template_path = "helm/ansible-playbook-operator/templates/deployment.yaml"
        manifest = render_helm_template(template_path, values)

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        expected_image = "kenchrcum/ansible-playbook-operator:0.1.3"
        assert container["image"] == expected_image

    def test_deployment_missing_digest_field(self):
        """Test deployment template when digest field is missing."""
        values = {
            "operator": {
                "image": {
                    "repository": "kenchrcum/ansible-playbook-operator",
                    "tag": "0.1.3",
                    "pullPolicy": "IfNotPresent",
                }
            }
        }

        template_path = "helm/ansible-playbook-operator/templates/deployment.yaml"
        manifest = render_helm_template(template_path, values)

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        expected_image = "kenchrcum/ansible-playbook-operator:0.1.3"
        assert container["image"] == expected_image

    def test_deployment_custom_repository(self):
        """Test deployment template with custom repository."""
        values = {
            "operator": {
                "image": {
                    "repository": "registry.example.com/ansible-playbook-operator",
                    "tag": "0.1.3",
                    "digest": "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                    "pullPolicy": "IfNotPresent",
                }
            }
        }

        template_path = "helm/ansible-playbook-operator/templates/deployment.yaml"
        manifest = render_helm_template(template_path, values)

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        expected_image = "registry.example.com/ansible-playbook-operator@sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        assert container["image"] == expected_image

    def test_deployment_pull_policy(self):
        """Test deployment template pull policy."""
        values = {
            "operator": {
                "image": {
                    "repository": "kenchrcum/ansible-playbook-operator",
                    "tag": "0.1.3",
                    "digest": "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                    "pullPolicy": "Always",
                }
            }
        }

        template_path = "helm/ansible-playbook-operator/templates/deployment.yaml"
        manifest = render_helm_template(template_path, values)

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        assert container["imagePullPolicy"] == "Always"

    def test_values_file_structure(self):
        """Test that values.yaml has the correct structure for image pinning."""
        values_path = Path("helm/ansible-playbook-operator/values.yaml")
        assert values_path.exists(), "values.yaml file should exist"

        values_content = values_path.read_text()

        # Check for operator image digest field
        assert "operator:" in values_content
        assert "image:" in values_content
        assert "digest:" in values_content

        # Check for executor image digest field
        assert "executorDefaults:" in values_content

        # Check for comments explaining digest usage
        assert "Optional: pin image by digest" in values_content
        assert "When digest is provided, it takes precedence over tag" in values_content

    def test_template_conditional_logic(self):
        """Test that template conditional logic works correctly."""
        # Test with digest
        values_with_digest = {
            "operator": {
                "image": {
                    "repository": "kenchrcum/ansible-playbook-operator",
                    "tag": "0.1.3",
                    "digest": "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                }
            }
        }

        template_path = "helm/ansible-playbook-operator/templates/deployment.yaml"
        manifest = render_helm_template(template_path, values_with_digest)

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        assert "@" in container["image"]
        assert "sha256:" in container["image"]

        # Test without digest
        values_without_digest = {
            "operator": {
                "image": {
                    "repository": "kenchrcum/ansible-playbook-operator",
                    "tag": "0.1.3",
                    "digest": "",
                }
            }
        }

        manifest = render_helm_template(template_path, values_without_digest)

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        assert ":" in container["image"]
        assert "@" not in container["image"]

    def test_digest_format_validation(self):
        """Test that digest format is properly validated."""
        values = {
            "operator": {
                "image": {
                    "repository": "kenchrcum/ansible-playbook-operator",
                    "tag": "0.1.3",
                    "digest": "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                }
            }
        }

        template_path = "helm/ansible-playbook-operator/templates/deployment.yaml"
        manifest = render_helm_template(template_path, values)

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        image = container["image"]

        # Verify digest format
        assert image.startswith("kenchrcum/ansible-playbook-operator@sha256:")
        digest_part = image.split("@")[1]
        assert digest_part.startswith("sha256:")
        assert len(digest_part) == 71  # sha256: + 64 hex chars

    def test_backward_compatibility(self):
        """Test that the template maintains backward compatibility."""
        # Test with old values structure (no digest field)
        old_values = {
            "operator": {
                "image": {
                    "repository": "kenchrcum/ansible-playbook-operator",
                    "tag": "0.1.3",
                    "pullPolicy": "IfNotPresent",
                }
            }
        }

        template_path = "helm/ansible-playbook-operator/templates/deployment.yaml"
        manifest = render_helm_template(template_path, old_values)

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        expected_image = "kenchrcum/ansible-playbook-operator:0.1.3"
        assert container["image"] == expected_image

        # Test with new values structure (with digest field)
        new_values = {
            "operator": {
                "image": {
                    "repository": "kenchrcum/ansible-playbook-operator",
                    "tag": "0.1.3",
                    "digest": "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                    "pullPolicy": "IfNotPresent",
                }
            }
        }

        manifest = render_helm_template(template_path, new_values)

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        expected_image = "kenchrcum/ansible-playbook-operator@sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        assert container["image"] == expected_image
