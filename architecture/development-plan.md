# Ansible Playbook Operator Development Plan

## Overview
This document outlines the step-by-step plan for building a Kubernetes operator that executes Ansible playbooks in a GitOps-focused manner. The operator uses the Kopf framework and manages three CRDs: Repository, Playbook, and Schedule.

## Phase 1: Project Setup and Design

### 1. Initialize Git Repository
- Set up project structure with directories: `src/`, `helm/`, `docs/`, `tests/`
- Create initial commit with basic structure

### 2. Define CRDs (Custom Resource Definitions)

#### Repository CRD
Manages Git repositories containing Ansible environments.
- **Fields**:
  - `url` (string): Git repository URL
  - `type` (enum): github/gitlab/gitea/public
  - `branch` (string, default: main): Branch to checkout
  - `sshKeySecret` (string): Name of Secret containing SSH private key
  - `paths` (object): Directory structure config
    - `playbookDir` (string, default: "playbooks")
    - `inventoryDir` (string, default: "inventory")
    - `requirementsFile` (string, default: "requirements.yml")
    - `rolesDir` (string, default: "roles")
  - `auth` (object): Authentication config
    - `tokenSecret` (string): Secret containing access token for private repos
- **Validation**: URL format, supported Git providers

#### Playbook CRD
Represents executable Ansible playbooks.
- **Fields**:
  - `repositoryRef` (string): Name of Repository CR
  - `playbookPath` (string): Relative path to playbook file
  - `secrets` (list): Environment variables from Secrets
    - `secretName` (string)
    - `secretKey` (string)
    - `envVarName` (string)
  - `extraVars` (map): Additional Ansible variables
  - `tags` (list): Ansible tags for selective execution
- **Validation**: References valid Repository CR, playbook file exists

#### Schedule CRD
Defines execution timing for playbooks.
- **Fields**:
  - `playbookRef` (string): Name of Playbook CR
  - `schedule` (string): Cron expression
  - `concurrencyPolicy` (enum): Allow/Forbid/Replace
  - `resources` (object): CPU/memory requests/limits
  - `backoffLimit` (int, default: 3)
  - `historyLimits` (object): Job history retention
    - `success` (int, default: 1)
    - `failure` (int, default: 1)
- **Creates**: CronJob resources that spawn Jobs

### 3. Design Operator Architecture
- Use Kopf's event-driven handlers (@kopf.on.create, @kopf.on.update, @kopf.on.delete)
- **Repository handlers**: Validate repo access, cache/clone logic
- **Playbook handlers**: Validate playbook existence, prepare execution environment
- **Schedule handlers**: Create/update/delete CronJobs with embedded Job templates
- **Shared utilities**: Git operations, secret mounting, Job creation logic

## Phase 2: Core Implementation

### 4. Implement Repository Management
- Handler for repo creation: Test connectivity, validate SSH keys/tokens
- Git operations wrapper: Clone, checkout branch, update submodules
- Caching mechanism: Store cloned repos in persistent volumes or init containers

### 5. Implement Playbook Execution
- Job template generation: Based on kenchrcum/ansible-runner image
- Secret mounting: Convert CRD secrets to env vars and volume mounts
- Ansible command construction: Build ansible-playbook command with inventory, requirements, tags
- Error handling: Parse ansible output, set Job status accordingly

### 6. Implement Scheduling Logic
- CronJob creation: Map Schedule CR to CronJob spec
- Job lifecycle: Handle successful/failed executions, cleanup old jobs
- Concurrency control: Respect concurrency policies

## Phase 3: Security and Permissions

### 7. RBAC Design with Presets
- **Minimal Preset**: Only permissions to create Jobs, access own namespace secrets
  - `jobs`, `cronjobs` (create/get/list/watch), `secrets` (get in operator namespace)
- **Cluster Admin Preset**: Full cluster access for playbooks managing K8s resources
  - All resources (*), cluster-wide access
- **Scoped Preset**: Limited to specific namespaces/resources
  - Configurable via Helm values
- Service account creation with least privilege by default

## Phase 4: Deployment and Packaging

### 8. Helm Chart Development
- Chart structure: `templates/crds.yaml`, `templates/rbac.yaml`, `templates/deployment.yaml`
- `values.yaml`: Configurable RBAC preset, image versions, resource limits, CRD defaults
- Secrets handling: Reference external secrets, generate internal ones for SSH keys
- Multi-namespace support: Allow operator deployment in different namespaces

### 9. Containerization
- Dockerfile: Multi-stage build with Python dependencies
- Base image: `python:3.11-slim`
- Include kopf, kubernetes-client, git, ansible-runner dependencies

## Phase 5: Testing and Validation

### 10. Testing Strategy
- Unit tests: Mock Kubernetes API, test CRD validation, Job generation
- Integration tests: Use kind/minikube, deploy operator, create CRs, verify Jobs
- CRD validation: OpenAPI schemas, admission webhooks
- E2E tests: Full workflow from Schedule creation to playbook execution

## Phase 6: Documentation and Release

### 11. Documentation
- README: Installation, usage examples, CRD specifications
- API docs: Generated from CRD schemas
- Helm chart docs: Configuration options, presets explanation
- Examples: Sample Repository/Playbook/Schedule CRs

### 12. CI/CD Pipeline
- GitHub Actions: Build, test, release Helm chart
- Image scanning, security checks
- Automated releases on tags