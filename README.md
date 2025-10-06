# Ansible Playbook Operator

![Version](https://img.shields.io/badge/version-0.1.2-blue.svg)
![License](https://img.shields.io/badge/license-Unlicense-green.svg)
[![Artifact Hub](https://img.shields.io/endpoint?url=https://artifacthub.io/badge/repository/ansible-playbook-operator)](https://artifacthub.io/packages/helm/ansible-playbook-operator/ansible-playbook-operator)

A lightweight, GitOps-focused Kubernetes operator for running Ansible playbooks on-demand or on a schedule. Designed for simplicity, security, and observability.

## Features

- **GitOps Integration**: Pull playbooks directly from Git repositories
- **Scheduled Execution**: Run playbooks on cron schedules with randomization support
- **On-Demand Execution**: Trigger playbook runs manually via Kubernetes API
- **Secure by Default**: Minimal RBAC, image pinning, and network policies
- **Observable**: Prometheus metrics, structured logging, and Kubernetes events
- **Flexible**: Support for Ansible execution options, vault passwords, and custom environments

## Installation

### Prerequisites

- Kubernetes 1.19+
- Helm 3.0+

### Quick Start

```bash
# Add the Helm repository
helm repo add ansible-playbook-operator https://kenchrcum.github.io/ansible-playbook-operator/
helm repo update

# Install the operator
helm install ansible-playbook-operator ansible-playbook-operator/ansible-playbook-operator
```

### Custom Installation

For production deployments, customize the installation:

```bash
# Install with custom values
helm install ansible-playbook-operator ansible-playbook-operator/ansible-playbook-operator \
  --values your-values.yaml \
  --namespace ansible-operator \
  --create-namespace
```

## Configuration

The Ansible Playbook Operator can be configured via Helm values. Below is a comprehensive table of all available configuration options.

### Operator Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operator.image.repository` | string | `"kenchrcum/ansible-playbook-operator"` | Operator container image repository |
| `operator.image.tag` | string | `"0.1.2"` | Operator container image tag |
| `operator.image.digest` | string | `""` | Operator container image digest (takes precedence over tag when set) |
| `operator.image.pullPolicy` | string | `"IfNotPresent"` | Operator container image pull policy |
| `operator.resources.requests.cpu` | string | `"100m"` | Operator CPU resource requests |
| `operator.resources.requests.memory` | string | `"128Mi"` | Operator memory resource requests |
| `operator.resources.limits.cpu` | string | `"500m"` | Operator CPU resource limits |
| `operator.resources.limits.memory` | string | `"512Mi"` | Operator memory resource limits |
| `operator.leaderElection` | bool | `true` | Enable leader election for high availability |
| `operator.watch.scope` | string | `"namespace"` | Watch scope: `namespace` or `all` |
| `operator.metrics.enabled` | bool | `false` | Enable Prometheus metrics endpoint |
| `operator.metrics.serviceMonitor.enabled` | bool | `true` | Create ServiceMonitor for Prometheus Operator |
| `operator.serviceAccount.create` | bool | `true` | Create dedicated ServiceAccount for operator |
| `operator.serviceAccount.name` | string | `""` | Custom ServiceAccount name (auto-generated if empty) |

### Executor Defaults Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `executorDefaults.image.repository` | string | `"kenchrcum/ansible-runner"` | Default executor container image repository |
| `executorDefaults.image.tag` | string | `"13"` | Default executor container image tag |
| `executorDefaults.image.digest` | string | `""` | Default executor container image digest (takes precedence over tag when set) |
| `executorDefaults.image.pullPolicy` | string | `"IfNotPresent"` | Default executor container image pull policy |
| `executorDefaults.serviceAccount.create` | bool | `true` | Create separate ServiceAccount for executor Jobs |
| `executorDefaults.serviceAccount.name` | string | `""` | Name of executor ServiceAccount (auto-generated if empty) |
| `executorDefaults.serviceAccount.rbacPreset` | string | `"minimal"` | RBAC preset: `minimal`, `scoped`, `cluster-admin` |
| `executorDefaults.cache.strategy` | string | `"none"` | Default cache strategy: `none`, `pvc` |
| `executorDefaults.cache.pvcName` | string | `""` | Default PVC name when strategy is `pvc` |
| `executorDefaults.cache.createPVC` | bool | `false` | Create PVC for caching |
| `executorDefaults.cache.storageSize` | string | `"10Gi"` | Storage size for cache PVC |
| `executorDefaults.cache.storageClassName` | string | `""` | Storage class name for cache PVC |

### RBAC Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `rbac.preset` | string | `"minimal"` | RBAC permission preset: `minimal`, `scoped`, `cluster-admin` |
| `rbac.clusterRead` | bool | `true` | Enable cluster read permissions for preflight checks |
| `rbac.secretRestriction.enabled` | bool | `false` | Enable Secret access restriction |
| `rbac.secretRestriction.allowedSecrets` | list | `[]` | List of allowed Secret names |
| `rbac.secretRestriction.crossNamespaceSecrets` | object | `{}` | Cross-namespace Secret access mapping |

### Network Policies Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `networkPolicies.enabled` | bool | `false` | Enable NetworkPolicy creation |
| `networkPolicies.preset` | string | `"none"` | NetworkPolicy preset: `none`, `restrictive`, `moderate`, `permissive` |
| `networkPolicies.git.endpoints` | list | `[github.com, gitlab.com, bitbucket.org, gitea.com, gitee.com]` | Git hostnames for egress |
| `networkPolicies.git.custom` | list | `[]` | Custom Git endpoints |
| `networkPolicies.git.ports` | list | `[{port: 22, protocol: TCP}, {port: 443, protocol: TCP}, {port: 80, protocol: TCP}]` | Git ports |
| `networkPolicies.registries.endpoints` | list | `[docker.io, registry-1.docker.io, gcr.io, k8s.gcr.io, quay.io, registry.k8s.io, ghcr.io]` | Container registry hostnames |
| `networkPolicies.registries.custom` | list | `[]` | Custom registry endpoints |
| `networkPolicies.registries.ports` | list | `[{port: 443, protocol: TCP}, {port: 80, protocol: TCP}]` | Registry ports |
| `networkPolicies.dns.enabled` | bool | `true` | Allow DNS resolution |
| `networkPolicies.dns.endpoints` | list | `[10.96.0.10, 169.254.20.10]` | DNS server endpoints |
| `networkPolicies.dns.ports` | list | `[{port: 53, protocol: UDP}, {port: 53, protocol: TCP}]` | DNS ports |
| `networkPolicies.kubernetes.enabled` | bool | `true` | Allow Kubernetes API access |
| `networkPolicies.kubernetes.endpoints` | list | `[kubernetes.default.svc.cluster.local]` | Kubernetes API endpoints |
| `networkPolicies.kubernetes.ports` | list | `[{port: 443, protocol: TCP}]` | Kubernetes API ports |
| `networkPolicies.additionalRules` | list | `[]` | Additional custom egress rules |

## Usage

After installation, create Ansible Repository and Playbook custom resources:

```yaml
apiVersion: ansible.cloud37.dev/v1alpha1
kind: Repository
metadata:
  name: my-ansible-repo
spec:
  url: https://github.com/example/ansible-playbooks
  # ... other spec fields

---
apiVersion: ansible.cloud37.dev/v1alpha1
kind: Playbook
metadata:
  name: deploy-app
spec:
  repository: my-ansible-repo
  playbook: site.yml
  # ... other spec fields
```

## Documentation

- [Full Documentation](https://github.com/kenchrcum/ansible-playbook-operator)
- [Configuration Guide](https://github.com/kenchrcum/ansible-playbook-operator/docs/configuration.md)
- [Security Best Practices](https://github.com/kenchrcum/ansible-playbook-operator/docs/security.md)
- [Monitoring and Observability](https://github.com/kenchrcum/ansible-playbook-operator/docs/monitoring.md)

## Contributing

Contributions are welcome! Please see our [contributing guidelines](https://github.com/kenchrcum/ansible-playbook-operator/CONTRIBUTING.md).

## License

This project is licensed under the [Unlicense](https://unlicense.org/) - see the [LICENSE](https://github.com/kenchrcum/ansible-playbook-operator/LICENSE) file for details.

## Support

- [GitHub Issues](https://github.com/kenchrcum/ansible-playbook-operator/issues)
- [Discussions](https://github.com/kenchrcum/ansible-playbook-operator/discussions)

---

*Built with ❤️ for Kubernetes and Ansible automation*