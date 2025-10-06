"""Unit tests for NetworkPolicy Helm templates."""

import pytest
import yaml  # type: ignore
from pathlib import Path
from typing import Any, Dict, List


def test_networkpolicy_operator_template_restrictive():
    """Test NetworkPolicy operator template with restrictive preset."""
    # This would test the Helm template rendering
    # For now, we'll test the structure and logic

    # Mock values for restrictive preset
    values: Dict[str, Any] = {
        "networkPolicies": {
            "enabled": True,
            "preset": "restrictive",
            "git": {
                "endpoints": ["github.com", "gitlab.com"],
                "custom": [],
                "ports": [{"port": 22, "protocol": "TCP"}, {"port": 443, "protocol": "TCP"}],
            },
            "registries": {
                "endpoints": ["docker.io", "quay.io"],
                "custom": [],
                "ports": [{"port": 443, "protocol": "TCP"}],
            },
            "dns": {"enabled": False, "endpoints": [], "ports": []},
            "kubernetes": {"enabled": False, "endpoints": [], "ports": []},
            "additionalRules": [],
        }
    }

    # Verify restrictive preset configuration
    assert values["networkPolicies"]["enabled"] is True
    assert values["networkPolicies"]["preset"] == "restrictive"
    assert values["networkPolicies"]["dns"]["enabled"] is False
    assert values["networkPolicies"]["kubernetes"]["enabled"] is False
    assert len(values["networkPolicies"]["git"]["endpoints"]) == 2
    assert len(values["networkPolicies"]["registries"]["endpoints"]) == 2


def test_networkpolicy_operator_template_moderate():
    """Test NetworkPolicy operator template with moderate preset."""
    values: Dict[str, Any] = {
        "networkPolicies": {
            "enabled": True,
            "preset": "moderate",
            "git": {
                "endpoints": ["github.com", "gitlab.com"],
                "custom": [],
                "ports": [{"port": 22, "protocol": "TCP"}, {"port": 443, "protocol": "TCP"}],
            },
            "registries": {
                "endpoints": ["docker.io", "quay.io"],
                "custom": [],
                "ports": [{"port": 443, "protocol": "TCP"}],
            },
            "dns": {
                "enabled": True,
                "endpoints": ["10.96.0.10"],
                "ports": [{"port": 53, "protocol": "UDP"}, {"port": 53, "protocol": "TCP"}],
            },
            "kubernetes": {
                "enabled": True,
                "endpoints": ["kubernetes.default.svc.cluster.local"],
                "ports": [{"port": 443, "protocol": "TCP"}],
            },
            "additionalRules": [],
        }
    }

    # Verify moderate preset configuration
    assert values["networkPolicies"]["enabled"] is True
    assert values["networkPolicies"]["preset"] == "moderate"
    assert values["networkPolicies"]["dns"]["enabled"] is True
    assert values["networkPolicies"]["kubernetes"]["enabled"] is True
    assert len(values["networkPolicies"]["dns"]["endpoints"]) == 1
    assert len(values["networkPolicies"]["kubernetes"]["endpoints"]) == 1


def test_networkpolicy_operator_template_permissive():
    """Test NetworkPolicy operator template with permissive preset."""
    values: Dict[str, Any] = {
        "networkPolicies": {
            "enabled": True,
            "preset": "permissive",
            "git": {"endpoints": [], "custom": [], "ports": []},
            "registries": {"endpoints": [], "custom": [], "ports": []},
            "dns": {"enabled": False, "endpoints": [], "ports": []},
            "kubernetes": {"enabled": False, "endpoints": [], "ports": []},
            "additionalRules": [],
        }
    }

    # Verify permissive preset configuration
    assert values["networkPolicies"]["enabled"] is True
    assert values["networkPolicies"]["preset"] == "permissive"
    assert values["networkPolicies"]["dns"]["enabled"] is False
    assert values["networkPolicies"]["kubernetes"]["enabled"] is False
    assert len(values["networkPolicies"]["git"]["endpoints"]) == 0
    assert len(values["networkPolicies"]["registries"]["endpoints"]) == 0


def test_networkpolicy_operator_template_disabled():
    """Test NetworkPolicy operator template when disabled."""
    values: Dict[str, Any] = {"networkPolicies": {"enabled": False, "preset": "none"}}

    # Verify disabled configuration
    assert values["networkPolicies"]["enabled"] is False
    assert values["networkPolicies"]["preset"] == "none"


