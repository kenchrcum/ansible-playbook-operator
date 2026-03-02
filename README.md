# Ansible Playbook Operator

[![AI Assisted](https://img.shields.io/badge/AI-Assisted_Development-blueviolet)](AI_DISCLAIMER.md)
![Version](https://img.shields.io/badge/version-0.1.6-blue.svg)
[![License](https://img.shields.io/badge/license-Unlicense-lightgrey.svg)](LICENSE)
[![Artifact Hub](https://img.shields.io/endpoint?url=https://artifacthub.io/badge/repository/ansible-playbook-operator)](https://artifacthub.io/packages/search?repo=ansible-playbook-operator)

A lightweight, GitOps-focused Kubernetes operator for executing Ansible playbooks using the [Kopf](https://kopf.readthedocs.io) framework. Built with security, observability, and operational simplicity as core principles.

## 🎯 Overview

The Ansible Playbook Operator brings Ansible automation directly into your Kubernetes workflows. It enables you to:

- **Manage Ansible playbook execution as Kubernetes resources** through custom CRDs
- **Schedule playbooks** with Kubernetes CronJobs and intelligent random scheduling to avoid thundering herds
- **GitOps integration** with seamless Git repository cloning (SSH/HTTPS/Token auth)
- **Secure by default** with least-privilege RBAC, hardened pod security contexts, and secret injection patterns
- **Observable** with Prometheus metrics, structured logging, and Kubernetes Events

### Key Features

✨ **Three Declarative CRDs**
- `Repository` — Define Git repositories with Ansible content
- `Playbook` — Configure playbook execution environments
- `Schedule` — Schedule playbook runs with CronJobs

🔐 **Security First**
- Non-root containers with read-only root filesystem
- Seccomp RuntimeDefault profile
- Multiple secret injection modes (env vars, files, vault passwords)
- SSH known_hosts pinning for strict host key checking
- RBAC presets: minimal, scoped, and opt-in cluster-admin

⏰ **Smart Scheduling**
- Standard cron expressions supported
- Random schedule macros: `@hourly-random`, `@daily-random`, `@weekly-random`, `@monthly-random`, `@yearly-random`
- Deterministic randomization prevents thundering herds while remaining stable per resource

📊 **Production Ready Observability**
- Prometheus metrics (reconciliation counters, durations)
- Kubernetes Events for lifecycle transitions
- Structured JSON logs with correlation IDs
- Status conditions following Kubernetes conventions

🎨 **Flexible Execution**
- Custom executor images (default: `kenchrcum/ansible-runner`)
- Resource limits, node selectors, tolerations, affinity rules
- Separate executor ServiceAccount with configurable RBAC presets for enhanced security isolation
- Service account override for least-privilege job execution
- Optional PVC-backed cache for `~/.ansible` collections/roles
- Support for secrets, extra vars, inventory paths, and ansible.cfg
- Comprehensive Ansible execution options: tags, check mode, verbosity, timeouts, forks, strategies
- Multiple secret injection modes: environment variables, file mounts, vault passwords

## 📋 Prerequisites

- Kubernetes 1.24+ cluster
- Helm 3.8+
- Optional: Prometheus for metrics collection

## 🚀 Quick Start

### Installation

Install the operator using Helm:

```bash
helm install ansible-playbook-operator ./helm/ansible-playbook-operator \
  --namespace ansible-operator-system \
  --create-namespace
```

**Customize installation:**

```bash
helm install ansible-playbook-operator ./helm/ansible-playbook-operator \
  --namespace ansible-operator-system \
  --create-namespace \
  --set operator.watch.scope=all \
  --set rbac.preset=minimal \
  --set operator.metrics.enabled=true
```

### Basic Example

1. **Create a Repository** pointing to your Ansible Git repository:

```yaml
apiVersion: ansible.cloud37.dev/v1alpha1
kind: Repository
metadata:
  name: my-ansible-repo
spec:
  url: https://github.com/myorg/ansible-repo
  branch: main
  auth:
    method: token
    secretRef:
      name: github-token
```

2. **Define a Playbook** to execute:

```yaml
apiVersion: ansible.cloud37.dev/v1alpha1
kind: Playbook
metadata:
  name: configure-servers
spec:
  repositoryRef:
    name: my-ansible-repo
  playbookPath: playbooks/configure.yml
  inventoryPath: inventory/production
  runtime:
    image: kenchrcum/ansible-runner:latest
    resources:
      requests:
        cpu: 200m
        memory: 256Mi
      limits:
        cpu: 1000m
        memory: 1Gi
```

3. **Schedule the Playbook**:

```yaml
apiVersion: ansible.cloud37.dev/v1alpha1
kind: Schedule
metadata:
  name: daily-config
spec:
  playbookRef:
    name: configure-servers
  schedule: "@daily-random"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 1
  failedJobsHistoryLimit: 3
  ttlSecondsAfterFinished: 3600
```

The operator will create a Kubernetes CronJob that executes your playbook at a deterministic random time each day.

## 📚 Custom Resource Definitions

### Repository

Represents a Git repository containing Ansible content.

**Key Fields:**
- `spec.url` (required) — Git URL (SSH or HTTPS)
- `spec.branch` (default: `main`) — Branch to clone
- `spec.revision` (optional) — Pin to a specific commit SHA
- `spec.auth.method` — Authentication: `ssh`, `https`, or `token`
- `spec.auth.secretRef` — Reference to Secret with credentials
- `spec.ssh.knownHostsConfigMapRef` — ConfigMap with SSH known_hosts
- `spec.ssh.strictHostKeyChecking` (default: `true`) — Enforce host key verification
- `spec.cache.strategy` (default: `none`) — Cache strategy: `none` or `pvc`
- `spec.cache.pvcName` — PVC name for caching when strategy is `pvc`
- `spec.paths` — Customize locations for playbooks, inventory, roles, requirements

**Example: SSH with strict host key checking:**

```yaml
apiVersion: ansible.cloud37.dev/v1alpha1
kind: Repository
metadata:
  name: secure-repo
spec:
  url: git@github.com:myorg/ansible.git
  branch: main
  auth:
    method: ssh
    secretRef:
      name: ssh-key  # type: kubernetes.io/ssh-auth
  ssh:
    knownHostsConfigMapRef:
      name: github-known-hosts
    strictHostKeyChecking: true
  paths:
    playbookDir: playbooks
    inventoryDir: inventory
    requirementsFile: requirements.yml
```

**Example: PVC-backed cache for Ansible collections:**

```yaml
apiVersion: ansible.cloud37.dev/v1alpha1
kind: Repository
metadata:
  name: cached-repo
spec:
  url: https://github.com/myorg/ansible.git
  cache:
    strategy: pvc
    pvcName: ansible-cache-pvc
```

**Status Conditions:**
- `AuthValid` — Credentials validation status
- `CloneReady` — Repository clone readiness
- `Ready` — Overall readiness

### Playbook

Configures an Ansible playbook execution environment.

**Key Fields:**
- `spec.repositoryRef.name` (required) — Reference to Repository
- `spec.playbookPath` (required) — Path to playbook relative to repo root
- `spec.inventoryPath` / `spec.inventoryPaths` — Inventory file(s)
- `spec.ansibleCfgPath` — Custom ansible.cfg location (optional; relative paths resolve under `/workspace/repo`)
- `spec.extraVars` — Extra variables as key-value pairs
- `spec.extraVarsSecretRefs` — Secrets to merge into extra vars
- `spec.execution` — Ansible execution options:
  - `tags`, `skipTags` — Task filtering
  - `checkMode`, `diff`, `step` — Execution modes
  - `verbosity` (0-4) — Output verbosity
  - `limit` — Host targeting
  - `connectionTimeout`, `forks`, `strategy` — Performance tuning
  - `flushCache`, `forceHandlers`, `startAtTask` — Advanced options
- `spec.secrets` — Secret injection configuration:
  - `env` — Explicit environment variable mappings
  - `envFromSecretRefs` — Import all keys from Secrets
  - `fileMounts` — Mount secrets as files
  - `vaultPasswordSecretRef` — Ansible Vault password
- `spec.runtime` — Execution configuration:
  - `image` — Custom executor image
  - `serviceAccountName` — Override service account
  - `resources`, `nodeSelector`, `tolerations`, `affinity`
  - `securityContext`, `podSecurityContext`

**Example: Playbook with execution options, secrets, vault, and custom ansible.cfg:**

```yaml
apiVersion: ansible.cloud37.dev/v1alpha1
kind: Playbook
metadata:
  name: deploy-app
spec:
  repositoryRef:
    name: my-ansible-repo
  playbookPath: playbooks/deploy.yml
  inventoryPath: inventory/production
  ansibleCfgPath: ansible-prod.cfg  # Relative path: /workspace/repo/ansible-prod.cfg
  # ansibleCfgPath: /custom/path/ansible.cfg  # Absolute path used as-is
  # Omit ansibleCfgPath to use in-repo ansible.cfg at /workspace/repo/ansible.cfg
  extraVars:
    app_version: "1.2.3"
    environment: production
  execution:
    tags: ["deploy", "web"]
    skipTags: ["test"]
    checkMode: false
    diff: true
    verbosity: 2
    limit: "web_servers:&production"
    connectionTimeout: 30
    forks: 10
    strategy: "free"
  secrets:
    env:
      - envVarName: DB_PASSWORD
        secretRef:
          name: db-creds
          key: password
    fileMounts:
      - secretRef:
          name: ssl-certs
        mountPath: /ssl-certs
        items:
          - key: cert.pem
            path: cert.pem
          - key: key.pem
            path: key.pem
    vaultPasswordSecretRef:
      name: vault-pass
      key: password
  runtime:
    image: kenchrcum/ansible-runner:latest
    serviceAccountName: ansible-deployer
    resources:
      requests:
        cpu: 500m
        memory: 512Mi
```

**Status Conditions:**
- `Ready` — Validation and reference checks
- `InvalidPath` — Path validation failures
- `RepoNotReady` — Referenced Repository not ready

### Schedule

Schedules periodic Playbook execution via Kubernetes CronJobs.

**Key Fields:**
- `spec.playbookRef.name` (required) — Reference to Playbook
- `spec.schedule` (required) — Cron expression or random macro
- `spec.suspend` (default: `false`) — Pause scheduling
- `spec.concurrencyPolicy` (default: `Forbid`) — `Allow`, `Forbid`, or `Replace`
- `spec.startingDeadlineSeconds` — Deadline for missed schedules
- `spec.backoffLimit` (default: `3`) — Job retry limit
- `spec.successfulJobsHistoryLimit` (default: `1`) — Retain successful Jobs
- `spec.failedJobsHistoryLimit` (default: `1`) — Retain failed Jobs
- `spec.ttlSecondsAfterFinished` (default: `3600`) — TTL for completed Jobs
- `spec.resources` — Override Playbook resource limits

**Schedule Macros:**

Instead of standard cron, use macros for load distribution:

- `@hourly-random` — Random minute each hour
- `@daily-random` — Random minute and hour each day
- `@weekly-random` — Random minute, hour, and day-of-week each week
- `@monthly-random` — Random minute, hour, and day-of-month (1-28) each month
- `@yearly-random` — Random minute, hour, day-of-month, and month each year

Randomization is **deterministic** based on the resource's UID, ensuring stability across operator restarts.

**Example: Weekly random schedule:**

```yaml
apiVersion: ansible.cloud37.dev/v1alpha1
kind: Schedule
metadata:
  name: weekly-maintenance
spec:
  playbookRef:
    name: system-maintenance
  schedule: "@weekly-random"
  concurrencyPolicy: Forbid
  failedJobsHistoryLimit: 3
  ttlSecondsAfterFinished: 7200
```

The computed schedule (e.g., `47 3 * * 2`) is published to `status.computedSchedule`.

**Status Fields:**
- `status.computedSchedule` — Concrete cron expression
- `status.lastRunTime` — Last execution timestamp
- `status.nextRunTime` — Next scheduled execution
- `status.lastJobRef` — Reference to most recent Job
- `status.conditions` — `Active`, `BlockedByConcurrency`, `Ready`

## 🔒 Security

### Default Security Posture

All executor pods run with hardened security contexts:

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

### RBAC Presets

Configure via Helm values:

- **`minimal`** (default) — Namespace-scoped permissions for Jobs, CronJobs, Events
- **`scoped`** — Extended to specific resource types and namespaces
- **`cluster-admin`** (opt-in) — Full cluster access (use with caution)

### Executor ServiceAccount

The operator creates a separate ServiceAccount for executor Jobs by default, providing enhanced security isolation:

```yaml
executorDefaults:
  serviceAccount:
    create: true
    name: ""  # Auto-generated as {release-name}-executor
    rbacPreset: minimal  # minimal, scoped, or cluster-admin
```

**Benefits:**
- **Security isolation** — Executor pods use a different identity than the operator
- **Minimal permissions** — Executor ServiceAccount has only the permissions needed for Ansible execution
- **Audit trail** — Clear separation between operator and executor activities
- **Configurable RBAC** — Choose appropriate permission level for your use case

**RBAC Presets for Executor:**

- **`minimal`** (default) — Read-only access to pods, services, configmaps, secrets; can create events
- **`scoped`** — Extended permissions for cross-namespace operations and resource management
- **`cluster-admin`** — Full cluster permissions (use with extreme caution)

See `examples/values-executor-serviceaccount.yaml` for detailed configurations.

```bash
helm install ansible-playbook-operator ./helm/ansible-playbook-operator \
  --set rbac.preset=minimal
```

### Secret Management

**Supported Secret Types:**
- `kubernetes.io/ssh-auth` — SSH private key
- Opaque — Token in `token` key
- `kubernetes.io/basic-auth` — Username/password

**Injection Methods:**
1. **Environment variables** — Explicit mappings or full Secret import
2. **File mounts** — Mount Secret keys as files (e.g., SSH keys, certificates)
3. **Vault passwords** — Ansible Vault password file

**Secret Access Control:**
- **Default**: Operator can access all Secrets in its namespace
- **Optional Restriction**: Use `rbac.secretRestriction.enabled: true` to limit access to specific Secrets
- **Cross-namespace**: Supported with `scoped` or `cluster-admin` presets
- See [examples/values-secret-restriction.yaml](examples/values-secret-restriction.yaml) for configuration examples

**Best Practices:**
- Use `serviceAccountName` in Playbook to run Jobs with least-privilege SAs
- Never log secrets (the operator redacts them)
- Pin known_hosts for SSH to prevent MITM attacks
- Use `strictHostKeyChecking: true` in production

## 📊 Observability

### Metrics

The operator exposes Prometheus metrics on port `8080`:

- `ansible_operator_reconcile_total{kind, result}` — Reconciliation counts
- `ansible_operator_reconcile_duration_seconds{kind}` — Reconciliation latency histogram

**Enable ServiceMonitor:**

```yaml
operator:
  metrics:
    enabled: true
    serviceMonitor:
      enabled: true
```

### Events

The operator emits Kubernetes Events for:
- `ValidateSucceeded` / `ValidateFailed`
- `CronJobApplied` / `CronJobCreated` / `CronJobPatched`
- `ReconcileStarted` / `ReconcileFailed`
- Configuration issues (e.g., missing Secrets, invalid references)

View events:

```bash
kubectl get events --field-selector involvedObject.kind=Schedule
```

### Logs

Structured JSON logs with fields:
- `controller`, `resource`, `uid`, `runId`, `event`, `reason`

**No secrets are logged.** The operator sanitizes all log output.

## 🛠️ Development

### Prerequisites

- Python 3.14+
- `uv` or `pip` for dependency management
- Pre-commit hooks configured

### Setup

```bash
# Clone repository
git clone https://github.com/kenchrcum/ansible-playbook-operator
cd ansible-playbook-operator

# Install dependencies
# Option 1: Using requirements files (recommended for CI/CD)
pip install -r requirements-dev.txt

# Option 2: Install as editable package
pip install -e ".[test]"

# Install pre-commit hooks
pre-commit install

# Run tests
pytest tests/
```

### Project Structure

```
.
├── src/
│   └── ansible_operator/
│       ├── main.py              # Kopf handlers and reconciliation logic
│       ├── metrics.py           # Prometheus metrics definitions
│       ├── constants.py         # API group and label constants
│       ├── builders/
│       │   └── cronjob_builder.py  # CronJob manifest generation
│       └── utils/
│           └── schedule.py      # Random schedule macro computation
├── helm/
│   └── ansible-playbook-operator/
│       ├── crds/                # CRD definitions (not templated)
│       ├── templates/           # Helm templates for operator deployment
│       └── values.yaml          # Default Helm values
├── tests/
│   ├── unit/                    # Unit tests
│   └── integration/             # Kind-based integration tests
├── examples/                    # Example CRs
├── schemas/                     # Additional JSON schemas
└── architecture/
    └── development-plan.md      # Living design document
```

### Testing

```bash
# Unit tests
pytest tests/unit/

# Integration tests (requires kind cluster)
pytest tests/integration/

# Run with coverage
pytest --cov=ansible_operator tests/
```

### Code Quality

The project uses:
- **`ruff`** — Fast Python linter
- **`ruff format`** / **`black`** — Code formatting
- **`mypy`** — Static type checking
- **`pytest`** — Testing framework

**Pre-commit checks:**

```bash
pre-commit run --all-files
```

### Building

**Build operator image:**

```bash
docker build -t kenchrcum/ansible-playbook-operator:dev .
```

**Test locally:**

```bash
kopf run --standalone -m ansible_operator.main
```

## 🎛️ Configuration

### Helm Values

Key configuration options:

```yaml
operator:
  image:
    repository: kenchrcum/ansible-playbook-operator
    tag: "0.1.6"
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 512Mi
  leaderElection: true
  watch:
    scope: namespace  # or 'all' for cluster-wide
  metrics:
    enabled: true
    serviceMonitor:
      enabled: true

executorDefaults:
  image:
    repository: kenchrcum/ansible-runner
    tag: 13
  serviceAccount:
    # Whether to create a separate ServiceAccount for executor Jobs
    create: true
    # Name of the executor ServiceAccount (auto-generated if empty)
    name: ""
    # RBAC preset for executor permissions: minimal (default), scoped, cluster-admin
    rbacPreset: minimal
  cache:
    strategy: none  # Default cache strategy for repositories
    pvcName: ""  # Default PVC name when strategy is pvc
    createPVC: false  # Create PVC via Helm
    storageSize: "10Gi"  # PVC size when createPVC is true
    storageClassName: ""  # Storage class for PVC

rbac:
  preset: minimal  # minimal|scoped|cluster-admin
  clusterRead: true
```

### Operator Settings

Configured in `main.py`:
- **Max workers:** 4 (parallel reconciliations)
- **Request timeout:** 30 seconds
- **Metrics port:** 8080
- **Field manager:** `ansible-operator` (Server-Side Apply)

## 🤝 Contributing

Contributions are welcome! Please follow these guidelines:

1. **Fork** the repository
2. **Create a feature branch**: `git checkout -b feat/my-feature`
3. **Follow the code style**: Run `pre-commit run --all-files`
4. **Add tests** for new functionality
5. **Update documentation** as needed
6. **Commit with Conventional Commits**: `feat:`, `fix:`, `docs:`, etc.
7. **Submit a Pull Request**

### Commit Message Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

## 📖 Documentation

### Core Documentation
- [Development Plan](./architecture/development-plan.md) - Comprehensive architectural documentation
- [Configuration Reference](./docs/configuration.md) - Complete configuration guide
- [Troubleshooting Guide](./docs/troubleshooting.md) - Common issues and solutions

### Operational Guides
- [Security Best Practices](./docs/security.md) - Security configuration and best practices
- [Monitoring and Alerting](./docs/monitoring.md) - Observability setup and configuration
- [Performance Tuning](./docs/performance.md) - Performance optimization guide
- [Upgrade and Migration](./docs/upgrade.md) - Version upgrades and migrations

### Architecture Overview

The [Development Plan](./architecture/development-plan.md) covers:

- CRD design philosophy
- Reconciliation model and Server-Side Apply strategy
- Security architecture and RBAC design
- Git authentication and secret handling
- Job/CronJob generation patterns
- Observability and testing strategies

## 📝 License

This project is licensed under the **Unlicense**.

## 🔗 Links

- **Home:** https://github.com/kenchrcum/ansible-playbook-operator
- **Issues:** https://github.com/kenchrcum/ansible-playbook-operator/issues
- **Helm Chart:** `./helm/ansible-playbook-operator`

## 🙏 Acknowledgments

- Built with [Kopf](https://kopf.readthedocs.io) — Kubernetes Operator Pythonic Framework
- Uses [kubernetes-client/python](https://github.com/kubernetes-client/python)
- Default executor: [kenchrcum/ansible-runner](https://hub.docker.com/r/kenchrcum/ansible-runner)

---

**Status:** v1alpha1 — Under active development. API may evolve to v1beta1 with conversion support.

For questions or support, please open an issue or reach out to the maintainers.
