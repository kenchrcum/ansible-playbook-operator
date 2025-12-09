# Image Pinning Strategy

This document outlines the recommended approach for pinning container images by digest for production deployments of the Ansible Playbook Operator.

## Overview

Image pinning by digest provides:
- **Security**: Prevents supply chain attacks by ensuring exact image versions
- **Reproducibility**: Guarantees identical deployments across environments
- **Stability**: Eliminates unexpected changes from tag updates
- **Compliance**: Meets security requirements for production environments

## How It Works

The Helm chart supports digest pinning through the `digest` field in image configurations:

```yaml
operator:
  image:
    repository: kenchrcum/ansible-playbook-operator
    tag: "0.1.4"
    digest: "sha256:abc123def456..."  # Takes precedence over tag
    pullPolicy: IfNotPresent

executorDefaults:
  image:
    repository: kenchrcum/ansible-runner
    tag: 13
    digest: "sha256:def456abc123..."  # Takes precedence over tag
    pullPolicy: IfNotPresent
```

**Important**: When `digest` is provided, it takes precedence over `tag`. The `tag` field is ignored and can be left for documentation purposes.

## Getting Image Digests

### Method 1: Docker CLI
```bash
# Get digest for operator image
docker pull kenchrcum/ansible-playbook-operator:0.1.4
docker inspect kenchrcum/ansible-playbook-operator:0.1.4 | jq -r '.[0].RepoDigests[0]'

# Get digest for executor image
docker pull kenchrcum/ansible-runner:latest
docker inspect kenchrcum/ansible-runner:latest | jq -r '.[0].RepoDigests[0]'
```

### Method 2: Registry API
```bash
# Get digest from registry manifest
curl -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
  https://registry-1.docker.io/v2/kenchrcum/ansible-playbook-operator/manifests/0.1.4 | \
  jq -r '.config.digest'
```

### Method 3: Using crane (Google's container tool)
```bash
# Install crane
go install github.com/google/go-containerregistry/cmd/crane@latest

# Get digest
crane digest kenchrcum/ansible-playbook-operator:0.1.4
crane digest kenchrcum/ansible-runner:latest
```

## Production Deployment Strategy

### 1. Development Phase
- Use tag-based images for development and testing
- Test thoroughly with latest images
- Document any issues or incompatibilities

### 2. Staging Phase
- Pin images by digest for staging environment
- Validate all functionality with pinned images
- Performance test with production-like workloads

### 3. Production Phase
- Deploy with digest-pinned images
- Monitor for any issues
- Document digest values for audit purposes

## Example Configurations

### Basic Digest Pinning
```yaml
# examples/values-image-pinning.yaml
operator:
  image:
    repository: kenchrcum/ansible-playbook-operator
    tag: "0.1.4"
    digest: "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
    pullPolicy: IfNotPresent

executorDefaults:
  image:
    repository: kenchrcum/ansible-runner
    tag: 13
    digest: "sha256:abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
    pullPolicy: IfNotPresent
```

### Production-Ready Configuration
```yaml
# examples/values-production-pinning.yaml
operator:
  image:
    repository: kenchrcum/ansible-playbook-operator
    tag: "0.1.4"
    digest: "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
    pullPolicy: IfNotPresent
  resources:
    requests:
      cpu: 200m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 1Gi

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
```

### Mixed Pinning Strategy
```yaml
# examples/values-mixed-pinning.yaml
# Pin critical components, use tags for less critical ones
operator:
  image:
    repository: kenchrcum/ansible-playbook-operator
    tag: "0.1.4"
    digest: "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
    pullPolicy: IfNotPresent

executorDefaults:
  image:
    repository: kenchrcum/ansible-runner
    tag: 13
    digest: ""  # Empty digest falls back to tag
    pullPolicy: IfNotPresent
```

## Automation and CI/CD Integration

### Automated Digest Updates
Create a script to automatically update digests in your values files:

