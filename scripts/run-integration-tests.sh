#!/bin/bash
set -euo pipefail

# Integration test runner for Ansible Playbook Operator
# This script sets up a kind cluster, deploys the operator, and runs integration tests

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
CLUSTER_NAME="ansible-operator-test"
OPERATOR_IMAGE="kenchrcum/ansible-playbook-operator:dev"
EXECUTOR_IMAGE="kenchrcum/ansible-runner:latest"
NAMESPACE="ansible-operator-system"
VERBOSE=false
CLEANUP=true

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --cluster-name)
            CLUSTER_NAME="$2"
            shift 2
            ;;
        --operator-image)
            OPERATOR_IMAGE="$2"
            shift 2
            ;;
        --executor-image)
            EXECUTOR_IMAGE="$2"
            shift 2
            ;;
        --namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --no-cleanup)
            CLEANUP=false
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --cluster-name NAME     Kind cluster name (default: ansible-operator-test)"
            echo "  --operator-image IMAGE   Operator image (default: kenchrcum/ansible-playbook-operator:0.1.2)"
            echo "  --executor-image IMAGE   Executor image (default: kenchrcum/ansible-runner:latest)"
            echo "  --namespace NAME         Operator namespace (default: ansible-operator-system)"
            echo "  --verbose               Enable verbose output"
            echo "  --no-cleanup            Don't clean up cluster after tests"
            echo "  --help                  Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."

    local missing_tools=()

    if ! command -v kind &> /dev/null; then
        missing_tools+=("kind")
    fi

    if ! command -v helm &> /dev/null; then
        missing_tools+=("helm")
    fi

    if ! command -v docker &> /dev/null; then
        missing_tools+=("docker")
    else
        # Check if Docker daemon is running
        if ! docker info &> /dev/null; then
            log_error "Docker daemon is not running"
            log_error "Please start Docker and try again"
            exit 1
        fi
    fi

    if ! command -v python3 &> /dev/null; then
        missing_tools+=("python3")
    fi

    if [ ${#missing_tools[@]} -ne 0 ]; then
        log_error "Missing required tools: ${missing_tools[*]}"
        log_error "Please install the missing tools and try again"
        exit 1
    fi

    log_info "All prerequisites found"
}

# Create kind cluster
create_kind_cluster() {
    log_info "Creating kind cluster: $CLUSTER_NAME"

    # Check if cluster already exists
    if kind get clusters | grep -q "^$CLUSTER_NAME$"; then
        log_warn "Cluster $CLUSTER_NAME already exists"
        if [ "$CLEANUP" = true ]; then
            log_info "Deleting existing cluster..."
            kind delete cluster --name "$CLUSTER_NAME"
        else
            log_info "Using existing cluster"
            return
        fi
    fi

    # Create simple kind cluster configuration (more reliable)
    cat > /tmp/kind-config.yaml << EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
EOF

    # Create cluster with timeout
    log_info "Creating cluster (this may take a few minutes)..."
    if ! timeout 600 kind create cluster \
        --name "$CLUSTER_NAME" \
        --config /tmp/kind-config.yaml; then
        log_error "Failed to create kind cluster"
        log_error "Please check Docker daemon and system resources"
        exit 1
    fi

    # Clean up config file
    rm -f /tmp/kind-config.yaml

    log_info "Kind cluster created successfully"
}

# Build and load images
load_images() {
    log_info "Loading images into kind cluster..."

    # Load operator image
    if docker image inspect "$OPERATOR_IMAGE" &> /dev/null; then
        kind load docker-image "$OPERATOR_IMAGE" --name "$CLUSTER_NAME"
        log_info "Loaded operator image: $OPERATOR_IMAGE"
    else
        log_warn "Operator image $OPERATOR_IMAGE not found locally"

        # Try to build the image first
        if [ -f "$PROJECT_ROOT/Dockerfile" ]; then
            log_info "Building operator image..."
            docker build -t "$OPERATOR_IMAGE" "$PROJECT_ROOT"
            kind load docker-image "$OPERATOR_IMAGE" --name "$CLUSTER_NAME"
            log_info "Built and loaded operator image: $OPERATOR_IMAGE"
        else
            log_info "Pulling image..."
            docker pull "$OPERATOR_IMAGE"
            kind load docker-image "$OPERATOR_IMAGE" --name "$CLUSTER_NAME"
            log_info "Pulled and loaded operator image: $OPERATOR_IMAGE"
        fi
    fi

    # Load executor image
    if docker image inspect "$EXECUTOR_IMAGE" &> /dev/null; then
        kind load docker-image "$EXECUTOR_IMAGE" --name "$CLUSTER_NAME"
        log_info "Loaded executor image: $EXECUTOR_IMAGE"
    else
        log_warn "Executor image $EXECUTOR_IMAGE not found locally"
        log_info "Pulling image..."
        docker pull "$EXECUTOR_IMAGE"
        kind load docker-image "$EXECUTOR_IMAGE" --name "$CLUSTER_NAME"
    fi
}

# Deploy operator
deploy_operator() {
    log_info "Deploying operator to kind cluster..."

    # Extract image tag and digest
    local operator_tag
    local operator_digest=""

    if [[ "$OPERATOR_IMAGE" =~ :([^@]+) ]]; then
        operator_tag="${BASH_REMATCH[1]}"
    else
        operator_tag="latest"
    fi

    if [[ "$OPERATOR_IMAGE" =~ @(sha256:[a-f0-9]+) ]]; then
        operator_digest="${BASH_REMATCH[1]}"
    fi

    # Deploy with Helm (disable ServiceMonitor for kind cluster, use Never pull policy for loaded images)
    helm install ansible-operator "$PROJECT_ROOT/helm/ansible-playbook-operator" \
        --create-namespace \
        --namespace "$NAMESPACE" \
        --set "operator.image.tag=$operator_tag" \
        --set "operator.image.digest=$operator_digest" \
        --set "operator.image.pullPolicy=Never" \
        --set "operator.watch.scope=all" \
        --set "operator.metrics.enabled=true" \
        --set "operator.metrics.serviceMonitor.enabled=false" \
        --set "executorDefaults.image.tag=${EXECUTOR_IMAGE##*:}" \
        --set "executorDefaults.image.pullPolicy=Never" \
        --set "rbac.preset=scoped" \
        --wait \
        --timeout 5m

    log_info "Operator deployed successfully"
}

# Wait for operator to be ready
wait_for_operator() {
    log_info "Waiting for operator to be ready..."

    # Wait for deployment (using the correct Helm-generated name)
    kubectl wait --for=condition=available \
        --timeout=300s \
        deployment/ansible-operator-ansible-playbook-operator \
        -n "$NAMESPACE"

    # Wait for CRDs
    kubectl wait --for condition=established \
        --timeout=60s \
        crd/repositories.ansible.cloud37.dev

    kubectl wait --for condition=established \
        --timeout=60s \
        crd/playbooks.ansible.cloud37.dev

    kubectl wait --for condition=established \
        --timeout=60s \
        crd/schedules.ansible.cloud37.dev

    log_info "Operator is ready"
}

# Run integration tests
run_tests() {
    log_info "Running integration tests..."

    # Change to project root
    cd "$PROJECT_ROOT"

    # Set kubeconfig
    local kubeconfig_file="/tmp/kubeconfig-${CLUSTER_NAME}.yaml"
    kind get kubeconfig --name "$CLUSTER_NAME" > "$kubeconfig_file"
    export KUBECONFIG="$kubeconfig_file"
    export KIND_CLUSTER_NAME="$CLUSTER_NAME"

    # Install test dependencies
    if [ -f .venv/bin/activate ]; then
        source .venv/bin/activate
    else
        log_info "Creating virtual environment..."
        python3 -m venv .venv
        source .venv/bin/activate
        pip install -e ".[test]"
    fi

    # Run pytest
    local pytest_args=()
    if [ "$VERBOSE" = true ]; then
        pytest_args+=("-v")
    else
        pytest_args+=("-q")
    fi

    pytest "${pytest_args[@]}" tests/integration/

    log_info "Integration tests completed"
}

# Cleanup function
cleanup() {
    # Clean up temporary kubeconfig file
    local kubeconfig_file="/tmp/kubeconfig-${CLUSTER_NAME}.yaml"
    if [ -f "$kubeconfig_file" ]; then
        rm -f "$kubeconfig_file"
    fi

    if [ "$CLEANUP" = true ]; then
        log_info "Cleaning up kind cluster..."
        kind delete cluster --name "$CLUSTER_NAME"
        log_info "Cleanup completed"
    else
        log_info "Skipping cleanup (--no-cleanup specified)"
        log_info "Cluster $CLUSTER_NAME is still running"
        log_info "Kubeconfig: $(kind get kubeconfig --name "$CLUSTER_NAME")"
    fi
}

# Main execution
main() {
    log_info "Starting Ansible Playbook Operator integration tests"
    log_info "Cluster: $CLUSTER_NAME"
    log_info "Operator image: $OPERATOR_IMAGE"
    log_info "Executor image: $EXECUTOR_IMAGE"
    log_info "Namespace: $NAMESPACE"

    # Set up trap for cleanup
    trap cleanup EXIT

    # Run steps
    check_prerequisites
    create_kind_cluster
    load_images
    deploy_operator
    wait_for_operator
    run_tests

    log_info "Integration tests completed successfully!"
}

# Run main function
main "$@"
