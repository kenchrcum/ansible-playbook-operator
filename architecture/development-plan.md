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
- `schedule` (string, required): either a standard cron expression or one of the macros `@hourly-random`, `@daily-random`, `@weekly-random`, `@monthly-random`, `@yearly-random`
  - `@hourly-random`: deterministic random minute (0–59)
  - `@daily-random`: deterministic random minute (0–59) and hour (0–23)
  - `@weekly-random`: deterministic random minute (0–59), hour (0–23), and day-of-week (0–6)
  - `@monthly-random`: deterministic random minute (0–59), hour (0–23), and day-of-month (1–28) for universal validity
  - `@yearly-random`: deterministic random minute (0–59), hour (0–23), month (1–12), and day-of-month (1–28) for universal validity
  - Randomization is stable per-object using a seed derived from `metadata.uid` (fallback: namespaced name)
  - The concrete cron is published to `status.computedSchedule`
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
- `computedSchedule` (string): concrete cron calculated from `spec.schedule` when a macro is used
- `lastRunTime` (timestamp)
- `nextRunTime` (timestamp)
- `lastJobRef` (namespaced name)
- `lastRunRevision` (string)
- `conditions`: `Active`, `BlockedByConcurrency`, `Ready`

Manual runs (v1alpha1): Supported via a well-known annotation on `Playbook` (e.g., `ansible.cloud37.dev/run-now: <id>`). The operator detects the change, creates a one-shot Job, and records the result in `status`.

## Phase 3: Operator Architecture

### 3. Reconciliation model

#### 3.1 Handler registration & controller settings
- Register `@kopf.on.create`, `@kopf.on.update`, `@kopf.on.resume`, `@kopf.on.delete` for `Repository`, `Playbook`, and `Schedule`.
- Idempotent handlers only — every step must be safe to repeat after operator restarts.
- Configure controller limits: bounded worker pool, rate-limited requeues, leader election on by default.

#### 3.2 Ownership, field management, and finalizers
- Use Server-Side Apply with field manager `ansible-operator`; patch only fields owned by the operator.
- Set `ownerReferences` on derived resources (CronJobs, Jobs, probe Jobs) pointing to the source CR.
- Add a single finalizer `ansible.cloud37.dev/finalizer` per CR:
  - `Repository`: remove any ephemeral probe Jobs/Pods created for validation.
  - `Playbook`: no derived long-lived resources; ensure orphan Jobs are left to TTL controller or are cleaned if labeled as derived.
  - `Schedule`: delete managed CronJob and optionally clean history (respecting history limits and TTL).

#### 3.3 Cross-resource indexing & triggers
- Maintain indices to map dependencies:
  - `Repository.name -> [Playbook...]`
  - `Playbook.name -> [Schedule...]`
- On `Repository` change: revalidate dependent `Playbook`s.
- On `Playbook` change: reconcile dependent `Schedule`s.
- Guard against thundering herds with rate-limited requeues.

#### 3.4 Repository reconciliation (desired vs. observed)
- Validate spec: URL format, auth method/secret presence, known hosts reference if SSH and strict checking is true.
- Connectivity probe (optional, fast):
  - Strategy A (default later phase): create a short-lived probe Job (e.g., `git ls-remote`) using a minimal git image; mount secrets/config.
  - Strategy B (fallback): skip external call; mark `AuthValid` unknown, rely on first Playbook run to surface issues.
- Status updates:
  - Conditions: `AuthValid` (True/False/Unknown), `CloneReady` (True/False/Unknown), `Ready` derived.
  - `resolvedRevision`: if `spec.revision` is set, copy to status; otherwise leave empty (resolved at execution time).
  - Emit Events on transitions: `ValidateSucceeded`, `ValidateFailed`.

#### 3.5 Playbook reconciliation
- Validate spec and references: ensure `Repository` exists and is Ready (or report `RepoNotReady`).
- Compute execution template inputs (no Job creation here): inventory path(s), vars sources, secrets mounts, runtime overrides.
- Status updates:
  - Conditions: `Ready` if paths and references validate; `InvalidPath` or `RepoNotReady` otherwise.
  - Emit Events: `ValidateSucceeded`, `ValidateFailed` with concise reasons.

#### 3.6 Schedule reconciliation
- Compute `status.computedSchedule` from `spec.schedule`:
  - If macro (`@hourly|daily|weekly|monthly|yearly-random`), derive a deterministic schedule using a seed from `metadata.uid`.
  - Otherwise, echo the provided cron.
- Render desired CronJob spec:
  - Populate pod template from `Playbook` runtime and secrets; set history limits, backoff, TTL, concurrency policy.
  - Apply security defaults (non-root, no privilege escalation, read-only FS, seccomp RuntimeDefault, drop caps).
  - Label with traceability keys (below).
