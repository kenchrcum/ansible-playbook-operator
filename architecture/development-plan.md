# Ansible Playbook Operator Development Plan (v1alpha1)

This document defines a step-by-step, code-free plan to build a lightweight, GitOps-focused Kubernetes Operator for executing Ansible Playbooks using the Kopf framework in Python. It refines CRD designs, security, observability, packaging, and testing to produce an operator that is safe-by-default and easy to operate.

- API Group: `ansible.cloud37.dev`
- Initial Version: `v1alpha1` (evolve to `v1beta1`/`v1` with conversion)
- Scope: Repository, Playbook, Schedule CRDs; execution through Kubernetes Job/CronJob with `kenchrcum/ansible-runner` (overridable)
- Non-goals (for v1alpha1): complex admission webhooks, multi-cluster orchestration, embedded secret managers

## Phase 1: Project Setup and Design

### 1. Repository bootstrapping
- Layout: `src/` (controllers, services), `schemas/` (CRD definitions), `helm/` (chart), `docs/`, `tests/`, `examples/`, `k8s/` (manifests for dev), `scripts/` (dev tooling)
- Tooling: Python 3.11, `ruff`, `black`, `mypy`, `pytest`, `pre-commit`; dependency management via `uv` or `pip-tools`
- Operator runtime: enable leader election; decide watch scope (single namespace by default, opt-in all-namespaces)
- Conventions: Conventional Commits; PRs require relevant tests + docs

### 2. API definition and conventions
- CRDs are structural with defaults, validation, and `status` subresource enabled
- Use Conditions with `type`, `status`, `reason`, `message`, `lastTransitionTime`
- Use OwnerReferences for derived resources; use Finalizers for cleanup
- Server-Side Apply with a single field manager (e.g., `ansible-operator`) to manage owned fields; reconcile drift idempotently

## Phase 2: CRDs (Custom Resource Definitions)

All references are namespaced unless explicitly noted. Fields listed with defaults are optional; unspecified fields use defaults.

### A. Repository
Represents a Git repository hosting an Ansible environment.

Spec:
- `url` (string, required): Git URL (ssh or https)
- `revision` (string, optional): commit SHA; if set, overrides `branch`
- `branch` (string, default: `main`)
- `paths` (object):
  - `playbookDir` (string, default: `playbooks`)
  - `inventoryDir` (string, default: `inventory`)
  - `requirementsFile` (string, default: `requirements.yml`)
  - `rolesDir` (string, default: `roles`)
- `auth` (object):
  - `method` (enum: `ssh|https|token`)
  - `secretRef` (object): `name`, optional `namespace` (cross-namespace disallowed by default)
  - Secret typing guidance: `kubernetes.io/ssh-auth` for SSH; Opaque with `token` key for PAT; `kubernetes.io/basic-auth` for user/password
- `ssh` (object):
  - `knownHostsConfigMapRef` (optional): pin host keys (avoid runtime `ssh-keyscan`)
  - `strictHostKeyChecking` (bool, default: true)
- `git` (object): `submodules` (bool, default: false), `lfs` (bool, default: false)
- `cache` (object, optional):
  - `strategy` (enum: `none|pvc`), `pvcName` (when `pvc`)

Status:
- `observedGeneration` (int)
- `resolvedRevision` (string)
- `lastSyncTime` (timestamp)
- `conditions`: `AuthValid`, `CloneReady`, `Ready`

### B. Playbook
Represents an executable Ansible playbook and its execution environment.

Spec:
- `repositoryRef` (object, required): `name` (and optional `namespace` if cross-namespace allowed)
- `playbookPath` (string, required): relative to repo root
- `inventoryPath` (string, optional) or `inventoryPaths` (array of string)
- `ansibleCfgPath` (string, optional)
- `extraVars` (object, string->any)
- `extraVarsSecretRefs` (array): list of SecretRefs merged into extra vars
- `secrets` (object):
  - `env` (array): items with `envVarName`, `secretRef.name`, `secretRef.key`
  - `envFromSecretRefs` (array): list of SecretRefs to import all keys as env vars
  - `fileMounts` (array): items with `secretRef`, `mountPath`, `items[]` (key->path mapping)
  - `vaultPasswordSecretRef` (optional): SecretRef for Ansible Vault password file
