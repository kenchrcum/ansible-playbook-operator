# Agent Guidelines

This document provides AI coding assistants with essential context and constraints for the Ansible Playbook Operator project.

## Project Overview

A Kubernetes operator that runs Ansible playbooks in response to custom resource changes. Written in Python 3.14, deployed via Helm, with controllers managing executor pods.

**License**: Unlicense (public domain dedication) — no attribution required, maximum permissiveness, no warranty.

## Core Principles

- **Simplicity first**: Prefer deterministic, straightforward solutions over clever complexity
- **Security by default**: Minimal RBAC, non-root pods, read-only filesystems, no privilege escalation
- **Observable**: All changes emit events, metrics, and structured logs
- **Reversible**: Feature flags and config switches allow rollback
- **Zero secrets exposure**: Never log, print, or document sensitive data

## Technology Stack

- **Language**: Python 3.14
- **Linting/Formatting**: `ruff` (lint), `black` (format), `mypy` (types)
- **Testing**: `pytest` (unit + kind-based integration)
- **Kubernetes**: Server-Side Apply with field manager `ansible-operator`
- **Deployment**: Helm charts with CRDs
- **Pre-commit**: Enforced before all commits

## Agent Workflow (CRITICAL)

### Commit Requirements
- **Always commit changes** when completing tasks or making meaningful progress
- Use conventional commit format: `type: description` (e.g., `feat:`, `fix:`, `docs:`, `test:`)
- Include detailed commit body for significant features or changes
- Reference completed TODO items in commit messages when appropriate
- Run pre-commit checks before committing: `source .venv/bin/activate && pre-commit run --all-files`

### Task Completion Workflow
1. Implement the requested changes
2. Update relevant tests and documentation
3. Run tests and pre-commit checks
4. Update TODO list with completed items
5. **Commit all changes** with descriptive message
6. Provide brief summary of what was accomplished

### Pre-commit Enforcement
Always run pre-commit checks locally before committing:
```bash
git add .
source .venv/bin/activate
pre-commit run --all-files
```

If hooks fail, auto-fix with:
- `ruff --fix .` and `ruff format .` (auto-fix imports, formatting)
- Re-run `pre-commit run --all-files` until it passes

**Do not commit if pre-commit is failing. Fix locally first.**

### Typical Pre-commit Fixes
- Import sorting/formatting (I001): use `ruff check --fix` for auto-fix
- Unused imports (F401): remove unused imports
- Type annotations: add proper type hints, avoid `Any` in public APIs
- Simplifications (SIM105): prefer `contextlib.suppress(Exception)` over `try/except/pass`
- Mypy: remove unused `# type: ignore`, add precise typing
- YAML linting: `examples/` directory is excluded (multi-document Kubernetes manifests)

### TODO Discipline
- Always reconcile the TODO list before starting new work
- Mark newly completed tasks as completed immediately after finishing
- Keep only one task `in_progress` at a time
- Set the next task to `in_progress` before starting it
- Cancel skipped tasks with a one-line justification
- Update `architecture/TODO.md` with `[x]` format for completed items
- Do not leave stale TODOs; the list must reflect current reality at all times

### Session Completion
- Commit all changes before ending session
- Provide clear summary of accomplishments
- Ensure TODO list reflects current state
- Leave repository in clean, committable state

## Code Style

### Python
- Strict typing at public boundaries; avoid `Any` in public APIs
- Descriptive names over abbreviations (clarity > brevity)
- Guard clauses over nested conditionals
- Explicit error handling; never swallow exceptions
- Small, focused functions; extract pure functions for testability
- For test files: use proper type annotations for variables (e.g., `status: dict[str, Any] = {}`)

### Example Pattern
```python
def process_resource(resource: CustomResource) -> Result:
    if not resource.spec:
        raise ValueError("Missing spec")
    
    if resource.spec.state == "disabled":
        return Result.skipped()
    
    return execute_playbook(resource)
```

## Directory Structure

```
src/                    # Controller entrypoints and services
├── controllers/        # Reconciliation logic
├── services/git/       # Git operations
├── services/ansible/   # Ansible execution
├── builders/           # Job and CronJob manifest builders (Ansible execution support)
└── k8s/resources/      # K8s resource builders

schemas/                # CRDs and JSON schemas (not Helm-templated)
helm/ansible-playbook-operator/
├── crds/               # CRD definitions
└── templates/          # Manifest templates, optional PVC template for caching

tests/
├── unit/               # Unit tests
└── integration/        # Kind-based integration tests

examples/               # Runnable, secure-by-default manifests
architecture/           # Design docs, TODO.md, backward-compatibility-policy.md
```

