## Ansible Playbook Operator — Development TODO (v1alpha1 scope unless noted)

This backlog captures missing or incomplete work to reach the goals in `architecture/development-plan.md`. Items are grouped by area and written as actionable tasks. Security defaults and least-privilege RBAC are expected across all items.

### Controllers and Reconciliation
- [x] Repository: implement connectivity probe Job (e.g., `git ls-remote`) with SSA; mount typed auth and optional `known_hosts` when `ssh.strictHostKeyChecking=true`.
- [x] Repository: set and maintain Conditions `AuthValid`, `CloneReady`, and derived `Ready`; emit `ValidateSucceeded`/`ValidateFailed` events with concise reasons.
- [x] Repository: add finalizer `ansible.cloud37.dev/finalizer` and clean up probe artifacts on delete.
- [x] Playbook: validate references and paths (exists relative to repo: playbook, inventory, optional `ansible.cfg`), surface `InvalidPath` or `RepoNotReady` conditions.
- [x] Schedule: adopt existing CronJobs safely (owner/labels match or UID annotation) and reconcile via SSA to patch only operator-owned fields.
- [x] Schedule: update `status.lastRunTime`, `status.nextRunTime`, `status.lastJobRef`, `status.lastRunRevision` from observed CronJob/Job.
- [x] Schedule: set Conditions (`Ready`, `BlockedByConcurrency`) according to observed state and `concurrencyPolicy`.
- [x] Cross-resource triggers: index `Repository -> [Playbook…]` and `Playbook -> [Schedule…]`; requeue dependents on changes with rate-limiting.
- [x] Manual run: honor `Playbook` annotation `ansible.cloud37.dev/run-now: <id>` to create a one-shot Job; record outcome in `status` and emit events.

### Execution Template (CronJob/Job) builder
- [x] Secrets: implement `secrets.fileMounts` (key-to-path) and mount layout; include optional `fsGroup` when needed.
- [x] Secrets: support `vaultPasswordSecretRef` and wire to Ansible via `--vault-password-file`.
- [x] Vars: merge `extraVarsSecretRefs` with `extraVars` without logging secret values; ensure deterministic precedence and redaction in logs.
- [x] Ansible config: support in-repo `ansible.cfg` (relative paths should resolve under `/workspace/repo`), and environment `ANSIBLE_CONFIG` when `spec.ansibleCfgPath` is set.
- [x] Git: add options for `submodules`, `lfs`, and shallow clone; respect `Repository.spec.git.*`.
- [x] Caching: optional PVC-backed cache for `~/.ansible` collections/roles per `Repository.spec.cache` and chart values.
- [x] Traceability: label Jobs with `ansible.cloud37.dev/run-id` and resolved `ansible.cloud37.dev/revision`; annotate rendered command sans secrets.
- [x] Security defaults: ensure container security merges defaults rather than being entirely replaced; enforce `readOnlyRootFilesystem`, `seccompProfile: RuntimeDefault`, `allowPrivilegeEscalation: false`, drop all caps unless explicitly overridden with justification.
- [x] CLI options: extend to support tags, check mode, timeout, and common `ansible-playbook` toggles via `Playbook.spec` (future-compatible design).

### Observability
- [x] Logging: structured JSON logs with `controller`, `resource`, `uid`, `runId`, `event`, `reason`; never log secrets.
- [x] Metrics: add workqueue depth, Job runs total and duration histograms; expose via existing metrics Service.
- [x] Events: standardize event reasons across lifecycle (ReconcileStarted/Failed, CronJobCreated/Patched/Adopted, JobCreated/Succeeded/Failed, CleanupSucceeded/Failed).