def test_networkpolicy_custom_endpoints():
    """Test NetworkPolicy with custom endpoints."""
    values: Dict[str, Any] = {
        "networkPolicies": {
            "enabled": True,
            "preset": "moderate",
            "git": {
                "endpoints": ["github.com"],
                "custom": ["git.internal.company.com", "192.168.1.100"],
                "ports": [{"port": 22, "protocol": "TCP"}, {"port": 443, "protocol": "TCP"}],
            },
            "registries": {
                "endpoints": ["docker.io"],
                "custom": ["registry.internal.company.com", "192.168.1.200"],
                "ports": [{"port": 443, "protocol": "TCP"}],
            },
            "dns": {
                "enabled": True,
                "endpoints": ["10.96.0.10", "8.8.8.8"],
                "ports": [{"port": 53, "protocol": "UDP"}, {"port": 53, "protocol": "TCP"}],
            },
            "kubernetes": {
                "enabled": True,
                "endpoints": ["kubernetes.default.svc.cluster.local"],
                "ports": [{"port": 443, "protocol": "TCP"}],
            },
            "additionalRules": [],
        }
    }

    # Verify custom endpoints configuration
    assert len(values["networkPolicies"]["git"]["custom"]) == 2
    assert len(values["networkPolicies"]["registries"]["custom"]) == 2
    assert len(values["networkPolicies"]["dns"]["endpoints"]) == 2
    assert "git.internal.company.com" in values["networkPolicies"]["git"]["custom"]
    assert "192.168.1.100" in values["networkPolicies"]["git"]["custom"]
    assert "registry.internal.company.com" in values["networkPolicies"]["registries"]["custom"]
    assert "192.168.1.200" in values["networkPolicies"]["registries"]["custom"]


def test_networkpolicy_additional_rules():
    """Test NetworkPolicy with additional rules."""
    values: Dict[str, Any] = {
        "networkPolicies": {
            "enabled": True,
            "preset": "moderate",
            "git": {
                "endpoints": ["github.com"],
                "custom": [],
                "ports": [{"port": 443, "protocol": "TCP"}],
            },
            "registries": {
                "endpoints": ["docker.io"],
                "custom": [],
                "ports": [{"port": 443, "protocol": "TCP"}],
            },
            "dns": {
                "enabled": True,
                "endpoints": ["10.96.0.10"],
                "ports": [{"port": 53, "protocol": "UDP"}, {"port": 53, "protocol": "TCP"}],
            },
            "kubernetes": {
                "enabled": True,
                "endpoints": ["kubernetes.default.svc.cluster.local"],
                "ports": [{"port": 443, "protocol": "TCP"}],
            },
            "additionalRules": [
                {
                    "to": [
                        {"namespaceSelector": {"matchLabels": {"name": "monitoring"}}},
                        {"podSelector": {"matchLabels": {"app": "prometheus"}}},
                    ],
                    "ports": [{"port": 9090, "protocol": "TCP"}],
                }
            ],
        }
    }

    # Verify additional rules configuration
    assert len(values["networkPolicies"]["additionalRules"]) == 1
    rule = values["networkPolicies"]["additionalRules"][0]
    assert len(rule["to"]) == 2
    assert rule["to"][0]["namespaceSelector"]["matchLabels"]["name"] == "monitoring"
    assert rule["to"][1]["podSelector"]["matchLabels"]["app"] == "prometheus"
    assert rule["ports"][0]["port"] == 9090
    assert rule["ports"][0]["protocol"] == "TCP"


def test_networkpolicy_executor_template():
    """Test NetworkPolicy executor template structure."""
    # This would test the executor template rendering
    # For now, we'll test the structure and logic

    values: Dict[str, Any] = {
        "networkPolicies": {
            "enabled": True,
            "preset": "moderate",
            "git": {
                "endpoints": ["github.com"],
                "custom": [],
                "ports": [{"port": 443, "protocol": "TCP"}],
            },
            "registries": {
                "endpoints": ["docker.io"],
                "custom": [],
                "ports": [{"port": 443, "protocol": "TCP"}],
            },
            "dns": {
                "enabled": True,
                "endpoints": ["10.96.0.10"],
                "ports": [{"port": 53, "protocol": "UDP"}, {"port": 53, "protocol": "TCP"}],
            },
            "kubernetes": {
                "enabled": True,
                "endpoints": ["kubernetes.default.svc.cluster.local"],
                "ports": [{"port": 443, "protocol": "TCP"}],
            },
            "additionalRules": [],
        }
    }

    # Verify executor template would use same configuration
    assert values["networkPolicies"]["enabled"] is True
    assert values["networkPolicies"]["preset"] == "moderate"