## Security Requirements

### Executor Pods Must Have
- `runAsNonRoot: true`
- `readOnlyRootFilesystem: true`
- `seccompProfile: RuntimeDefault`
- `allowPrivilegeEscalation: false`
- Dropped capabilities (`drop: ["ALL"]`)

### General
- Pin images by digest in released charts and CI
- Default to minimal RBAC; escalation is explicit opt-in
- No hardcoded secrets or credentials

### RBAC Presets
Implement RBAC with three progressive levels controlled by `rbac.preset` Helm value:

1. **Minimal (Default)**: Namespaced Role with core operator permissions only; single-namespace deployments
2. **Scoped**: Extended namespaced permissions for cross-namespace scenarios; cluster-wide operator deployments
3. **Cluster-Admin**: Full cluster permissions within namespace; playbooks requiring cluster-wide resource management (high-risk, explicit opt-in)

**Implementation Pattern**: Use conditional Helm templating with `{{- if eq .Values.rbac.preset "preset-name" }}`

**Security Principles**:
- Default to minimal preset
- Progressive escalation (each preset builds on previous level)
- Clear documentation of risks and use cases
- Maintain backward compatibility with existing boolean flags
- Principle of least privilege

## Deployment Modes

### Single-Namespace Mode (`scope: namespace`)
- **Configuration**: `operator.watch.scope: namespace`
- **RBAC**: `rbac.preset: minimal` (default)
- **Use cases**: Isolated deployments, development/testing, multi-tenant scenarios
- **Security**: Maximum isolation, least privilege
- **Limitations**: Cannot access resources in other namespaces

### Cluster-Wide Mode (`scope: all`)
- **Configuration**: `operator.watch.scope: all`
- **RBAC**: `rbac.preset: scoped` (recommended)
- **Use cases**: Centralized DevOps teams, cross-namespace resource sharing
- **Security**: Cross-namespace access, higher privilege requirements
- **Advantages**: Single operator instance, centralized management

**Terminology**: Use "cluster-wide" for `scope: all` deployments, "single-namespace" for `scope: namespace` deployments. Avoid "multi-namespace" terminology.

## Ansible Execution Capabilities

The Playbook CRD supports comprehensive execution options via `spec.execution`:

### Task Filtering
- `tags`: Array of tags to run (`--tags`)
- `skipTags`: Array of tags to skip (`--skip-tags`)

### Execution Modes
- `checkMode`: Boolean for dry-run mode (`--check`)
- `diff`: Boolean to show file differences (`--diff`)
- `step`: Boolean for step-by-step execution (`--step`)

### Output Control
- `verbosity`: Integer (0-4) for output verbosity (`-v`, `-vv`, `-vvv`, `-vvvv`)

### Host Targeting
- `limit`: String to limit execution to specific hosts (`--limit`)

### Performance Tuning
- `connectionTimeout`: Integer for connection timeout in seconds (`--timeout`)
- `forks`: Integer for parallel processes (`--forks`)
- `strategy`: String for execution strategy (`linear` or `free`, `--strategy`)

### Advanced Options
- `flushCache`: Boolean to clear fact cache (`--flush-cache`)
- `forceHandlers`: Boolean to run handlers on failure (`--force-handlers`)
- `startAtTask`: String to start at specific task (`--start-at-task`)

**Best Practices**:
- Use `checkMode: true` for validation runs
- Combine `tags` and `skipTags` for precise task control
- Set appropriate `connectionTimeout` for network reliability
- Use `verbosity: 2` for debugging, `verbosity: 0` for production
- Consider `strategy: free` for independent tasks when appropriate

## PVC-Backed Cache

The operator supports optional PVC-backed caching for `~/.ansible` collections and roles.

### CRD Configuration
```yaml
spec:
  cache:
    strategy: pvc  # or "none" (default)
    pvcName: my-cache-pvc  # Required when strategy is "pvc"
```

### Helm Configuration
```yaml
executorDefaults:
  cache:
    strategy: none  # Default strategy
    pvcName: ""  # Default PVC name
    createPVC: false  # Auto-create PVC via Helm
    storageSize: "10Gi"  # PVC size when createPVC=true
    storageClassName: ""  # Optional storage class
```