- Apply with SSA; adopt existing CronJob if labels/owner match; patch only owned fields.
- Status updates:
  - Conditions: `Ready` if CronJob matches desired; `BlockedByConcurrency` when appropriate.
  - `lastRunTime`, `nextRunTime`, `lastJobRef` are updated from observed CronJob/Job status when available.
  - Emit Events: `CronJobCreated`, `CronJobPatched`, `CronJobAdopted`.

#### 3.7 Traceability labels/annotations (on CronJobs/Jobs)
- `ansible.cloud37.dev/managed-by: ansible-operator`
- `ansible.cloud37.dev/owner-kind: Schedule`
- `ansible.cloud37.dev/owner-name: <ns.name>`
- `ansible.cloud37.dev/owner-uid: <metadata.uid>` (label)
- `ansible.cloud37.dev/owner-uid: <metadata.uid>` (annotation for adoption safety)
- `ansible.cloud37.dev/revision: <repo.resolvedRevision or play run commit>` (on Jobs)
- `ansible.cloud37.dev/run-id: <uuid>` (on Jobs)

#### 3.8 Events and condition semantics
- Standard event reasons:
  - ReconcileStarted, ReconcileFailed, ValidateSucceeded, ValidateFailed,
  - CronJobCreated, CronJobPatched, CronJobAdopted,
  - JobCreated, JobSucceeded, JobFailed, CleanupSucceeded, CleanupFailed.
- Conditions are authoritative for user-facing state; Events are ephemeral but helpful for debugging.

#### 3.9 Drift detection and SSA strategy
- Use SSA diff to detect drift only within operator-owned fields; do not overwrite user-managed fields.
- Safe CronJob adoption logic:
  - If CronJob is already managed by ansible-operator: check owner UID (label or annotation) matches
  - If CronJob has owner references: check Schedule owner reference matches
  - If CronJob has UID annotation: check annotation matches Schedule UID (manual adoption)
  - Otherwise: emit warning and skip adoption to avoid hijacking
- Never force-apply unless recovering from a previous operator field manager; prefer granular patches.

#### 3.10 Requeues and backoff
- Requeue on transient failures with exponential backoff; cap max delay.
- Periodic soft requeue (e.g., every 10–15 minutes) for `Schedule` to refresh `nextRunTime` if needed.
- Avoid time-based loops where possible; rely on Kubernetes events/status.

### 4. Git and execution separation
- Separation of concerns:
  - Operator remains lightweight and does not hold repository content; it validates refs and renders desired runtime configuration
  - Executor Job performs clone/checkout and runs Ansible; isolation avoids leaking credentials into operator memory
- Determinism:
  - If `Repository.spec.revision` is set, executor must checkout that exact commit; record it in Job labels and `Schedule.status.lastRunRevision`
  - Otherwise, executor checks out the branch tip and records the resolved commit
- Authentication:
  - Use typed Secrets (`kubernetes.io/ssh-auth`, Opaque token) per `Repository.spec.auth`
  - Enforce known_hosts pinning when `ssh.strictHostKeyChecking` is true by mounting the provided ConfigMap
  - Avoid runtime `ssh-keyscan` by default; allow opt-in via a `Playbook.runtime.allowSshKeyscan` future flag
- Repo options:
  - Submodules and LFS support follow `Repository.spec.git` toggles
  - Shallow clone is preferred for performance unless `revision` requires full history
- Caching:
  - Optional PVC cache for `~/.ansible` collections/roles to speed repeated runs; scope by namespace and label by owner to reduce contention
  - Do not cache repository working tree unless an advanced cache strategy is explicitly configured

### 5. Job and CronJob generation
- Image selection:
  - Default executor image `kenchrcum/ansible-runner` (digest pinned in chart); overridable via `Playbook.runtime.image`
- Command construction:
  - Install galaxy requirements if `requirements.yml` exists
  - Build `ansible-playbook` command with inventory path(s), `--extra-vars` from `extraVars` and `extraVarsSecretRefs`
  - Support tags (future) and `ansible.cfg` if provided
- Secrets and config injection:
  - Environment: explicit env var mappings and full `envFromSecretRefs`
  - Files: `fileMounts` with key-to-path mappings and a vault password file if configured
  - SSH: mount `kubernetes.io/ssh-auth` secret at a secure path and set permissions before use
- CronJob spec:
  - Respect `successfulJobsHistoryLimit`, `failedJobsHistoryLimit`, `concurrencyPolicy`, `startingDeadlineSeconds`, `ttlSecondsAfterFinished`
  - Template pod-level knobs from `Playbook.runtime` (resources, node/pod scheduling, imagePullSecrets)
  - Set `activeDeadlineSeconds` and `backoffLimit` according to `Schedule.spec`
- Security defaults for executor pods:
  - `runAsNonRoot: true`, `runAsUser: 1000`, `runAsGroup: 1000`
  - `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`
  - `seccompProfile: RuntimeDefault`, drop all Linux capabilities
  - Optional `fsGroup` when file-mounted secrets require shared access
