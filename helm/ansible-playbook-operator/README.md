# Ansible Playbook Operator Helm Chart

A lightweight, GitOps-focused Kubernetes operator for executing Ansible playbooks using the [Kopf](https://kopf.readthedocs.io) framework. Built with security, observability, and operational simplicity as core principles.

## Prerequisites

- Kubernetes 1.24+
- Helm 3.8+
- CNI with NetworkPolicy support (optional, for NetworkPolicies)
- Prometheus Operator (optional, for ServiceMonitor)

## Installation

### Basic Installation

```bash
helm install ansible-playbook-operator ./helm/ansible-playbook-operator \
  --namespace ansible-operator-system \
  --create-namespace
```

### Custom Installation

```bash
helm install ansible-playbook-operator ./helm/ansible-playbook-operator \
  --namespace ansible-operator-system \
  --create-namespace \
  --set operator.watch.scope=all \
  --set rbac.preset=minimal \
  --set operator.metrics.enabled=true
```

### Using Values Files

```bash
# Production deployment with image pinning
helm install ansible-playbook-operator ./helm/ansible-playbook-operator \
  --namespace ansible-operator-system \
  --create-namespace \
  --values examples/values-production-pinning.yaml

# Cluster-wide deployment
helm install ansible-playbook-operator ./helm/ansible-playbook-operator \
  --namespace ansible-operator-system \
  --create-namespace \
  --values examples/values-cluster-watch.yaml

# With NetworkPolicies enabled
helm install ansible-playbook-operator ./helm/ansible-playbook-operator \
  --namespace ansible-operator-system \
  --create-namespace \
  --values examples/values-networkpolicies.yaml
```

## Configuration

### Operator Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `operator.image.repository` | Operator image repository | `kenchrcum/ansible-playbook-operator` |
| `operator.image.tag` | Operator image tag | `0.1.5` |
| `operator.image.digest` | Operator image digest (takes precedence over tag) | `""` |
| `operator.image.pullPolicy` | Image pull policy | `IfNotPresent` |
| `operator.resources.requests` | Resource requests | `cpu: 100m, memory: 128Mi` |
| `operator.resources.limits` | Resource limits | `cpu: 500m, memory: 512Mi` |
| `operator.leaderElection` | Enable leader election | `true` |
| `operator.watch.scope` | Watch scope (`namespace` or `all`) | `namespace` |
| `operator.metrics.enabled` | Enable Prometheus metrics | `false` |
| `operator.metrics.serviceMonitor.enabled` | Create ServiceMonitor | `true` |
| `operator.serviceAccount.create` | Create ServiceAccount | `true` |
| `operator.serviceAccount.name` | ServiceAccount name | `""` |

### Executor Defaults Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `executorDefaults.image.repository` | Executor image repository | `kenchrcum/ansible-runner` |
| `executorDefaults.image.tag` | Executor image tag | `13` |
| `executorDefaults.image.digest` | Executor image digest (takes precedence over tag) | `""` |
| `executorDefaults.image.pullPolicy` | Image pull policy | `IfNotPresent` |
| `executorDefaults.serviceAccount.create` | Create executor ServiceAccount | `true` |
| `executorDefaults.serviceAccount.name` | Executor ServiceAccount name | `""` |
| `executorDefaults.serviceAccount.rbacPreset` | RBAC preset (`minimal`, `scoped`, `cluster-admin`) | `minimal` |
| `executorDefaults.cache.strategy` | Cache strategy (`none`, `pvc`) | `none` |
| `executorDefaults.cache.pvcName` | PVC name for caching | `""` |
| `executorDefaults.cache.createPVC` | Create PVC for caching | `false` |
| `executorDefaults.cache.storageSize` | Storage size for cache PVC | `10Gi` |
| `executorDefaults.cache.storageClassName` | Storage class for cache PVC | `""` |

### RBAC Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `rbac.preset` | RBAC preset (`minimal`, `scoped`, `cluster-admin`) | `minimal` |
| `rbac.clusterRead` | Enable cluster read permissions | `true` |
| `rbac.secretRestriction.enabled` | Enable secret access restriction | `false` |
| `rbac.secretRestriction.allowedSecrets` | List of allowed secret names | `[]` |
| `rbac.secretRestriction.crossNamespaceSecrets` | Cross-namespace secret access | `{}` |

### NetworkPolicy Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `networkPolicies.enabled` | Enable NetworkPolicies | `false` |
| `networkPolicies.preset` | NetworkPolicy preset (`none`, `restrictive`, `moderate`, `permissive`) | `none` |
| `networkPolicies.git.endpoints` | Git endpoints to allow | `[github.com, gitlab.com, bitbucket.org, gitea.com, gitee.com]` |
| `networkPolicies.git.custom` | Custom Git endpoints | `[]` |
| `networkPolicies.git.ports` | Git ports to allow | `[{port: 22, protocol: TCP}, {port: 443, protocol: TCP}, {port: 80, protocol: TCP}]` |
| `networkPolicies.registries.endpoints` | Registry endpoints to allow | `[docker.io, registry-1.docker.io, gcr.io, k8s.gcr.io, quay.io, registry.k8s.io, ghcr.io]` |
| `networkPolicies.registries.custom` | Custom registry endpoints | `[]` |
| `networkPolicies.registries.ports` | Registry ports to allow | `[{port: 443, protocol: TCP}, {port: 80, protocol: TCP}]` |
| `networkPolicies.dns.enabled` | Enable DNS resolution | `true` |
| `networkPolicies.dns.endpoints` | DNS endpoints | `[10.96.0.10, 169.254.20.10]` |
| `networkPolicies.dns.ports` | DNS ports | `[{port: 53, protocol: UDP}, {port: 53, protocol: TCP}]` |
| `networkPolicies.kubernetes.enabled` | Enable Kubernetes API access | `true` |
| `networkPolicies.kubernetes.endpoints` | Kubernetes API endpoints | `[kubernetes.default.svc.cluster.local]` |
| `networkPolicies.kubernetes.ports` | Kubernetes API ports | `[{port: 443, protocol: TCP}]` |
| `networkPolicies.additionalRules` | Additional egress rules | `[]` |

## Examples

### Basic Example

```yaml
# Basic configuration
operator:
  image:
    repository: kenchrcum/ansible-playbook-operator
    tag: "0.1.5"
  watch:
    scope: namespace

executorDefaults:
  image:
    repository: kenchrcum/ansible-runner
    tag: 13

rbac:
  preset: minimal
```

### Production Example

```yaml
# Production configuration with security hardening
operator:
  image:
    repository: kenchrcum/ansible-playbook-operator
    tag: "0.1.5"
    digest: "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
    pullPolicy: IfNotPresent
  resources:
    requests:
      cpu: 200m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 1Gi
  watch:
    scope: all
  metrics:
    enabled: true
    serviceMonitor:
      enabled: true

executorDefaults:
  image:
    repository: kenchrcum/ansible-runner
    tag: 13
    digest: "sha256:abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
    pullPolicy: IfNotPresent
  cache:
    strategy: pvc
    createPVC: true
    storageSize: "50Gi"
    storageClassName: "fast-ssd"

rbac:
  preset: scoped
  clusterRead: true

networkPolicies:
  enabled: true
  preset: moderate
```

### Development Example

```yaml
# Development configuration with relaxed security
operator:
  image:
    repository: kenchrcum/ansible-playbook-operator
    tag: "0.1.5"
  watch:
    scope: namespace

executorDefaults:
  image:
    repository: kenchrcum/ansible-runner
    tag: 13

rbac:
  preset: minimal
  clusterRead: true

networkPolicies:
  enabled: false
```

## RBAC Presets

### Minimal (Default)
- **Scope**: Single namespace
- **Permissions**: Least-privilege namespaced permissions
- **Use Cases**: Single-tenant deployments, development environments
- **Security Level**: High

### Scoped
- **Scope**: Cluster-wide
- **Permissions**: Cross-namespace access with controlled permissions
- **Use Cases**: Centralized management, multi-tenant environments
- **Security Level**: Medium

### Cluster-Admin
- **Scope**: Cluster-wide
- **Permissions**: Full cluster permissions
- **Use Cases**: Development/testing, highly trusted environments
- **Security Level**: Low

## NetworkPolicy Presets

### None (Default)
- **Egress**: All traffic allowed
- **Use Cases**: Development, testing
- **Security Level**: Low

### Restrictive
- **Egress**: Only Git endpoints and container registries
- **Use Cases**: High-security environments, air-gapped deployments
- **Security Level**: High

### Moderate (Recommended)
- **Egress**: DNS, Git endpoints, registries, and Kubernetes API
- **Use Cases**: Production environments, most Ansible operations
- **Security Level**: High

### Permissive
- **Egress**: All traffic allowed
- **Use Cases**: Development, testing, troubleshooting
- **Security Level**: Low

## Security Considerations

### Image Security
- Use digest pinning for production deployments
- Regularly scan images for vulnerabilities
- Implement image signing and verification
- Monitor for image updates and security patches

### Network Security
- Enable NetworkPolicies with appropriate presets
- Restrict egress to only required endpoints
- Use dedicated service accounts for different security contexts
- Implement network segmentation

### Access Control
- Use least-privilege RBAC presets
- Implement secret access restrictions when possible
- Regularly audit permissions and access patterns
- Monitor for privilege escalation attempts

### Compliance
- Maintain audit trails of all deployments
- Document security configurations and justifications
- Implement policy enforcement for security requirements
- Regular security reviews and assessments

## Monitoring and Observability

### Metrics
- Enable Prometheus metrics for operator monitoring
- Use ServiceMonitor for Prometheus Operator integration
- Monitor reconciliation counters and durations
- Track resource usage and performance metrics

### Logging
- Structured JSON logs with correlation IDs
- Never log secrets or sensitive information
- Include controller, resource, and event information
- Implement log aggregation and analysis

### Events
- Kubernetes Events for lifecycle transitions
- Standardized event reasons across all operations
- Event correlation with metrics and logs
- Alerting on critical events and failures

## Troubleshooting

### Common Issues

#### 1. Permission Errors
```
Error: forbidden: User cannot access resource
```
**Solution**: Check RBAC preset configuration and permissions

#### 2. Network Connectivity Issues
```
Error: connection refused
```
**Solution**: Verify NetworkPolicy configuration and endpoints

#### 3. Image Pull Failures
```
Error: failed to pull image
```
**Solution**: Check image digest, registry access, and network policies

#### 4. Resource Quota Exceeded
```
Error: resource quota exceeded
```
**Solution**: Increase resource quotas or optimize resource usage

### Debug Commands

```bash
# Check operator status
kubectl get deployment ansible-playbook-operator -n ansible-operator-system

# View operator logs
kubectl logs -l app.kubernetes.io/name=ansible-playbook-operator -n ansible-operator-system

# Check RBAC permissions
kubectl auth can-i get secrets --as=system:serviceaccount:ansible-operator-system:ansible-playbook-operator

# Verify NetworkPolicies
kubectl get networkpolicies -n ansible-operator-system

# Check PVC status
kubectl get pvc -n ansible-operator-system
```

## Best Practices

### 1. Security
- Use digest pinning for production deployments
- Enable NetworkPolicies with appropriate presets
- Implement least-privilege RBAC configurations
- Regular security audits and updates

### 2. Performance
- Configure appropriate resource requests and limits
- Use PVC caching for frequently executed playbooks
- Monitor resource usage and optimize as needed
- Implement horizontal scaling if required

### 3. Reliability
- Enable leader election for high availability
- Implement proper backup and recovery procedures
- Monitor for failures and implement alerting
- Test disaster recovery procedures regularly

### 4. Operations
- Use GitOps workflows for deployment management
- Implement automated testing and validation
- Maintain comprehensive documentation
- Regular updates and maintenance procedures

## Migration Guide

### From Tag-Based to Digest-Based Images

1. **Get current image digests**:
   ```bash
   crane digest kenchrcum/ansible-playbook-operator:0.1.5
   crane digest kenchrcum/ansible-runner:latest
   ```

2. **Update values file**:
   ```yaml
   operator:
     image:
       digest: "sha256:1234567890abcdef..."
   executorDefaults:
     image:
       digest: "sha256:abcdef1234567890..."
   ```

3. **Deploy and verify**:
   ```bash
   helm upgrade ansible-playbook-operator ./helm/ansible-playbook-operator \
     --values values-image-pinning.yaml
   ```

### From Namespace to Cluster-Wide Watch

1. **Update watch scope**:
   ```yaml
   operator:
     watch:
       scope: all
   ```

2. **Change RBAC preset**:
   ```yaml
   rbac:
     preset: scoped
   ```

3. **Deploy and test**:
   ```bash
   helm upgrade ansible-playbook-operator ./helm/ansible-playbook-operator \
     --values values-cluster-watch.yaml
   ```

## Support

For issues, questions, or contributions:

- **GitHub**: [https://github.com/kenchrcum/ansible-playbook-operator](https://github.com/kenchrcum/ansible-playbook-operator)
- **Documentation**: [https://github.com/kenchrcum/ansible-playbook-operator/tree/main/docs](https://github.com/kenchrcum/ansible-playbook-operator/tree/main/docs)
- **Examples**: [https://github.com/kenchrcum/ansible-playbook-operator/tree/main/examples](https://github.com/kenchrcum/ansible-playbook-operator/tree/main/examples)

## License

This project is licensed under the Unlicense - see the [LICENSE](LICENSE) file for details.
