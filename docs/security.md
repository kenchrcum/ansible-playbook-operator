# Security Best Practices

This guide covers security best practices for deploying and operating the Ansible Playbook Operator.

## Table of Contents

- [Security Overview](#security-overview)
- [Authentication Security](#authentication-security)
- [RBAC Security](#rbac-security)
- [Network Security](#network-security)
- [Image Security](#image-security)
- [Secret Management](#secret-management)
- [Pod Security](#pod-security)
- [Monitoring Security](#monitoring-security)
- [Compliance](#compliance)

## Security Overview

The Ansible Playbook Operator implements security-by-default principles:

- **Least Privilege**: Minimal RBAC permissions by default
- **Secure Defaults**: Hardened pod security contexts
- **Secret Protection**: No secrets in logs or events
- **Network Isolation**: Optional NetworkPolicies
- **Image Pinning**: Digest-based image verification

## Authentication Security

### SSH Key Management

**Best Practices:**
1. Use OpenSSH format keys
2. Rotate keys regularly
3. Use dedicated keys per environment
4. Store keys in Kubernetes Secrets

**Key Format:**
```bash
# Generate OpenSSH format key
ssh-keygen -t ed25519 -C "ansible-operator@company.com"

# Verify key format
head -1 ~/.ssh/id_ed25519
# Should output: -----BEGIN OPENSSH PRIVATE KEY-----
```

**Secret Storage:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: ssh-key
type: kubernetes.io/ssh-auth
data:
  ssh-privatekey: <base64-encoded-key>
```

### HTTPS Token Security

**Best Practices:**
1. Use Personal Access Tokens (PATs)
2. Limit token scope to minimum required
3. Set token expiration
4. Rotate tokens regularly

**Token Scopes:**
- `repo`: Full repository access
- `read:org`: Read organization membership
- `read:user`: Read user profile

**Secret Storage:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: github-token
type: Opaque
data:
  token: <base64-encoded-token>
```

### Known Hosts Pinning

**Best Practices:**
1. Pin SSH host keys
2. Use ConfigMaps for known_hosts
3. Enable strict host key checking
4. Update known_hosts regularly

**Configuration:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: github-known-hosts
data:
  known_hosts: |
    github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl
    github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Ue1gvwnGLVlOhGeYrnZaMgRK6+PKCUXaDbC7qtbW8gIkhL7aGCsOr/C56SJMy/BCZfxd1nWzAOxSDPgVsmerOBYfNqltV9/hWCqBywINIR+5dIg6JTJ72pcEpEjcYgXkE2YEFXV1JHnsKgbLWNlhScqb2UmyRkQyytRLtL+38TGxkxCflmO+5Z8CSSNY7GidjMIZ7Q4zMjA2n1nGrlTDkzwDCsw+wqFPGQA179cnfGWOWRVruj16z6XyvxvjJwbz0wQZ75XK5tKSb7FNyeIEs4TT4jk+S4dhPeAUC5y+bDYirYgM4GC7uEnztnZyaVWQ7B381AK4Qdrwt51ZqExKbQpTUNn+EjqoTwvqNj4kqx5QUCI0ThS/YkOxJCXmPUWZbhjpCg56i+2aB6CmK2JGhn57K5mj0MNdBXA4/WnwH6XoPWJzK5Nyu2zB3nOverA8J+7WcmWQM9UQS0Q==
```

**Repository Configuration:**
```yaml
apiVersion: ansible.cloud37.dev/v1alpha1
kind: Repository
metadata:
  name: secure-repo
spec:
  url: git@github.com:company/repo.git
  auth:
    method: ssh
    secretRef:
      name: ssh-key
  ssh:
    strictHostKeyChecking: true
    knownHostsConfigMapRef:
      name: github-known-hosts
```

## RBAC Security

### Preset Selection

**Minimal Preset (Recommended):**
```yaml
rbac:
  preset: minimal
  clusterRead: true
```

**Scoped Preset:**
```yaml
rbac:
  preset: scoped
```

**Cluster-Admin Preset (Use with Caution):**
```yaml
rbac:
  preset: cluster-admin
```

### Secret Access Restriction

**Enable Secret Restriction:**
```yaml
rbac:
  secretRestriction:
    enabled: true
    allowedSecrets:
      - github-token
      - ssh-key
      - vault-password
```

**Cross-Namespace Secrets:**
```yaml
rbac:
  secretRestriction:
    enabled: true
    crossNamespaceSecrets:
      shared-namespace:
        - shared-secret
      prod-namespace:
        - prod-secret
```

### Executor ServiceAccount

**Separate Executor Identity:**
```yaml
executorDefaults:
  serviceAccount:
    create: true
    rbacPreset: minimal
```

**Benefits:**
- Security isolation
- Minimal permissions
- Audit trail
- Configurable RBAC

## Network Security

### NetworkPolicies

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

### Egress Rules

**Git Traffic:**
- Port 22 (SSH)
- Port 443 (HTTPS)
- Port 9418 (Git protocol)

**Registry Traffic:**
- Port 443 (HTTPS)
- Port 80 (HTTP)

**DNS Resolution:**
- Port 53 (UDP/TCP)

## Image Security

### Image Pinning

**Pin by Digest:**
```yaml
operator:
  image:
    repository: kenchrcum/ansible-playbook-operator
    digest: "sha256:abc123def456..."

executorDefaults:
  image:
    repository: kenchrcum/ansible-runner
    digest: "sha256:def456ghi789..."
```

**Benefits:**
- Reproducible deployments
- Prevents image tampering
- Enhances security posture

### Image Scanning

**Scan Images:**
```bash
# Using Trivy
trivy image kenchrcum/ansible-playbook-operator:0.1.3

# Using Grype
grype kenchrcum/ansible-playbook-operator:0.1.3
```

**CI/CD Integration:**
```yaml
# GitHub Actions example
- name: Scan image
  uses: aquasecurity/trivy-action@master
  with:
    image-ref: 'kenchrcum/ansible-playbook-operator:${{ github.sha }}'
    format: 'sarif'
    output: 'trivy-results.sarif'
```

## Secret Management

### Secret Types

**SSH Keys:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: ssh-key
type: kubernetes.io/ssh-auth
data:
  ssh-privatekey: <base64-encoded-key>
```

**Tokens:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: github-token
type: Opaque
data:
  token: <base64-encoded-token>
```

**Vault Passwords:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: vault-password
type: Opaque
data:
  password: <base64-encoded-password>
```

### Secret Rotation

**Automated Rotation:**
1. Use external secret management
2. Implement rotation policies
3. Update Secrets regularly
4. Monitor secret age

**Manual Rotation:**
```bash
# Update SSH key
kubectl create secret generic ssh-key-new --from-file=ssh-privatekey=~/.ssh/id_ed25519 --dry-run=client -o yaml | kubectl apply -f -

# Update Repository reference
kubectl patch repository my-repo -p '{"spec":{"auth":{"secretRef":{"name":"ssh-key-new"}}}}'

# Delete old secret
kubectl delete secret ssh-key
```

## Pod Security

### Security Contexts

**Operator Security Context:**
```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
```

**Executor Security Context:**
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

### Pod Security Standards

**Restricted Level:**
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: ansible-operator-system
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

**Benefits:**
- Enforces security policies
- Prevents privilege escalation
- Restricts host access
- Limits capabilities

## Monitoring Security

### Security Events

**Monitor Authentication Failures:**
```bash
kubectl get events --field-selector reason=ValidateFailed
```

**Monitor RBAC Denials:**
```bash
kubectl get events --field-selector reason=Forbidden
```

**Monitor Secret Access:**
```bash
kubectl get events --field-selector involvedObject.kind=Secret
```

### Audit Logging

**Enable Audit Logging:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: audit-policy
data:
  policy.yaml: |
    apiVersion: audit.k8s.io/v1
    kind: Policy
    rules:
    - level: Metadata
      resources:
      - group: ""
        resources: ["secrets"]
    - level: RequestResponse
      resources:
      - group: "ansible.cloud37.dev"
        resources: ["*"]
```

### Security Metrics

**Prometheus Metrics:**
- `ansible_operator_reconcile_total{result="error"}`
- `ansible_operator_job_runs_total{result="failure"}`

**Alerting Rules:**
```yaml
groups:
- name: ansible-operator-security
  rules:
  - alert: AuthenticationFailures
    expr: rate(ansible_operator_reconcile_total{result="error"}[5m]) > 0.1
    labels:
      severity: warning
    annotations:
      summary: "High rate of authentication failures"
```

## Compliance

### CIS Kubernetes Benchmark

**Compliance Checklist:**
- [ ] Use non-root containers
- [ ] Drop all capabilities
- [ ] Use read-only root filesystem
- [ ] Enable seccomp profiles
- [ ] Implement NetworkPolicies
- [ ] Use RBAC
- [ ] Pin container images
- [ ] Enable audit logging

### SOC 2 Compliance

**Security Controls:**
- Access control (RBAC)
- Data encryption (Secrets)
- Network security (NetworkPolicies)
- Monitoring (Metrics, Events)
- Incident response (Troubleshooting)

### GDPR Compliance

**Data Protection:**
- Minimize data collection
- Encrypt sensitive data
- Implement data retention
- Provide data deletion

## Security Checklist

### Pre-Deployment

- [ ] Review RBAC permissions
- [ ] Configure NetworkPolicies
- [ ] Pin container images
- [ ] Enable secret restrictions
- [ ] Set up monitoring

### Post-Deployment

- [ ] Verify security contexts
- [ ] Test network isolation
- [ ] Monitor security events
- [ ] Review audit logs
- [ ] Update security policies

### Ongoing Maintenance

- [ ] Rotate secrets regularly
- [ ] Update container images
- [ ] Review RBAC permissions
- [ ] Monitor security metrics
- [ ] Conduct security audits

## Security Incident Response

### Incident Detection

**Indicators:**
- Authentication failures
- RBAC denials
- Network anomalies
- Unusual resource usage

**Response Steps:**
1. Isolate affected resources
2. Investigate root cause
3. Implement remediation
4. Update security policies
5. Document lessons learned

### Recovery Procedures

**Secret Compromise:**
1. Rotate compromised secrets
2. Update all references
3. Monitor for abuse
4. Review access logs

**Container Compromise:**
1. Stop affected pods
2. Investigate container
3. Update base images
4. Redeploy with fixes

## Security Resources

### Documentation
- [Kubernetes Security](https://kubernetes.io/docs/concepts/security/)
- [Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
- [Network Policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/)

### Tools
- [Trivy](https://trivy.dev/) - Container vulnerability scanner
- [Grype](https://github.com/anchore/grype) - Vulnerability scanner
- [Falco](https://falco.org/) - Runtime security monitoring

### Standards
- [CIS Kubernetes Benchmark](https://www.cisecurity.org/benchmark/kubernetes)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)
- [OWASP Container Security](https://owasp.org/www-project-container-security/)
