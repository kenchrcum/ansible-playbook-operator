# Upgrade and Migration Guide

This guide covers upgrading the Ansible Playbook Operator and migrating between versions.

## Table of Contents

- [Upgrade Overview](#upgrade-overview)
- [Helm Chart Upgrades](#helm-chart-upgrades)
- [CRD Version Migration](#crd-version-migration)
- [Backward Compatibility](#backward-compatibility)
- [Rollback Procedures](#rollback-procedures)
- [Migration Strategies](#migration-strategies)
- [Testing Upgrades](#testing-upgrades)
- [Troubleshooting Upgrades](#troubleshooting-upgrades)

## Upgrade Overview

The Ansible Playbook Operator follows semantic versioning:

- **Major versions**: Breaking changes, require migration
- **Minor versions**: New features, backward compatible
- **Patch versions**: Bug fixes, backward compatible

### Version Compatibility

| Operator Version | CRD Version | Kubernetes Version | Helm Version |
|------------------|-------------|-------------------|--------------|
| 0.1.2 | v1alpha1 | 1.24+ | 3.8+ |
| 0.2.0 | v1alpha1 | 1.24+ | 3.8+ |
| 1.0.0 | v1beta1 | 1.24+ | 3.8+ |

### Upgrade Paths

**Supported Upgrades:**
- 0.1.2 → 0.2.0 (minor version)
- 0.2.0 → 1.0.0 (major version with migration)
- 1.0.0 → 1.1.0 (minor version)

**Unsupported Upgrades:**
- Skipping major versions
- Downgrading to previous major versions
- Upgrading across incompatible Kubernetes versions

## Helm Chart Upgrades

### Minor Version Upgrades

**Upgrade Process:**
```bash
# Check current version
helm list -n ansible-operator-system

# Update Helm repository
helm repo update

# Upgrade to latest minor version
helm upgrade ansible-playbook-operator ./helm/ansible-playbook-operator \
  --namespace ansible-operator-system \
  --reuse-values
```

**Verification:**
```bash
# Check operator status
kubectl get pods -n ansible-operator-system

# Check operator logs
kubectl logs -n ansible-operator-system deployment/ansible-playbook-operator

# Verify CRDs
kubectl get crd | grep ansible.cloud37.dev
```

### Major Version Upgrades

**Pre-Upgrade Checklist:**
- [ ] Backup existing resources
- [ ] Review breaking changes
- [ ] Plan migration strategy
- [ ] Test in non-production environment
- [ ] Schedule maintenance window

**Upgrade Process:**
```bash
# 1. Backup existing resources
kubectl get repositories,playbooks,schedules --all-namespaces -o yaml > backup.yaml

# 2. Review breaking changes
# Check release notes for v1.0.0

# 3. Upgrade Helm chart
helm upgrade ansible-playbook-operator ./helm/ansible-playbook-operator \
  --namespace ansible-operator-system \
  --version 1.0.0 \
  --reuse-values

# 4. Verify upgrade
kubectl get pods -n ansible-operator-system
kubectl get crd | grep ansible.cloud37.dev
```

### Configuration Migration

**Helm Values Migration:**
```yaml
# Old configuration (v0.1.2)
operator:
  image:
    tag: "0.1.2"
  resources:
    requests:
      cpu: 100m
      memory: 128Mi

# New configuration (v1.0.0)
operator:
  image:
    tag: "1.0.0"
    digest: "sha256:abc123def456..."  # New: image pinning
  resources:
    requests:
      cpu: 200m  # Increased default
      memory: 256Mi  # Increased default
  metrics:
    enabled: true  # New: metrics enabled by default
```

## CRD Version Migration

### v1alpha1 to v1beta1 Migration

**CRD Changes:**
- New fields added
- Field validation updates
- Status condition changes
- Default value updates

**Migration Process:**
```bash
# 1. Check current CRD version
kubectl get crd playbooks.ansible.cloud37.dev -o jsonpath='{.spec.versions[*].name}'

# 2. Apply new CRD version
kubectl apply -f helm/ansible-playbook-operator/crds/

# 3. Verify CRD migration
kubectl get crd playbooks.ansible.cloud37.dev -o jsonpath='{.spec.versions[*].name}'

# 4. Check resource status
kubectl get playbooks --all-namespaces
```

### Resource Migration

**Automatic Migration:**
- Kubernetes handles CRD version conversion
- Existing resources are automatically migrated
- No manual intervention required

**Manual Verification:**
```bash
# Check resource status
kubectl get repositories,playbooks,schedules --all-namespaces

# Verify status conditions
kubectl get playbook my-playbook -o jsonpath='{.status.conditions}'

# Check for migration issues
kubectl get events --field-selector reason=MigrationFailed
```

## Backward Compatibility

### API Compatibility

**v1alpha1 Compatibility:**
- All v1alpha1 resources continue to work
- New fields are optional
- Existing fields remain unchanged
- Status conditions are backward compatible

**v1beta1 Compatibility:**
- New fields added
- Enhanced validation
- Improved status conditions
- Better error reporting

### Configuration Compatibility

**Helm Values Compatibility:**
```yaml
# Old values still work
operator:
  image:
    tag: "0.1.2"
  resources:
    requests:
      cpu: 100m
      memory: 128Mi

# New values are optional
operator:
  image:
    tag: "1.0.0"
    digest: "sha256:abc123def456..."  # Optional
  resources:
    requests:
      cpu: 200m  # Updated default
      memory: 256Mi  # Updated default
  metrics:
    enabled: true  # New default
```

### Breaking Changes

**v1.0.0 Breaking Changes:**
- Minimum Kubernetes version: 1.24+
- Minimum Helm version: 3.8+
- RBAC preset changes
- Default resource limits increased

**Migration Required:**
- Update Kubernetes cluster
- Update Helm version
- Review RBAC configuration
- Adjust resource limits

## Rollback Procedures

### Helm Rollback

**Rollback Process:**
```bash
# Check upgrade history
helm history ansible-playbook-operator -n ansible-operator-system

# Rollback to previous version
helm rollback ansible-playbook-operator 1 -n ansible-operator-system

# Verify rollback
kubectl get pods -n ansible-operator-system
kubectl get crd | grep ansible.cloud37.dev
```

**Rollback Verification:**
```bash
# Check operator status
kubectl get pods -n ansible-operator-system

# Check operator logs
kubectl logs -n ansible-operator-system deployment/ansible-playbook-operator

# Verify resource status
kubectl get repositories,playbooks,schedules --all-namespaces
```

### CRD Rollback

**CRD Rollback Process:**
```bash
# 1. Rollback Helm chart
helm rollback ansible-playbook-operator 1 -n ansible-operator-system

# 2. Apply previous CRD version
kubectl apply -f helm/ansible-playbook-operator/crds/

# 3. Verify CRD rollback
kubectl get crd playbooks.ansible.cloud37.dev -o jsonpath='{.spec.versions[*].name}'

# 4. Check resource status
kubectl get playbooks --all-namespaces
```

### Resource Rollback

**Resource Rollback:**
```bash
# Restore from backup
kubectl apply -f backup.yaml

# Verify resource restoration
kubectl get repositories,playbooks,schedules --all-namespaces

# Check resource status
kubectl get playbook my-playbook -o yaml
```

## Migration Strategies

### Blue-Green Migration

**Strategy:**
1. Deploy new version in parallel
2. Migrate resources gradually
3. Switch traffic to new version
4. Decommission old version

**Implementation:**
```bash
# 1. Deploy new version
helm install ansible-playbook-operator-v2 ./helm/ansible-playbook-operator \
  --namespace ansible-operator-system-v2 \
  --create-namespace \
  --version 1.0.0

# 2. Migrate resources
kubectl get playbooks --all-namespaces -o yaml | \
  sed 's/ansible-operator-system/ansible-operator-system-v2/g' | \
  kubectl apply -f -

# 3. Verify migration
kubectl get playbooks -n ansible-operator-system-v2

# 4. Switch traffic
# Update resource references to new namespace

# 5. Decommission old version
helm uninstall ansible-playbook-operator -n ansible-operator-system
```

### Rolling Migration

**Strategy:**
1. Upgrade operator in place
2. Migrate resources automatically
3. Verify functionality
4. Complete migration

**Implementation:**
```bash
# 1. Upgrade operator
helm upgrade ansible-playbook-operator ./helm/ansible-playbook-operator \
  --namespace ansible-operator-system \
  --version 1.0.0

# 2. Monitor migration
kubectl get pods -n ansible-operator-system
kubectl get events --field-selector involvedObject.kind=Playbook

# 3. Verify functionality
kubectl get playbooks --all-namespaces
kubectl get schedules --all-namespaces

# 4. Complete migration
# No additional steps required
```

### Canary Migration

**Strategy:**
1. Deploy new version for subset of resources
2. Monitor performance and functionality
3. Gradually increase traffic
4. Complete migration

**Implementation:**
```bash
# 1. Deploy new version
helm install ansible-playbook-operator-canary ./helm/ansible-playbook-operator \
  --namespace ansible-operator-system-canary \
  --create-namespace \
  --version 1.0.0

# 2. Migrate subset of resources
kubectl get playbooks -n production -o yaml | \
  sed 's/ansible-operator-system/ansible-operator-system-canary/g' | \
  kubectl apply -f -

# 3. Monitor performance
kubectl get pods -n ansible-operator-system-canary
kubectl logs -n ansible-operator-system-canary deployment/ansible-playbook-operator

# 4. Gradually increase traffic
# Migrate more resources as confidence grows

# 5. Complete migration
# Migrate all remaining resources
```

## Testing Upgrades

### Pre-Upgrade Testing

**Test Environment Setup:**
```bash
# Create test namespace
kubectl create namespace ansible-operator-test

# Deploy current version
helm install ansible-playbook-operator-test ./helm/ansible-playbook-operator \
  --namespace ansible-operator-test \
  --version 0.1.2

# Create test resources
kubectl apply -f examples/playbook-basic.yaml -n ansible-operator-test
```

**Upgrade Testing:**
```bash
# Upgrade to new version
helm upgrade ansible-playbook-operator-test ./helm/ansible-playbook-operator \
  --namespace ansible-operator-test \
  --version 1.0.0

# Verify upgrade
kubectl get pods -n ansible-operator-test
kubectl get playbooks -n ansible-operator-test

# Test functionality
kubectl get events --field-selector involvedObject.kind=Playbook
```

### Post-Upgrade Testing

**Functionality Tests:**
```bash
# Test resource creation
kubectl apply -f examples/playbook-basic.yaml

# Test resource updates
kubectl patch playbook my-playbook -p '{"spec":{"playbookPath":"new-path.yml"}}'

# Test resource deletion
kubectl delete playbook my-playbook

# Test schedule execution
kubectl get cronjobs
kubectl get jobs
```

**Performance Tests:**
```bash
# Test reconciliation performance
kubectl get events --field-selector involvedObject.kind=Repository

# Test job execution performance
kubectl get jobs -l ansible.cloud37.dev/managed-by=ansible-operator

# Test resource status updates
kubectl get playbooks -o jsonpath='{.status.conditions}'
```

## Troubleshooting Upgrades

### Common Issues

**Upgrade Failures:**
```bash
# Check upgrade status
helm status ansible-playbook-operator -n ansible-operator-system

# Check operator logs
kubectl logs -n ansible-operator-system deployment/ansible-playbook-operator

# Check resource status
kubectl get repositories,playbooks,schedules --all-namespaces
```

**CRD Migration Issues:**
```bash
# Check CRD status
kubectl get crd playbooks.ansible.cloud37.dev -o yaml

# Check resource status
kubectl get playbooks --all-namespaces

# Check for migration errors
kubectl get events --field-selector reason=MigrationFailed
```

**Resource Status Issues:**
```bash
# Check resource conditions
kubectl get playbook my-playbook -o jsonpath='{.status.conditions}'

# Check resource events
kubectl get events --field-selector involvedObject.name=my-playbook

# Check operator logs
kubectl logs -n ansible-operator-system deployment/ansible-playbook-operator | grep "my-playbook"
```

### Recovery Procedures

**Failed Upgrade Recovery:**
```bash
# 1. Rollback Helm chart
helm rollback ansible-playbook-operator 1 -n ansible-operator-system

# 2. Verify rollback
kubectl get pods -n ansible-operator-system

# 3. Check resource status
kubectl get repositories,playbooks,schedules --all-namespaces

# 4. Investigate failure
kubectl logs -n ansible-operator-system deployment/ansible-playbook-operator
```

**Resource Migration Recovery:**
```bash
# 1. Check resource status
kubectl get playbooks --all-namespaces

# 2. Restore from backup
kubectl apply -f backup.yaml

# 3. Verify restoration
kubectl get playbooks --all-namespaces

# 4. Check resource conditions
kubectl get playbook my-playbook -o jsonpath='{.status.conditions}'
```

### Upgrade Checklist

**Pre-Upgrade:**
- [ ] Backup existing resources
- [ ] Review release notes
- [ ] Test in non-production environment
- [ ] Plan migration strategy
- [ ] Schedule maintenance window

**During Upgrade:**
- [ ] Monitor upgrade progress
- [ ] Check operator status
- [ ] Verify resource migration
- [ ] Test functionality
- [ ] Monitor performance

**Post-Upgrade:**
- [ ] Verify all resources
- [ ] Test key functionality
- [ ] Monitor performance
- [ ] Update documentation
- [ ] Communicate success

**Rollback Preparation:**
- [ ] Document rollback procedures
- [ ] Test rollback process
- [ ] Prepare rollback commands
- [ ] Monitor for issues
- [ ] Be ready to rollback
