# Integration Tests

This directory contains integration tests for the Ansible Playbook Operator using a kind cluster.

## Overview

The integration tests verify:

- Operator deployment via Helm chart
- Repository CR creation with SSH and HTTPS authentication
- Playbook CR creation and validation
- Schedule CR creation and CronJob materialization
- Job execution paths (success and failure)
- Authentication matrix (SSH with pinned known_hosts, HTTPS token)
- Pod security defaults enforcement

## Prerequisites

Before running integration tests, ensure you have:

- [kind](https://kind.sigs.k8s.io/) - Kubernetes in Docker
- [helm](https://helm.sh/) - Package manager for Kubernetes
- [docker](https://www.docker.com/) - Container runtime
- Python 3.11+ with virtual environment support

## Quick Start

Run the integration tests using the provided script:

```bash
# From project root
./scripts/run-integration-tests.sh
```

This will:
1. Create a kind cluster
2. Build and load operator/executor images
3. Deploy the operator via Helm
4. Run the integration tests
5. Clean up the cluster

## Manual Setup

If you prefer to run tests manually:

### 1. Create Kind Cluster

```bash
kind create cluster --name ansible-operator-test
```

### 2. Load Images

```bash
# Build operator image (if not already built)
docker build -t kenchrcum/ansible-playbook-operator:0.1.0 .

# Load images into kind
kind load docker-image kenchrcum/ansible-playbook-operator:0.1.0 --name ansible-operator-test
kind load docker-image kenchrcum/ansible-runner:latest --name ansible-operator-test
```

### 3. Deploy Operator

```bash
helm install ansible-operator ./helm/ansible-playbook-operator \
  --create-namespace \
  --namespace ansible-operator-system \
  --set operator.watch.scope=all \
  --set operator.metrics.enabled=true \
  --wait
```

### 4. Run Tests

```bash
# Set kubeconfig
export KUBECONFIG="$(kind get kubeconfig --name ansible-operator-test)"

# Install test dependencies
source .venv/bin/activate
pip install -e ".[test]"

# Run tests
pytest tests/integration/ -v
```

### 5. Cleanup

```bash
kind delete cluster --name ansible-operator-test
```

## Test Structure

### Test Classes

- `TestRepositoryIntegration` - Tests Repository CR functionality
- `TestPlaybookIntegration` - Tests Playbook CR functionality
- `TestScheduleIntegration` - Tests Schedule CR and CronJob materialization
- `TestJobExecution` - Tests Job execution paths

### Key Test Scenarios

#### Repository Tests
- SSH authentication with pinned known_hosts
- HTTPS token authentication
- Connectivity probe job creation
- Security context enforcement

#### Playbook Tests
- Playbook validation against Repository
- Execution options configuration
- Manual run annotation handling

#### Schedule Tests
- CronJob materialization from Schedule CR
- Schedule status updates
- Concurrency policy enforcement

#### Job Execution Tests
- Manual run Job creation
- Job success/failure handling
- Status updates and event emission

## Configuration

### Environment Variables

- `KUBECONFIG` - Path to kubeconfig file (set automatically by script)
- `TEST_NAMESPACE` - Namespace for test resources (auto-generated)

### Test Configuration

Tests use the following defaults:
- Cluster name: `ansible-operator-test`
- Operator namespace: `ansible-operator-system`
- Operator image: `kenchrcum/ansible-playbook-operator:0.1.0`
- Executor image: `kenchrcum/ansible-runner:latest`

## Troubleshooting

### Common Issues

1. **Kind cluster creation fails**
   - Ensure Docker is running: `docker info`
   - Check available disk space: `df -h`
   - Verify kind installation: `kind version`
   - Try without PodSecurity: The script automatically falls back to a simpler configuration
   - Check system resources: `free -h` and `top`

2. **Kubelet health check timeout**
   - This is common with newer Kubernetes versions
   - The script automatically retries with a simpler configuration
   - Ensure Docker has sufficient resources allocated
   - Try restarting Docker: `sudo systemctl restart docker`

3. **Image loading fails**
   - Ensure images are built locally or available for pull
   - Check Docker daemon is running: `docker info`
   - Verify image names/tags
   - The script will attempt to build the operator image if missing

4. **Operator deployment fails**
   - Check Helm installation: `helm version`
   - Verify CRDs are available: `kubectl get crd`
   - Check operator logs: `kubectl logs -n ansible-operator-system deployment/ansible-operator`
   - Ensure images are loaded: `docker images | grep ansible`

5. **Tests fail**
   - Check operator is running: `kubectl get pods -n ansible-operator-system`
   - Verify CRDs are established: `kubectl get crd | grep ansible.cloud37.dev`
   - Check test namespace resources: `kubectl get all -n <test-namespace>`
   - Check operator logs for errors: `kubectl logs -n ansible-operator-system deployment/ansible-operator`

### Debug Mode

Run tests with verbose output:

```bash
./scripts/run-integration-tests.sh --verbose
```

### Keep Cluster for Debugging

Keep the cluster running after tests:

```bash
./scripts/run-integration-tests.sh --no-cleanup
```

Then manually inspect:

```bash
export KUBECONFIG="$(kind get kubeconfig --name ansible-operator-test)"
kubectl get all -A
kubectl logs -n ansible-operator-system deployment/ansible-operator
```

## Security Testing

The integration tests verify pod security defaults:

- `runAsNonRoot: true`
- `runAsUser: 1000`
- `runAsGroup: 1000`
- `allowPrivilegeEscalation: false`
- `readOnlyRootFilesystem: true`
- `seccompProfile.type: RuntimeDefault`
- `capabilities.drop: ["ALL"]`

These are enforced on all generated Jobs and CronJobs.

## Contributing

When adding new integration tests:

1. Follow the existing test structure
2. Use descriptive test names
3. Include proper cleanup in fixtures
4. Verify security defaults are enforced
5. Test both success and failure paths
6. Update this README if needed