- Traceability:
  - Labels: managed-by, owner-kind/name/uid, run-id, resolved revision; annotate with rendered command sans secrets
  - Emit Events on creation/patch/adoption failures and successes

### 6. Concurrency and backpressure
- Respect CronJob `concurrencyPolicy` and surface conflicts via `Schedule` Conditions
- Configure Kopf worker pool (e.g., 4–8 workers) and exponential backoff requeues for transient errors
- Debounce cascaded reconciles: coalesce bursts from repository changes into a bounded work queue
- Use `@kopf.on.resume` to adopt existing resources and recompute `status.computedSchedule`

## Phase 4: Security and Permissions

### 7. RBAC presets (least privilege by default)
- Minimal (default):
  - Namespaced permissions to manage `jobs` and `cronjobs` (create/get/list/watch/patch)
  - Read `events` and `pods/log` in namespace for observability
  - Read only Secrets referenced by `Playbook`/`Repository` (use `resourceNames` where feasible)
- Scoped:
  - Values-driven allowlists of namespaces/resources; provide a separate ServiceAccount for executor Jobs
- Cluster Admin (opt-in):
  - Full cluster access for playbooks managing cluster resources; disabled by default and gated via Helm value
  - Document risks and provide example PSP/PSA labels and NetworkPolicies

### 8. Multi-tenancy and isolation
- Allow per-Playbook `serviceAccountName` to run Jobs under a least-privilege SA distinct from the operator
- Provide optional NetworkPolicies that restrict egress to Git endpoints and required targets
- Recommend Pod Security Admission labels and namespaces with restricted policies

## Phase 5: Deployment and Packaging

### 9. Helm chart
- Structure:
  - `crds/`: one file per CRD (no templating of schema)
  - `templates/`: Deployment, RBAC, ServiceAccount, Config, Service(+ServiceMonitor), NetworkPolicy
  - `values.yaml`: `operator.*`, `executorDefaults.*`, `rbac.*`, `watch.*`, `metrics.*`, `cache.*`
- Values highlights:
  - Pin images by digest in releases
  - Enable leader election and configure namespace/all-namespaces watch
  - Toggle ServiceMonitor and provide scrape labels
  - Optional NetworkPolicies limiting egress to Git endpoints and package registries
  - Optional PVC cache configuration

### 10. Container images
- Operator image: `python:3.11-slim` with `kopf`, `kubernetes`, `pyyaml`, and minimal tools; no Ansible required in the operator image
- Executor image: default `kenchrcum/ansible-runner` (digest-pinned), overridable per Playbook
- Supply SBOM and image scanning in CI; keep images reproducible and minimal

## Phase 6: Observability and Testing

### 11. Observability
- Logs: structured JSON with fields `controller`, `resource`, `uid`, `runId`, `event`, `reason`; never log secret values
- Events: concise reasons/messages; emitted on validations, apply/adopt, job lifecycle
- Metrics (Prometheus):
  - `ansible_operator_reconcile_total{kind,result}`
  - `ansible_operator_reconcile_duration_seconds{kind}` (histogram)
  - `ansible_operator_workqueue_depth`
  - `ansible_operator_job_runs_total{result}` and `ansible_operator_job_duration_seconds`
  - Expose via Service; provide optional ServiceMonitor in chart
- Status: Conditions are the authoritative source for user state; maintain `computedSchedule`, `lastRunTime`, and `lastJobRef`

### 12. Testing Strategy
- Unit tests:
  - CRD schemas: defaults, mutually exclusive fields, CEL rules
  - Command rendering: inventory handling, extra vars, secret injection (env/envFrom/files), vault password
  - Schedule macros: deterministic `computedSchedule` for same UID; distribution across minutes/hours/days
- Integration (kind/minikube):
  - Operator deploy, CR creation, CronJob materialization, Job success/failure paths
  - Auth matrix (SSH known_hosts pinned, HTTPS token); missing secret failure conditions
  - Security defaults enforced on pods (non-root, readonly rootfs)
  - Multi-resource cascade: changing `Repository` revalidates `Playbook` and updates `Schedule`
- Concurrency/race: overlapping schedules with Forbid/Replace, many schedules using random macros, operator restarts with `on.resume`
- Upgrade: CRD version bumps and Helm upgrades with existing CRs and running schedules
- Security: secret redaction in logs, RBAC denied cases produce clear Events/Conditions

## Phase 7: CI/CD and Release

### 13. CI/CD pipeline
- PR checks: ruff, black, mypy, unit tests, minimal kind e2e smoke, chart lint (`helm lint`/`chart-testing`)
- Security: Trivy/Grype image scans, Syft SBOM, secret scanning, dependency audit
- Releases: tag-driven build, push image and chart with digests; generate changelog
- Supply-chain: provenance/attestations (SLSA-style) optional but recommended

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
