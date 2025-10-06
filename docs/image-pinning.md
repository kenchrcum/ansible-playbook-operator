# Image Pinning and Security

This document describes the image pinning capabilities of the Ansible Playbook Operator, which provides enhanced security and reproducibility by pinning container images to specific digests.

## Overview

Image pinning ensures that your deployments use exact, immutable container images rather than tags that can change over time. This provides several benefits:

- **Security**: Prevents supply chain attacks by ensuring you get the exact image you tested
- **Reproducibility**: Guarantees identical deployments across environments
- **Compliance**: Meets security requirements for immutable infrastructure
- **Auditability**: Provides clear traceability of deployed images

## Supported Images

The operator supports digest pinning for two types of images:

1. **Operator Image**: The main operator container (`kenchrcum/ansible-playbook-operator`)
2. **Executor Images**: Default executor containers (`kenchrcum/ansible-runner`)

## Configuration

### Helm Values Configuration

Image pinning is configured through Helm values in the `values.yaml` file:

```yaml
operator:
  image:
    repository: kenchrcum/ansible-playbook-operator
    tag: "0.1.1"
    # Optional: pin image by digest for enhanced security and reproducibility
    # When digest is provided, it takes precedence over tag
    # Format: sha256:abc123def456...
    digest: ""

executorDefaults:
  image:
    repository: kenchrcum/ansible-runner
    tag: 13
    # Optional: pin image by digest for enhanced security and reproducibility
    # When digest is provided, it takes precedence over tag
    # Format: sha256:abc123def456...
    digest: ""
```

### Image Reference Format

When a digest is provided, the image reference format changes from:
- `repository:tag` (e.g., `kenchrcum/ansible-runner:latest`)
- `repository@digest` (e.g., `kenchrcum/ansible-runner@sha256:abc123def456...`)

The digest takes precedence over the tag when both are specified.

## Usage Examples

### Basic Usage with Digest Pinning

```yaml
# values.yaml
operator:
  image:
    repository: kenchrcum/ansible-playbook-operator
    digest: "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"

executorDefaults:
  image:
    repository: kenchrcum/ansible-runner
    digest: "sha256:abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
```

### Mixed Configuration (Tag + Digest)

```yaml
# values.yaml
operator:
  image:
    repository: kenchrcum/ansible-playbook-operator
    tag: "0.1.1"  # Ignored when digest is present
    digest: "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"

executorDefaults:
  image:
    repository: kenchrcum/ansible-runner
    tag: 13    # Ignored when digest is present
    digest: "sha256:abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
```

### Fallback to Tags

```yaml
# values.yaml
operator:
  image:
    repository: kenchrcum/ansible-playbook-operator
    tag: "0.1.1"
    digest: ""  # Empty digest falls back to tag

executorDefaults:
  image:
    repository: kenchrcum/ansible-runner
    tag: 13
    digest: ""  # Empty digest falls back to tag
```

## Obtaining Image Digests

### Using Docker CLI

```bash
# Pull the image and inspect
docker pull kenchrcum/ansible-playbook-operator:0.1.1
docker inspect kenchrcum/ansible-playbook-operator:0.1.1 | grep -i digest

# Or use docker manifest
docker manifest inspect kenchrcum/ansible-playbook-operator:0.1.1
```

### Using Crane (Google's Container Registry Tool)

```bash
# Install crane
go install github.com/google/go-containerregistry/cmd/crane@latest

# Get digest
crane digest kenchrcum/ansible-playbook-operator:0.1.1
```

### Using Skopeo

```bash
# Install skopeo
# Ubuntu/Debian: apt install skopeo
# RHEL/CentOS: yum install skopeo

# Get digest
skopeo inspect docker://kenchrcum/ansible-playbook-operator:0.1.1
```

## Upgrade Flow

### Planning Upgrades

1. **Test New Images**: Always test new images in a non-production environment first
2. **Obtain Digests**: Get the digest of the new image version you want to deploy
3. **Update Values**: Update your Helm values with the new digest
4. **Deploy**: Apply the updated configuration

### Step-by-Step Upgrade Process

```bash
# 1. Get the digest of the new image
NEW_DIGEST=$(crane digest kenchrcum/ansible-playbook-operator:0.2.0)
echo "New digest: $NEW_DIGEST"

# 2. Update your values file
cat > values-upgrade.yaml << EOF
operator:
  image:
    repository: kenchrcum/ansible-playbook-operator
    digest: "$NEW_DIGEST"

executorDefaults:
  image:
    repository: kenchrcum/ansible-runner
    digest: "sha256:your-executor-digest-here"
EOF

# 3. Upgrade the Helm release
helm upgrade ansible-operator ./helm/ansible-playbook-operator \
  --values values-upgrade.yaml \
  --namespace ansible-operator-system

# 4. Verify the upgrade
kubectl get pods -n ansible-operator-system
kubectl describe pod -l app.kubernetes.io/name=ansible-playbook-operator -n ansible-operator-system
```

### Rollback Process

```bash
# 1. Revert to previous digest
cat > values-rollback.yaml << EOF
operator:
  image:
    repository: kenchrcum/ansible-playbook-operator
    digest: "sha256:previous-digest-here"
EOF

# 2. Rollback the Helm release
helm upgrade ansible-operator ./helm/ansible-playbook-operator \
  --values values-rollback.yaml \
  --namespace ansible-operator-system

# 3. Verify rollback
kubectl get pods -n ansible-operator-system
```