**Implementation Details**:
- Cache is mounted to `/home/ansible/.ansible` in executor pods
- Only caches Ansible collections/roles, not repository working trees
- PVC must be accessible by executor pods in the same namespace

## Observability Standards

### Events
Emit Kubernetes Events for:
- Reconciliation start/completion
- Executor pod lifecycle changes
- Git clone success/failure
- Playbook execution results
- Event examples: `ValidateSucceeded`/`ValidateFailed` with concise reasons

### Metrics (Prometheus)
- Reconcile duration and count
- Queue depth
- Job success/failure rates
- Conversion metrics: `ansible_operator_conversion_total{from_version,to_version,result}`
- Provide Service and optional ServiceMonitor

### Logging
- Structured JSON format
- Include correlation IDs: `{cr_uid}-{run_id}`
- Log levels: DEBUG, INFO, WARNING, ERROR
- **Never log secrets, tokens, or sensitive data**

## Git & Commits

### Branch Names
- `feat/*` - New features
- `fix/*` - Bug fixes
- `docs/*` - Documentation only
- `chore/*` - Maintenance tasks
- `refactor/*` - Code restructuring
- `test/*` - Test additions/fixes

### Commit Style
- Use Conventional Commits format
- Focus on "why" over "what"
- Small, focused commits
- No commented-out code
- No TODO comments (create issues instead)

### Pull Requests
- Squash merge via PRs
- Include "why" in PR description
- Update tests and docs in same PR
- CI must pass: lint, type-check, unit, integration, chart lint

## Kubernetes Patterns

### Server-Side Apply
- Always use Server-Side Apply for resource creation/updates
- Field manager: `ansible-operator`
- Example:
```python
api.patch_namespaced_custom_object(
    group="...",
    version="...",
    namespace="...",
    plural="...",
    name="...",
    body=resource_dict,
    field_manager="ansible-operator",
    force=True
)
```

### Status Conditions
New features must include status conditions following Kubernetes conventions:
- `type`: Condition type (e.g., "Ready", "Progressing")
- `status`: "True", "False", "Unknown"
- `reason`: CamelCase one-word reason
- `message`: Human-readable details
- `lastTransitionTime`: RFC3339 timestamp

**Repository CRD Conditions**:
- `AuthValid`: Authentication validation status
- `CloneReady`: Git clone readiness status
- `Ready`: Derived from `AuthValid=True` AND `CloneReady=True`

### CRD Schema Validation
- CRD schemas must not define `metadata` properties beyond `name` and `generateName`
- Kubernetes implicitly handles metadata fields; defining them causes validation errors
- Use `kubectl apply --dry-run=client` to validate CRD schemas before committing

## Helm Charts

### CRDs
- Stored in `helm/ansible-playbook-operator/crds/`
- No Helm templating in CRD schemas
- Follow Kubernetes versioning (additive changes only)

### Values Structure
```yaml
operator:           # Operator deployment config
  replicas: 1
  image: ...
  watch:
    scope: namespace  # or "all" for cluster-wide

executorDefaults:   # Default executor pod settings
  resources: ...
  securityContext: ...
  cache:            # PVC-backed cache configuration
    strategy: none
    pvcName: ""
    createPVC: false

rbac:               # RBAC configuration
  create: true
  preset: minimal   # or "scoped", "cluster-admin"
```

## Testing Requirements

### Running Tests
Always run tests using the virtual environment:
```bash
source .venv/bin/activate
pytest tests/unit/ -v
```

Run specific tests:
```bash
pytest tests/unit/test_filename.py -v
pytest tests/unit/test_filename.py::TestClass::test_method -v
```

Use `-s` flag for print output during debugging, `-q` for quiet output.

### Unit Tests
- Test pure functions and business logic
- Mock external dependencies (K8s API, filesystem)
- Fast execution (< 1s per test)
- Use descriptive test names
- Group related tests in test classes

### Kubernetes Controller Testing
**Repository CRD Testing**:
- Test all validation failure scenarios (missing URL, auth secret, ConfigMap)
- Verify `AuthValid`, `CloneReady`, and `Ready` conditions are set correctly
- Test probe success/failure transitions
- Test event emission (`ValidateSucceeded`/`ValidateFailed`)

**Mock Setup**:
```python
mock_patch = MockPatch()
meta_mock = MagicMock()
meta_mock.get.side_effect = lambda key, default=None: None if key == "deletionTimestamp" else MagicMock()
```