### RBAC and Security
- [x] Helm RBAC presets: implement `rbac.preset` values `minimal` (default), `scoped`, `cluster-admin` with clear, least-privilege rules.
- [x] Operator watch scope: when `operator.watch.scope=all`, provide ClusterRole for CRDs and namespaced resources read as needed; keep writes namespaced.
- [x] Executor identity: support separate ServiceAccount for executor Jobs, templated in Helm, with minimal permissions for target scenarios.
- [x] Secret access: restrict Secret reads to referenced names (use `resourceNames` where feasible) and document limitations.
- [x] NetworkPolicies: optional egress restrictions to Git endpoints and required registries; example presets in chart values.
- [x] Image pinning: pin operator and default executor images by digest for releases and CI; document upgrade flow.

### Helm Chart Improvements
- [x] Values layout: complete split between `operator.*`, `executorDefaults.*`, and `rbac.*`; document all fields with sane defaults.
- [x] ServiceMonitor: allow additional labels/namespace selectors; document Prometheus Operator expectations.
- [x] Multi-namespace examples: provide example values for `namespace` vs `all` watch; include RBAC presets and trade-offs.
- [x] Provide optional PVC cache values and templates for executor cache volume.
- [x] Add optional NetworkPolicy manifests and example values.
- [x] Hardening: ensure Deployment, ServiceAccount, and RBAC reflect least-privilege and security context defaults; add PSA labels guidance.

### CRDs
- [x] Reconcile CRD schemas with plan: verify defaults, validations (CEL), and `status` shapes match; add missing list fields enums and descriptions.
- [x] Backward compatibility notes: establish policy for version bumps (`v1beta1`) and conversion when schema evolves.
- [x] Additional validations: mutually exclusive fields (already for inventory), ensure required fields for `fileMounts` and secret refs; add CEL for simple guards.

### Status and Drift/SSA Strategy
- [x] SSA ownership: limit patches to operator-owned fields; avoid stomping user-managed fields; codify ownership map.
- [x] Adoption safety: require matching owner UID annotation or label to adopt existing resources; otherwise emit warnings and do not hijack.
- [ ] Periodic requeue: soft requeue for `Schedule` to refresh `nextRunTime` if needed without busy loops.

### Testing
- [x] Unit: CRD schema defaults/validation, command rendering (inventory, extra vars, secret injection, vault), git options (ssh/token, known_hosts), security defaults merging.
- [x] Unit: SSA/adoption behaviors (owned field diffs), status condition transitions, event emission coverage.
- [ ] Integration (kind): deploy operator, create CRs → CronJob materialization, Job success/failure paths; auth matrix (SSH with pinned known_hosts, HTTPS token); pod security defaults enforced.
- [ ] Concurrency/race: overlapping schedules with `Forbid/Replace`, many schedules using random macros, operator restarts (`on.resume`).

### CI/CD and Release
- [ ] CI pipeline: ruff, black, mypy, unit tests, minimal kind e2e smoke, chart lint; secret scanning and dependency audit.
- [ ] Supply chain: SBOM (Syft) and image scan (Trivy/Grype); publish digests on release; changelog automation.

### Documentation and Examples
- [x] README: extend with RBAC presets, watch scope, executor SA, security defaults, and metrics integration.
- [x] Architecture doc: update `architecture/development-plan.md` when adding new fields or behaviors (design-first).
- [x] Examples: add `ansible.cfg` in-repo example, `fileMounts`, `vaultPasswordSecretRef`, PVC cache usage, and RBAC presets; all runnable on kind/minikube.

### From user’s current priorities
- [x] RBAC presets for minimal, scoped, and cluster-admin roles/bindings controlled by chart values.
- [x] Broaden Ansible execution capabilities and configuration options beyond basic playbooks (vars, tags, vault, multiple inventories, retries/timeouts).
- [ ] General Helm chart improvements (values structure, docs, examples, NetworkPolicies, digest pinning).

### Later-phase (v1beta1+) considerations
- [ ] Introduce a dedicated `Run` CR (instead of annotation) for ad-hoc executions with history and status.
- [ ] Conversion and migration docs for any breaking CRD changes.