## Security Considerations

### Supply Chain Security

- **Immutable Images**: Digests ensure you get the exact image you tested
- **Tamper Detection**: Any modification to the image results in a different digest
- **Audit Trail**: Digests provide clear traceability of deployed images

### Best Practices

1. **Pin All Images**: Use digest pinning for both operator and executor images
2. **Regular Updates**: Regularly update to new digests after testing
3. **Version Control**: Store digest values in version control for auditability
4. **Testing**: Always test new digests in non-production environments first

### Compliance Requirements

Many compliance frameworks require image pinning:

- **SOC 2**: Immutable infrastructure requirements
- **PCI DSS**: Secure software development practices
- **HIPAA**: Audit trail requirements
- **FedRAMP**: Supply chain security requirements

## Troubleshooting

### Common Issues

#### Image Pull Errors

```bash
# Error: failed to pull image
# Solution: Verify the digest is correct and accessible
crane digest kenchrcum/ansible-playbook-operator:0.1.1
```

#### Digest Format Errors

```bash
# Error: invalid digest format
# Solution: Ensure digest starts with 'sha256:'
digest: "sha256:1234567890abcdef..."  # Correct
digest: "1234567890abcdef..."         # Incorrect
```

#### Registry Access Issues

```bash
# Error: unauthorized access
# Solution: Configure image pull secrets
kubectl create secret docker-registry regcred \
  --docker-server=your-registry.com \
  --docker-username=your-username \
  --docker-password=your-password \
  --docker-email=your-email@example.com
```

### Verification Commands

```bash
# Check deployed image
kubectl get pods -n ansible-operator-system -o jsonpath='{.items[0].spec.containers[0].image}'

# Verify digest format
kubectl get pods -n ansible-operator-system -o jsonpath='{.items[0].spec.containers[0].image}' | grep -E 'sha256:[a-f0-9]{64}'

# Check image pull policy
kubectl get pods -n ansible-operator-system -o jsonpath='{.items[0].spec.containers[0].imagePullPolicy}'
```

## CI/CD Integration

### Automated Digest Updates

```yaml
# GitHub Actions example
name: Update Image Digests
on:
  schedule:
    - cron: '0 0 * * 1'  # Weekly

jobs:
  update-digests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Get latest digest
        id: get-digest
        run: |
          DIGEST=$(crane digest kenchrcum/ansible-playbook-operator:latest)
          echo "digest=$DIGEST" >> $GITHUB_OUTPUT
      - name: Update values
        run: |
          sed -i "s/digest: .*/digest: \"${{ steps.get-digest.outputs.digest }}\"/" helm/ansible-playbook-operator/values.yaml
      - name: Create PR
        uses: peter-evans/create-pull-request@v5
        with:
          commit-message: "chore: update operator image digest"
          title: "Update operator image digest"
          body: "Automated update of operator image digest to ${{ steps.get-digest.outputs.digest }}"
```

### Release Automation

```yaml
# Release workflow
name: Release
on:
  push:
    tags:
      - 'v*'

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Build and push
        run: |
          docker build -t kenchrcum/ansible-playbook-operator:${{ github.ref_name }} .
          docker push kenchrcum/ansible-playbook-operator:${{ github.ref_name }}
      - name: Get digest
        id: get-digest
        run: |
          DIGEST=$(crane digest kenchrcum/ansible-playbook-operator:${{ github.ref_name }})
          echo "digest=$DIGEST" >> $GITHUB_OUTPUT
      - name: Update release notes
        run: |
          echo "Image digest: ${{ steps.get-digest.outputs.digest }}" >> release-notes.md
```

## Migration Guide

### From Tag-Based to Digest-Based

1. **Identify Current Images**: Get the current image references
2. **Obtain Digests**: Get digests for current images
3. **Update Configuration**: Add digest fields to values.yaml
4. **Test Deployment**: Deploy and verify functionality
5. **Update Documentation**: Update your deployment documentation

### Example Migration

```bash
# 1. Get current image
kubectl get pods -n ansible-operator-system -o jsonpath='{.items[0].spec.containers[0].image}'
# Output: kenchrcum/ansible-playbook-operator:0.1.1

# 2. Get digest for current image
CURRENT_DIGEST=$(crane digest kenchrcum/ansible-playbook-operator:0.1.1)
echo "Current digest: $CURRENT_DIGEST"

# 3. Update values.yaml
cat >> values.yaml << EOF
operator:
  image:
    repository: kenchrcum/ansible-playbook-operator
    tag: "0.1.1"
    digest: "$CURRENT_DIGEST"
EOF

# 4. Apply changes
helm upgrade ansible-operator ./helm/ansible-playbook-operator \
  --values values.yaml \
  --namespace ansible-operator-system
```

## References

- [Docker Image Digests](https://docs.docker.com/engine/reference/commandline/images/#list-image-digests)
- [Kubernetes Image Pull Policies](https://kubernetes.io/docs/concepts/containers/images/#image-pull-policy)
- [Helm Values](https://helm.sh/docs/chart_template_guide/values_files/)
- [Container Security Best Practices](https://kubernetes.io/docs/concepts/security/container-security/)