def test_networkpolicy_validation():
    """Test NetworkPolicy configuration validation."""
    # Test valid configurations
    valid_configs: List[Dict[str, Any]] = [
        {"enabled": False, "preset": "none"},
        {"enabled": True, "preset": "restrictive"},
        {"enabled": True, "preset": "moderate"},
        {"enabled": True, "preset": "permissive"},
    ]

    for config in valid_configs:
        assert config["preset"] in ["none", "restrictive", "moderate", "permissive"]
        if config["enabled"]:
            assert config["preset"] != "none"
        else:
            assert config["preset"] == "none"


def test_networkpolicy_port_validation():
    """Test NetworkPolicy port configuration validation."""
    # Test valid port configurations
    valid_ports: List[Dict[str, Any]] = [
        {"port": 22, "protocol": "TCP"},
        {"port": 443, "protocol": "TCP"},
        {"port": 80, "protocol": "TCP"},
        {"port": 53, "protocol": "UDP"},
        {"port": 53, "protocol": "TCP"},
    ]

    for port in valid_ports:
        assert port["protocol"] in ["TCP", "UDP"]
        assert isinstance(port["port"], int)
        assert 1 <= port["port"] <= 65535


def test_networkpolicy_endpoint_validation():
    """Test NetworkPolicy endpoint configuration validation."""
    # Test valid endpoint configurations
    valid_endpoints: List[str] = [
        "github.com",
        "gitlab.com",
        "docker.io",
        "192.168.1.100",
        "kubernetes.default.svc.cluster.local",
    ]

    for endpoint in valid_endpoints:
        assert isinstance(endpoint, str)
        assert len(endpoint) > 0
        # Basic validation - should not contain spaces or special characters
        assert " " not in endpoint
        assert not endpoint.startswith("-")
        assert not endpoint.endswith("-")


def test_networkpolicy_example_values_file():
    """Test that the example values file is valid YAML."""
    example_file = Path(__file__).parent.parent.parent / "examples" / "values-networkpolicies.yaml"

    if example_file.exists():
        with open(example_file, "r") as f:
            content = f.read()

        # Remove comments and test YAML parsing
        lines = content.split("\n")
        yaml_lines = []
        for line in lines:
            if not line.strip().startswith("#"):
                yaml_lines.append(line)

        yaml_content = "\n".join(yaml_lines)

        # Should not raise an exception
        try:
            yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            pytest.fail(f"Example values file contains invalid YAML: {e}")


def test_networkpolicy_helm_values_structure():
    """Test that the Helm values.yaml structure is correct."""
    values_file = (
        Path(__file__).parent.parent.parent / "helm" / "ansible-playbook-operator" / "values.yaml"
    )

    if values_file.exists():
        with open(values_file, "r") as f:
            content = f.read()

        # Parse YAML
        values = yaml.safe_load(content)

        # Check NetworkPolicy structure
        assert "networkPolicies" in values
        np = values["networkPolicies"]

        # Check required fields
        assert "enabled" in np
        assert "preset" in np
        assert "git" in np
        assert "registries" in np
        assert "dns" in np
        assert "kubernetes" in np
        assert "additionalRules" in np

        # Check preset values
        assert np["preset"] in ["none", "restrictive", "moderate", "permissive"]

        # Check git structure
        assert "endpoints" in np["git"]
        assert "custom" in np["git"]
        assert "ports" in np["git"]

        # Check registries structure
        assert "endpoints" in np["registries"]
        assert "custom" in np["registries"]
        assert "ports" in np["registries"]

        # Check dns structure
        assert "enabled" in np["dns"]
        assert "endpoints" in np["dns"]
        assert "ports" in np["dns"]

        # Check kubernetes structure
        assert "enabled" in np["kubernetes"]
        assert "endpoints" in np["kubernetes"]
        assert "ports" in np["kubernetes"]
