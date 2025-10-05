#!/bin/bash
# Script to update image digests in Helm values
# Usage: ./scripts/update-image-digests.sh [operator-tag] [executor-tag]

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
OPERATOR_TAG="${1:-latest}"
EXECUTOR_TAG="${2:-latest}"
VALUES_FILE="helm/ansible-playbook-operator/values.yaml"

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to get image digest
get_digest() {
    local image="$1"
    local digest

    if command_exists crane; then
        digest=$(crane digest "$image" 2>/dev/null)
    elif command_exists skopeo; then
        digest=$(skopeo inspect "docker://$image" --format "{{.Digest}}" 2>/dev/null)
    elif command_exists docker; then
        digest=$(docker manifest inspect "$image" 2>/dev/null | jq -r '.config.digest')
    else
        print_error "No tool available to get image digest. Please install crane, skopeo, or docker."
        exit 1
    fi

    if [[ -z "$digest" ]]; then
        print_error "Failed to get digest for image: $image"
        exit 1
    fi

    echo "$digest"
}

# Function to update digest in values file
update_digest() {
    local section="$1"
    local new_digest="$2"
    local temp_file=$(mktemp)

    # Update the digest in the values file
    sed "s|\(${section}:\)\s*\"sha256:[a-f0-9]\{64\}\"|\1 \"$new_digest\"|g" "$VALUES_FILE" > "$temp_file"

    # Check if the file was actually changed
    if ! diff -q "$VALUES_FILE" "$temp_file" >/dev/null; then
        mv "$temp_file" "$VALUES_FILE"
        print_status "Updated $section digest to: $new_digest"
    else
        rm "$temp_file"
        print_warning "No changes needed for $section digest"
    fi
}

# Main script
main() {
    print_status "Starting image digest update process"

    # Check if values file exists
    if [[ ! -f "$VALUES_FILE" ]]; then
        print_error "Values file not found: $VALUES_FILE"
        exit 1
    fi

    # Get operator image digest
    print_status "Getting operator image digest..."
    OPERATOR_IMAGE="kenchrcum/ansible-playbook-operator:$OPERATOR_TAG"
    OPERATOR_DIGEST=$(get_digest "$OPERATOR_IMAGE")
    print_status "Operator digest: $OPERATOR_DIGEST"

    # Get executor image digest
    print_status "Getting executor image digest..."
    EXECUTOR_IMAGE="kenchrcum/ansible-runner:$EXECUTOR_TAG"
    EXECUTOR_DIGEST=$(get_digest "$EXECUTOR_IMAGE")
    print_status "Executor digest: $EXECUTOR_DIGEST"

    # Update operator digest
    print_status "Updating operator digest..."
    update_digest "operator.image.digest" "$OPERATOR_DIGEST"

    # Update executor digest
    print_status "Updating executor digest..."
    update_digest "executorDefaults.image.digest" "$EXECUTOR_DIGEST"

    # Show final state
    print_status "Final digest configuration:"
    echo "Operator: $OPERATOR_DIGEST"
    echo "Executor: $EXECUTOR_DIGEST"

    # Show updated values file
    print_status "Updated values file:"
    grep -A 2 -B 2 "digest:" "$VALUES_FILE" || true

    print_status "Image digest update completed successfully!"

    # Optional: create a commit
    if command_exists git && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        if git diff --quiet "$VALUES_FILE"; then
            print_warning "No changes to commit"
        else
            read -p "Do you want to commit these changes? (y/N): " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                git add "$VALUES_FILE"
                git commit -m "chore: update image digests

- Operator: $OPERATOR_DIGEST
- Executor: $EXECUTOR_DIGEST"
                print_status "Changes committed successfully!"
            else
                print_warning "Changes not committed"
            fi
        fi
    fi
}

# Run main function
main "$@"