```bash
#!/bin/bash
# update-image-digests.sh

OPERATOR_DIGEST=$(crane digest kenchrcum/ansible-playbook-operator:0.1.4)
EXECUTOR_DIGEST=$(crane digest kenchrcum/ansible-runner:latest)

# Update values files
sed -i "s/digest: \".*\"/digest: \"$OPERATOR_DIGEST\"/" examples/values-image-pinning.yaml
sed -i "s/digest: \".*\"/digest: \"$EXECUTOR_DIGEST\"/" examples/values-image-pinning.yaml

echo "Updated digests:"
echo "Operator: $OPERATOR_DIGEST"
echo "Executor: $EXECUTOR_DIGEST"
```

### GitOps Integration
1. Store digest values in Git
2. Use automated tools to update digests
3. Require manual approval for production deployments
4. Maintain audit trail of all changes

## Security Considerations

### Supply Chain Security
- **Verify digests**: Always verify digests from trusted sources
- **Monitor updates**: Set up alerts for new image versions
- **Scan images**: Use tools like Trivy or Grype to scan pinned images
- **Regular updates**: Plan regular updates to get security patches

### Access Control
- **Registry access**: Ensure secure access to container registries
- **Network policies**: Implement network policies to restrict registry access
- **RBAC**: Use appropriate RBAC for image pulling

### Compliance
- **Audit trails**: Maintain records of all image deployments
- **Vulnerability scanning**: Regularly scan pinned images for vulnerabilities
- **Policy enforcement**: Implement policies requiring digest pinning

## Troubleshooting

### Common Issues

#### 1. Digest Not Found
```
Error: failed to pull image: manifest unknown
```
**Solution**: Verify the digest is correct and the image exists in the registry.

#### 2. Digest Mismatch
```
Error: digest verification failed
```
**Solution**: Ensure the digest matches the exact image version you want to deploy.

#### 3. Registry Access Issues
```
Error: failed to pull image: unauthorized
```
**Solution**: Check registry credentials and network policies.

### Debug Commands
```bash
# Verify digest exists
crane digest kenchrcum/ansible-playbook-operator:0.1.4

# Check image manifest
crane manifest kenchrcum/ansible-playbook-operator@sha256:1234567890abcdef...

# Test image pull
docker pull kenchrcum/ansible-playbook-operator@sha256:1234567890abcdef...
```

## Best Practices

### 1. Documentation
- Document all digest values in your deployment manifests
- Maintain a changelog of image updates
- Include digest information in your release notes

### 2. Testing
- Test digest-pinned images in staging before production
- Validate all functionality with pinned images
- Performance test with production-like workloads

### 3. Monitoring
- Monitor for image pull failures
- Set up alerts for digest verification failures
- Track image update frequencies

### 4. Maintenance
- Plan regular updates for security patches
- Maintain a schedule for image updates
- Document rollback procedures

## Migration Guide

### From Tag-Based to Digest-Based

1. **Identify current images**:
   ```bash
   kubectl get deployment ansible-playbook-operator -o yaml | grep image:
   ```

2. **Get current digests**:
   ```bash
   crane digest kenchrcum/ansible-playbook-operator:0.1.4
   crane digest kenchrcum/ansible-runner:latest
   ```

3. **Update values file**:
   ```yaml
   operator:
     image:
       repository: kenchrcum/ansible-playbook-operator
       tag: "0.1.4"
       digest: "sha256:1234567890abcdef..."
   ```

4. **Deploy and verify**:
   ```bash
   helm upgrade ansible-playbook-operator ./helm/ansible-playbook-operator \
     --values values-image-pinning.yaml
   ```

5. **Monitor deployment**:
   ```bash
   kubectl rollout status deployment/ansible-playbook-operator
   kubectl logs -l app.kubernetes.io/name=ansible-playbook-operator
   ```

## References

- [Docker Image Digests](https://docs.docker.com/engine/reference/commandline/images/#list-image-digests)
- [Kubernetes Image Pull Policies](https://kubernetes.io/docs/concepts/containers/images/#updating-images)
- [Helm Image Configuration](https://helm.sh/docs/chart_template_guide/builtin_objects/)
- [Container Security Best Practices](https://kubernetes.io/docs/concepts/security/)
