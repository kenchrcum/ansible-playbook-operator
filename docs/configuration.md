# Configuration Reference

This document provides a comprehensive reference for configuring the Ansible Playbook Operator.

## Table of Contents

- [Helm Values Reference](#helm-values-reference)
- [Environment Variables](#environment-variables)
- [Operator Flags](#operator-flags)
- [Watch Scope Configuration](#watch-scope-configuration)
- [RBAC Configuration](#rbac-configuration)
- [Security Configuration](#security-configuration)
- [Monitoring Configuration](#monitoring-configuration)
- [Cache Configuration](#cache-configuration)
- [Network Policy Configuration](#network-policy-configuration)

## Helm Values Reference

### Operator Configuration

```yaml
operator:
  # Container image configuration
  image:
    repository: kenchrcum/ansible-playbook-operator
    tag: "0.1.5"
    digest: ""  # Optional: pin by digest for security
    pullPolicy: IfNotPresent

  # Resource requests and limits
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 512Mi

  # Leader election for HA deployments
  leaderElection: true

  # Watch scope: 'namespace' (default) or 'all' (cluster-wide)
  watch:
    scope: namespace

  # Metrics and monitoring
  metrics:
    enabled: false
    serviceMonitor:
      enabled: true

  # ServiceAccount configuration
  serviceAccount:
    create: true
    name: ""  # Auto-generated if empty
```

### Executor Defaults

```yaml
executorDefaults:
  # Default executor image
  image:
    repository: kenchrcum/ansible-runner
    tag: 13
    digest: ""  # Optional: pin by digest for security
    pullPolicy: IfNotPresent

  # Executor ServiceAccount
  serviceAccount:
    create: true
    name: ""  # Auto-generated if empty
    rbacPreset: minimal  # minimal, scoped, cluster-admin

  # Cache configuration
  cache:
    strategy: none  # none, pvc
    pvcName: ""
    createPVC: false
    storageSize: "10Gi"
    storageClassName: ""
```

### RBAC Configuration

```yaml
rbac:
  # Permission preset: minimal, scoped, cluster-admin
  preset: minimal

  # Cluster read permissions for Kopf preflight
  clusterRead: true

  # Secret access restriction
  secretRestriction:
    enabled: false
    allowedSecrets: []
    crossNamespaceSecrets: {}
```

### Network Policy Configuration

```yaml
networkPolicies:
  enabled: false
  preset: none  # none, restrictive, moderate, permissive

  # Git endpoints
  git:
    endpoints:
      - github.com
      - gitlab.com
      - bitbucket.org
    custom: []
    ports:
      - port: 22
        protocol: TCP
      - port: 443
        protocol: TCP

  # Container registries
  registries:
    endpoints:
      - docker.io
      - gcr.io
      - quay.io
    custom: []
    ports:
      - port: 443
        protocol: TCP

  # DNS configuration
  dns:
    enabled: true
    endpoints:
      - 10.96.0.10
    ports:
      - port: 53
        protocol: UDP

  # Kubernetes API access
  kubernetes:
    enabled: true
    endpoints:
      - kubernetes.default.svc.cluster.local
    ports:
      - port: 443
        protocol: TCP
```

## Environment Variables

The operator supports the following environment variables:

### Core Configuration

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `WATCH_SCOPE` | Watch scope for resources | `namespace` | `all` |
| `POD_NAMESPACE` | Namespace where operator runs | Auto-detected | `ansible-operator-system` |
| `KOPF_LEADER_ELECTION` | Enable leader election | `true` | `false` |
| `EXECUTOR_SERVICE_ACCOUNT` | Executor ServiceAccount name | Auto-generated | `my-executor-sa` |

### Debugging

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `KOPF_DEBUG` | Enable debug logging | `false` | `true` |
| `PYTHONUNBUFFERED` | Unbuffered Python output | `1` | `1` |
| `USER` | User for security context | `ansible` | `ansible` |

### Performance Tuning

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `KOPF_MAX_WORKERS` | Maximum concurrent reconciliations | `4` | `8` |
| `KOPF_REQUEST_TIMEOUT` | API request timeout (seconds) | `30` | `60` |

## Operator Flags

The operator uses Kopf framework flags:

### Watch Scope Flags

```bash
# Single namespace (default)
kopf run --namespace my-namespace -m ansible_operator.main

# All namespaces
kopf run --all-namespaces -m ansible_operator.main

# Specific namespace
kopf run --namespace ansible-operator-system -m ansible_operator.main
```

### Performance Flags

```bash
# Custom worker count
kopf run --max-workers 8 -m ansible_operator.main

# Custom timeout
kopf run --request-timeout 60 -m ansible_operator.main
```

### Debug Flags

```bash
# Enable debug logging
kopf run --debug -m ansible_operator.main

# Verbose output
kopf run --verbose -m ansible_operator.main
```

## Watch Scope Configuration

### Namespace Scope (Default)

**Configuration:**
```yaml
operator:
  watch:
    scope: namespace
```

**Behavior:**
- Operator watches resources only in its own namespace
- Requires minimal RBAC permissions
- Suitable for single-namespace deployments
- Default ServiceAccount has namespace-scoped permissions

**RBAC Requirements:**
```yaml
rbac:
  preset: minimal
  clusterRead: true  # For CRD and namespace discovery
```

### Cluster-Wide Scope

**Configuration:**
```yaml
operator:
  watch:
    scope: all
```

**Behavior:**
- Operator watches resources across all namespaces
- Requires cluster-wide RBAC permissions
- Suitable for multi-namespace deployments
- ServiceAccount needs ClusterRole permissions

**RBAC Requirements:**
```yaml
rbac:
  preset: scoped  # or cluster-admin for full access
```

**Example Deployment:**
```bash
helm install ansible-playbook-operator ./helm/ansible-playbook-operator \
  --namespace ansible-operator-system \
  --create-namespace \
  --set operator.watch.scope=all \
  --set rbac.preset=scoped
```

## RBAC Configuration

### Preset Overview

| Preset | Description | Use Case | Permissions |
|--------|-------------|----------|-------------|
| `minimal` | Least-privilege, namespace-scoped | Single namespace deployments | Basic operator permissions |
| `scoped` | Extended, cross-namespace | Multi-namespace deployments | Cluster-wide read, namespace write |
| `cluster-admin` | Full cluster access | Cluster-wide resource management | Wildcard permissions |

### Minimal Preset

**Configuration:**
```yaml
rbac:
  preset: minimal
  clusterRead: true
```

**Permissions:**
- Namespace-scoped Role for core operations
- Read-only access to referenced Secrets
- Basic cluster read permissions for CRDs/namespaces
- Manage Jobs, CronJobs, Events in namespace

**Use Cases:**
- Single-namespace deployments
- Development environments
- Minimal trust scenarios

### Scoped Preset

**Configuration:**
```yaml
rbac:
  preset: scoped
```

**Permissions:**
- ClusterRole for cross-namespace resource access
- Extended namespaced permissions
- Read access to Secrets, ConfigMaps across namespaces
- Manage Jobs, CronJobs across namespaces

**Use Cases:**
- Multi-namespace deployments
- Cluster-wide operator deployments
- Cross-namespace resource management

### Cluster-Admin Preset

**Configuration:**
```yaml
rbac:
  preset: cluster-admin
```

**Permissions:**
- Full cluster permissions
- Wildcard API groups, resources, verbs
- Complete cluster access

**Use Cases:**
- Playbooks requiring cluster-wide resource management
- Administrative automation
- **Warning**: Use with extreme caution

### Secret Access Restriction

**Configuration:**
```yaml
rbac:
  secretRestriction:
    enabled: true
    allowedSecrets:
      - github-token
      - ssh-key
      - vault-password
    crossNamespaceSecrets:
      shared-namespace:
        - shared-secret
```

**Behavior:**
- Restricts Secret access to explicitly listed names
- Provides enhanced security but requires operational overhead
- Must be maintained when new Secrets are referenced

## Security Configuration

### Image Pinning

**Configuration:**
```yaml
operator:
  image:
    repository: kenchrcum/ansible-playbook-operator
    digest: "sha256:abc123def456..."  # Pinned by digest

executorDefaults:
  image:
    repository: kenchrcum/ansible-runner
    digest: "sha256:def456ghi789..."  # Pinned by digest
```

**Benefits:**
- Ensures reproducible deployments
- Prevents image tampering
- Enhances security posture

### Security Contexts

**Operator Security Context:**
```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
```

**Executor Security Context (Default):**
```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  seccompProfile:
    type: RuntimeDefault
  capabilities:
    drop: ["ALL"]
```

### Network Policies

**Restrictive Preset:**
```yaml
networkPolicies:
  enabled: true
  preset: restrictive
```

**Moderate Preset:**
```yaml
networkPolicies:
  enabled: true
  preset: moderate
```

**Custom Configuration:**
```yaml
networkPolicies:
  enabled: true
  preset: none
  git:
    custom:
      - git.company.com
  registries:
    custom:
      - registry.company.com
```

## Monitoring Configuration

### Metrics

**Basic Configuration:**
```yaml
operator:
  metrics:
    enabled: true
```

**ServiceMonitor Configuration:**
```yaml
operator:
  metrics:
    enabled: true
    serviceMonitor:
      enabled: true
```

**Custom Metrics Port:**
```yaml
operator:
  metrics:
    enabled: true
    port: 8080
```

### Logging

**Structured Logging:**
- JSON format with structured fields
- Correlation IDs for tracing
- Secret redaction enabled
- Configurable log levels

**Log Fields:**
- `controller`: Controller name
- `resource`: Resource identifier
- `uid`: Resource UID
- `runId`: Execution run ID
- `event`: Event type
- `reason`: Event reason

## Cache Configuration

### PVC Cache Strategy

**Configuration:**
```yaml
executorDefaults:
  cache:
    strategy: pvc
    pvcName: "ansible-cache-pvc"
    createPVC: true
    storageSize: "20Gi"
    storageClassName: "fast-ssd"
```

**Benefits:**
- Speeds up repeated Ansible runs
- Caches collections and roles
- Reduces network traffic
- Improves performance

### Cache Management

**Cache Contents:**
- Ansible collections (`~/.ansible/collections`)
- Ansible roles (`~/.ansible/roles`)
- Galaxy requirements cache

**Cache Lifecycle:**
- Created per namespace
- Labeled by owner
- TTL-based cleanup
- Manual cleanup available

## Network Policy Configuration

### Preset Descriptions

| Preset | Description | Egress Rules |
|--------|-------------|--------------|
| `none` | No NetworkPolicies | All traffic allowed |
| `restrictive` | Minimal egress | Git + registries only |
| `moderate` | Balanced security | Git + registries + DNS + API |
| `permissive` | Maximum compatibility | All traffic allowed |

### Custom Endpoints

**Git Endpoints:**
```yaml
networkPolicies:
  git:
    custom:
      - git.company.com
      - 192.168.1.100
```

**Registry Endpoints:**
```yaml
networkPolicies:
  registries:
    custom:
      - registry.company.com
      - 192.168.1.200
```

### Port Configuration

**Custom Ports:**
```yaml
networkPolicies:
  git:
    ports:
      - port: 22
        protocol: TCP
      - port: 443
        protocol: TCP
      - port: 9418
        protocol: TCP  # Git protocol
```

## Configuration Examples

### Development Environment

```yaml
operator:
  image:
    tag: "dev"
  resources:
    requests:
      cpu: 50m
      memory: 64Mi
    limits:
      cpu: 200m
      memory: 256Mi
  metrics:
    enabled: true

rbac:
  preset: minimal

networkPolicies:
  enabled: false
```

### Production Environment

```yaml
operator:
  image:
    digest: "sha256:abc123def456..."
  resources:
    requests:
      cpu: 200m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 1Gi
  metrics:
    enabled: true
    serviceMonitor:
      enabled: true

executorDefaults:
  image:
    digest: "sha256:def456ghi789..."
  cache:
    strategy: pvc
    createPVC: true
    storageSize: "50Gi"
    storageClassName: "fast-ssd"

rbac:
  preset: scoped
  secretRestriction:
    enabled: true
    allowedSecrets:
      - github-token
      - ssh-key

networkPolicies:
  enabled: true
  preset: moderate
```

### High Security Environment

```yaml
operator:
  image:
    digest: "sha256:abc123def456..."

rbac:
  preset: minimal
  secretRestriction:
    enabled: true
    allowedSecrets:
      - github-token
      - ssh-key
      - vault-password

networkPolicies:
  enabled: true
  preset: restrictive
  git:
    custom:
      - git.company.com
  registries:
    custom:
      - registry.company.com
```

## Validation

### Helm Values Validation

```bash
# Validate Helm values
helm template ansible-playbook-operator ./helm/ansible-playbook-operator --values my-values.yaml --dry-run

# Check for syntax errors
helm lint ./helm/ansible-playbook-operator --values my-values.yaml
```

### Configuration Testing

```bash
# Test operator startup
kubectl run test-operator --image=kenchrcum/ansible-playbook-operator:dev --rm -it -- sh

# Validate RBAC permissions
kubectl auth can-i get pods --as=system:serviceaccount:ansible-operator-system:ansible-playbook-operator
```

### Network Connectivity Testing

```bash
# Test Git connectivity
kubectl run git-test --image=alpine/git --rm -it -- sh
# Inside pod: git ls-remote https://github.com/your-org/your-repo.git

# Test registry connectivity
kubectl run registry-test --image=alpine --rm -it -- sh
# Inside pod: wget -O- https://registry-1.docker.io/v2/
```