**Job Completion Testing**:
- Test successful probe: `AuthValid=True`, `CloneReady=True`, `Ready=True`
- Test failed probe: `AuthValid=False`, `CloneReady=False`, `Ready=False`
- Verify status updates via CustomObjectsApi.patch_namespaced_custom_object_status

### Integration Tests
- Use kind for Kubernetes cluster
- Test controller reconciliation loops
- Verify CRD lifecycle and status updates
- Clean up resources after each test

### Coverage
- New features require tests
- Maintain or improve coverage percentage
- Test error paths and edge cases
- Cover all execution options individually and in combination

## Backward Compatibility

### Versioning Strategy
- Follow Kubernetes API versioning: `v1alpha1` → `v1beta1` → `v1`
- Current version: `v1alpha1` (experimental)
- Version promotion requires 6+ months stability and community consensus
- See `architecture/backward-compatibility-policy.md` for complete guidelines

### Schema Evolution Rules

**Allowed Changes (Non-Breaking)**:
- Adding new optional fields with defaults
- Adding new fields to `status` subresource
- Adding new printer columns
- Adding new enum values (append-only)
- Making optional fields required (with default values)
- Relaxing validation constraints

**Prohibited Changes (Breaking)**:
- Removing any field from `spec` or `status`
- Removing enum values
- Changing field types (string → int, object → array, etc.)
- Making required fields optional
- Tightening validation constraints that reject existing data
- Changing field names

### Breaking Change Process
1. **Proposal Phase**: Create RFC with impact assessment and migration strategy
2. **Implementation Phase**: Implement new version with conversion webhooks
3. **Deprecation Phase**: 6-month notice, 3-month warning period
4. **Removal Phase**: Remove deprecated version after grace period

### Conversion Strategy
- Implement conversion webhooks for automatic migration between versions
- Provide migration tooling and documentation for complex changes
- Test all conversion paths with unit, integration, and E2E tests
- Monitor conversion success/failure with metrics and events

### Monitoring
- Metrics: `ansible_operator_conversion_total{from_version,to_version,result}`
- Events: `ConversionSucceeded`/`ConversionFailed`, `DeprecationWarning`
- Logs: Structured JSON with deprecation warnings and conversion attempts

## Documentation

### Architecture
- `architecture/development-plan.md` is the living design document
- Update before implementing significant changes
- Document design decisions and tradeoffs
- `architecture/backward-compatibility-policy.md` for detailed compatibility guidelines

### Examples
- Must be runnable in kind/minikube
- Follow security defaults
- Include comments explaining key fields
- Minimal viable examples (no unnecessary complexity)
- Examples: `values-namespace-watch.yaml`, `values-cluster-watch.yaml`, `values-rbac-presets.yaml`, `playbook-execution-options.yaml`, `playbook-check-mode.yaml`

## Quality Gates

Before merging, verify:
- [ ] CI passes (lint, types, tests, chart lint)
- [ ] Tests updated/added for new functionality
- [ ] Documentation updated
- [ ] Metrics/events added for observable changes
- [ ] Status conditions updated
- [ ] No secret leakage in logs or errors
- [ ] Security defaults maintained or strengthened
- [ ] Pre-commit checks pass
- [ ] TODO list updated with completed items
- [ ] Changes committed with descriptive conventional commit message

## Common Pitfalls to Avoid

1. **Don't** template CRD schemas in Helm
2. **Don't** log sensitive data (secrets, tokens, credentials)
3. **Don't** use `Any` in public Python APIs
4. **Don't** swallow exceptions without logging
5. **Don't** create TODOs; create issues instead
6. **Don't** reduce security defaults without explicit opt-in
7. **Don't** make breaking CRD changes without versioning
8. **Don't** commit commented-out code
9. **Don't** commit without running pre-commit checks
10. **Don't** leave work uncommitted at session end
11. **Don't** define `metadata` properties in CRD schemas (beyond `name` and `generateName`)
12. **Don't** use "multi-namespace" terminology (use "cluster-wide" instead)

## When in Doubt

1. Check existing patterns in `src/controllers/` and `src/builders/`
2. Refer to `architecture/development-plan.md`
3. Follow security-first principles
4. Make it observable (events, metrics, logs)
5. Keep it simple and testable
6. Always commit changes when completing tasks
7. Run pre-commit checks before committing
8. Update TODO list to reflect current state