- `runtime` (object):
  - `image` (string, default: `kenchrcum/ansible-runner:latest`, overridable)
  - `serviceAccountName` (string, optional)
  - `imagePullSecrets` (array)
  - `resources` (requests/limits)
  - `nodeSelector`, `tolerations`, `affinity`
  - `securityContext`, `podSecurityContext`
  - `volumes`, `volumeMounts`
  - `activeDeadlineSeconds` (int, optional)

Status:
- `observedGeneration` (int)
- `validated` (bool)
- `lastValidationTime` (timestamp)
- `conditions`: `Ready`, `InvalidPath`, `RepoNotReady`

### C. Schedule
Defines when a Playbook is executed by creating CronJobs (which spawn Jobs).

Spec:
- `playbookRef` (object, required): `name` (+ optional `namespace` if allowed)
- `schedule` (string, required): cron expression
- `suspend` (bool, default: false)
- `startingDeadlineSeconds` (int, optional)
- `concurrencyPolicy` (enum: `Allow|Forbid|Replace`, default: `Forbid`)
- `resources` (requests/limits) for executor pods
- `backoffLimit` (int, default: 3)
- `successfulJobsHistoryLimit` (int, default: 1)
- `failedJobsHistoryLimit` (int, default: 1)
- `ttlSecondsAfterFinished` (int, default: 3600)

Status:
- `observedGeneration` (int)
- `lastRunTime` (timestamp)
- `nextRunTime` (timestamp)
- `lastJobRef` (namespaced name)
- `lastRunRevision` (string)
- `conditions`: `Active`, `BlockedByConcurrency`, `Ready`

Manual runs (v1alpha1): Supported via a well-known annotation on `Playbook` (e.g., `ansible.cloud37.dev/run-now: <id>`). The operator detects the change, creates a one-shot Job, and records the result in `status`.

## Phase 3: Operator Architecture

### 3. Reconciliation model
- Handlers: `@kopf.on.create|update|delete|resume` for each CRD; idempotent, event-driven
- Adopt-or-recreate pattern with Server-Side Apply; patch only owned fields with field manager `ansible-operator`
- Use Finalizers to clean up derived resources (CronJobs/Jobs/PVCs)
- Emit Kubernetes Events for key transitions (ValidateFailed, JobCreated, JobSucceeded/Failed)
- Labels/annotations for traceability: link Jobs to CRs, include run id and `resolvedRevision`

### 4. Git and execution separation
- Operator validates connectivity and computes desired state; cloning happens inside executor Jobs for isolation
- Optional caching of collections/roles via PVC mounted at `~/.ansible` (configurable)
- For deterministic runs: when `spec.revision` is set on Repository, executor checks out that SHA and records it on the Job and `status`

### 5. Job and CronJob generation
- Job containers use the executor image (default `kenchrcum/ansible-runner`), overridable in `Playbook.runtime.image`
- Construct `ansible-playbook` command with inventory, requirements install (if file exists), tags (future), and extra vars
- Include `activeDeadlineSeconds`, `backoffLimit`, `ttlSecondsAfterFinished`
- Security defaults for executor pods:
  - `runAsNonRoot: true`, `runAsUser: 1000`, `runAsGroup: 1000`
  - `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`
  - `seccompProfile: RuntimeDefault`, drop all Linux capabilities

### 6. Concurrency and backpressure
- Respect CronJob `concurrencyPolicy`
- Configure Kopf worker limits (e.g., `max-workers`) and rate limiting to protect the API server
- Use `@kopf.on.resume` to requeue and reconcile after operator restarts, ensuring existing resources are adopted

## Phase 4: Security and Permissions

### 7. RBAC presets (least privilege by default)
- Minimal (default):
  - Namespaced permissions to manage `jobs` and `cronjobs` (create/get/list/watch/patch)
  - Read `events`
  - Read `secrets` only in the operator namespace and/or referenced secrets (use `resourceNames` where feasible)
- Scoped:
  - Values-driven set of allowed namespaces/resources; separate ServiceAccount for executor Jobs is supported
- Cluster Admin (opt-in):
  - Full cluster access for playbooks that manage cluster resources; explicitly disabled by default

### 8. Multi-tenancy and isolation
- Allow per-Playbook `serviceAccountName` to run Jobs under a least-privilege SA distinct from the operator
- Provide optional NetworkPolicies that restrict egress to Git endpoints and required targets
- Recommend Pod Security Admission labels and namespaces with restricted policies

## Phase 5: Deployment and Packaging

### 9. Helm chart
- Chart structure:
  - `crds/` (separate files per CRD; do NOT template schema)
  - `templates/` (Deployment, RBAC, ServiceAccount, Config, optional Service/ServiceMonitor, NetworkPolicy)
  - `values.yaml` split into `operator.*` and `executorDefaults.*` and `rbac.*`
- Configuration via values:
  - Image versions and pinned digests for operator and executor
  - RBAC preset selection
  - Watch scope (namespace/all-namespaces)
  - Resource limits for operator and executor
  - Metrics and ServiceMonitor enablement
  - Optional PVC for caching

### 10. Container images
- Operator image: `python:3.11-slim` with `kopf`, `kubernetes`, `pyyaml`, and minimal tools; no Ansible required in the operator image
- Executor image: default `kenchrcum/ansible-runner` (digest-pinned), overridable per Playbook
- Supply SBOM and image scanning in CI; keep images reproducible and minimal

## Phase 6: Observability and Testing

### 11. Observability
- Structured JSON logs with correlation IDs (resource UID + run id)
- Kubernetes Events for user-facing feedback
- Prometheus metrics: reconcile durations/counts, queue depth, job outcomes; expose via Service + optional ServiceMonitor
- `status.conditions` is the primary user-facing health surface

### 12. Testing Strategy
- Unit tests: CRD schema defaults/validation, command rendering, secret resolution, auth matrix (SSH, HTTPS PAT, basic)
- Integration tests (kind/minikube): deploy operator, create CRs, validate Jobs, known hosts handling
- Concurrency/race tests: overlapping schedules with Forbid/Replace, operator restarts (`on.resume`)
- Upgrade tests: CRD version bumps and Helm upgrades with existing CRs
- Security tests: ensure secrets never leak in logs; least-privilege RBAC verification

## Phase 7: CI/CD and Release

### 13. CI/CD pipeline
- Build and test on PRs; ruff/black/mypy/pytest; chart lint (ct)
- Image scanning (Trivy/Grype), SBOM (Syft), pinned image digests
- Release on tags: publish operator image and Helm chart
- Optional: provenance/attestations (SLSA-style) for images and charts

## Rollout, Upgrades, and Compatibility
- Start at `v1alpha1` with clear migration notes on any breaking CRD changes; use new versions rather than in-place breaking changes
- Helm: CRDs live in `crds/` to ensure robust install/upgrade; never template structural schema fields
- Backward compatibility: provide conversion or migration docs when evolving CRDs

## Risks and Mitigations
- Git auth complexity: use typed secrets and known hosts pinning; integration tests per provider
- Secret handling: multiple injection modes; explicit forbid logging secret values; pre-commit checks
- CronJob-only execution: support manual run via Playbook annotation; consider a dedicated `Run` CR in later versions
- Cluster access risks: presets default to minimal; clear documentation for opt-in escalation

## MVP Scope (deliverable for first release)
1) CRDs with validation, defaults, status/conditions
2) Reconciliation for Repository validation, Playbook validation, Schedule→CronJob with TTL and concurrency
3) Executor Job generation with secrets (env/envFrom/file mounts), vault password, and security defaults
4) Helm chart (CRDs in `crds/`, operator Deployment, RBAC presets), single-namespace watch
5) Observability essentials: Events, metrics, structured logs
6) Tests: unit + integration (kind) for happy-path and basic auth matrix

Note: This plan intentionally avoids writing code and focuses on architecture, safety, and operability to guide subsequent implementation sessions.
