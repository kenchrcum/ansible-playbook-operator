# Backward Compatibility Policy

This document establishes the policy for maintaining backward compatibility during CRD schema evolution and version bumps for the Ansible Playbook Operator.

## Versioning Strategy

### Version Lifecycle

The operator follows Kubernetes API versioning conventions:

- **v1alpha1** (current): Initial version with experimental features
- **v1beta1** (future): Stable API with potential breaking changes
- **v1** (future): Stable API with guaranteed backward compatibility

### Version Promotion Criteria

#### v1alpha1 → v1beta1
- API has been stable for at least 6 months
- No breaking changes planned for the next 12 months
- All critical features are implemented and tested
- Migration path is documented and tested
- Community feedback indicates API is ready for stability

#### v1beta1 → v1
- API has been stable for at least 12 months
- No breaking changes planned for the next 24 months
- All features are production-ready
- Comprehensive migration tooling is available
- Community consensus on API stability

## Schema Evolution Rules

### Allowed Changes (Non-Breaking)

#### Field Additions
- **Always allowed**: Adding new optional fields with defaults
- **Always allowed**: Adding new fields to `status` subresource
- **Always allowed**: Adding new printer columns
- **Always allowed**: Adding new enum values (append-only)

#### Field Modifications
- **Allowed**: Making optional fields required (with default values)
- **Allowed**: Relaxing validation constraints (e.g., increasing max length)
- **Allowed**: Adding new validation rules that don't reject existing valid data
- **Allowed**: Changing field descriptions and documentation

#### Structural Changes
- **Allowed**: Adding new subresources (e.g., `status`, `scale`)
- **Allowed**: Adding new API groups or versions
- **Allowed**: Adding new resource kinds

### Prohibited Changes (Breaking)

#### Field Removals
- **Never allowed**: Removing any field from `spec` or `status`
- **Never allowed**: Removing enum values
- **Never allowed**: Removing required fields

#### Field Modifications
- **Never allowed**: Changing field types (string → int, object → array, etc.)
- **Never allowed**: Making required fields optional
- **Never allowed**: Tightening validation constraints that reject existing data
- **Never allowed**: Changing field names

#### Structural Changes
- **Never allowed**: Removing subresources
- **Never allowed**: Changing resource scope (Namespaced ↔ Cluster)
- **Never allowed**: Changing resource names (kind, plural, singular)

## Breaking Change Process

### When Breaking Changes Are Necessary

Breaking changes should only be considered when:
1. Security vulnerabilities require field removal or type changes
2. Fundamental design flaws prevent proper operation
3. Kubernetes API conventions require structural changes
4. Performance requirements necessitate incompatible changes

### Breaking Change Workflow

1. **Proposal Phase**
   - Create detailed RFC explaining the necessity
   - Document impact assessment and migration complexity
   - Propose new version (e.g., v1beta1) with conversion strategy
   - Community review and approval

2. **Implementation Phase**
   - Implement new version alongside existing version
   - Add conversion webhooks for automatic migration
   - Create migration tooling and documentation
   - Comprehensive testing of conversion paths

3. **Deprecation Phase**
   - Announce deprecation with timeline
   - Provide migration guides and tooling
   - Support both versions for deprecation period
   - Monitor migration progress

4. **Removal Phase**
   - Remove deprecated version after grace period
   - Update documentation and examples
   - Clean up conversion webhooks

## Conversion Strategy

### Automatic Conversion

For breaking changes, implement conversion webhooks:

```yaml
# Example conversion webhook configuration
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
spec:
  versions:
    - name: v1alpha1
      served: true
      storage: false
      # ... schema
    - name: v1beta1
      served: true
      storage: true
      # ... schema
  conversion:
    strategy: Webhook
    webhook:
      clientConfig:
        service:
          name: ansible-operator-webhook
          namespace: ansible-operator-system
          path: /convert
      conversionReviewVersions: ["v1"]
```

### Conversion Functions

Implement conversion functions in the operator:

```python
# Example conversion function
def convert_v1alpha1_to_v1beta1(original):
    """Convert v1alpha1 Playbook to v1beta1 format."""
    converted = original.copy()

    # Handle field renames
    if 'oldFieldName' in converted['spec']:
        converted['spec']['newFieldName'] = converted['spec'].pop('oldFieldName')

    # Handle structural changes
    if 'legacyConfig' in converted['spec']:
        converted['spec']['config'] = {
            'type': 'legacy',
            'value': converted['spec'].pop('legacyConfig')
        }

    return converted
```

### Manual Migration

For complex changes, provide migration tools:

```bash
# Example migration script
ansible-operator migrate --from v1alpha1 --to v1beta1 --namespace my-namespace
```

## Deprecation Policy

### Deprecation Timeline

- **Announcement**: 6 months before removal
- **Warning Period**: 3 months with warnings in logs/events
- **Removal**: After grace period expires

### Deprecation Notices

Add deprecation annotations to CRDs:

```yaml
# Example deprecation annotation
metadata:
  annotations:
    deprecated: "true"
    deprecation-date: "2024-06-01"
    removal-date: "2024-12-01"
    replacement: "v1beta1"
```

### User Communication

- **Release Notes**: Clear deprecation notices
- **Documentation**: Migration guides and examples
- **Events**: Emit deprecation warnings in operator events
- **Logs**: Include deprecation warnings in structured logs

## Testing Requirements

### Conversion Testing

- **Unit Tests**: Test all conversion functions
- **Integration Tests**: Test conversion webhooks
- **E2E Tests**: Test migration of existing resources
- **Performance Tests**: Ensure conversion doesn't impact performance

### Migration Testing

- **Backup/Restore**: Test migration with existing data
- **Rollback**: Test rollback scenarios
- **Edge Cases**: Test migration of malformed or incomplete data

## Documentation Requirements

### Migration Guides

For each breaking change, provide:
- **Impact Assessment**: What changes and why
- **Migration Steps**: Step-by-step instructions
- **Examples**: Before/after examples
- **Troubleshooting**: Common issues and solutions

### Version Compatibility Matrix

| Operator Version | Supported CRD Versions | Notes |
|------------------|------------------------|-------|
| 0.1.x | v1alpha1 | Initial release |
| 0.2.x | v1alpha1, v1beta1 | Conversion support |
| 1.0.x | v1beta1, v1 | v1alpha1 deprecated |

## Implementation Guidelines

### Code Organization

```
src/ansible_operator/
├── api/
│   ├── v1alpha1/
│   │   ├── __init__.py
│   │   ├── playbook.py
│   │   ├── repository.py
│   │   └── schedule.py
│   ├── v1beta1/
│   │   ├── __init__.py
│   │   ├── playbook.py
│   │   ├── repository.py
│   │   └── schedule.py
│   └── conversion/
│       ├── __init__.py
│       ├── playbook.py
│       ├── repository.py
│       └── schedule.py
```

### Conversion Webhook

```python
# Example conversion webhook handler
@kopf.on.startup()
def register_conversion_webhook(**kwargs):
    """Register conversion webhook for CRD version conversion."""
    # Implementation details
    pass

def handle_conversion_request(request):
    """Handle CRD conversion requests."""
    # Parse request
    # Apply conversion functions
    # Return converted objects
    pass
```

## Monitoring and Observability

### Metrics

- `ansible_operator_conversion_total{from_version,to_version,result}`
- `ansible_operator_conversion_duration_seconds{from_version,to_version}`
- `ansible_operator_deprecated_api_usage_total{version,resource}`

### Events

- `ConversionSucceeded` / `ConversionFailed`
- `DeprecationWarning` / `DeprecationError`
- `MigrationStarted` / `MigrationCompleted`

### Logs

```json
{
  "level": "warning",
  "message": "Using deprecated API version",
  "resource": "playbook",
  "version": "v1alpha1",
  "deprecation_date": "2024-06-01",
  "removal_date": "2024-12-01",
  "replacement": "v1beta1"
}
```

## Security Considerations

### Conversion Security

- **Validation**: Validate converted objects
- **Sanitization**: Sanitize input data
- **Authorization**: Ensure conversion webhook has proper RBAC
- **Audit**: Log all conversion attempts

### Migration Security

- **Backup**: Require backups before migration
- **Rollback**: Provide rollback procedures
- **Testing**: Test migration in non-production environments
- **Monitoring**: Monitor migration progress and failures

## Compliance and Governance

### Review Process

- **Architecture Review**: All breaking changes require architecture review
- **Security Review**: Security implications must be assessed
- **Community Review**: Breaking changes require community consensus
- **Documentation Review**: Migration guides must be reviewed

### Approval Authority

- **Minor Changes**: Maintainer approval
- **Breaking Changes**: Architecture team approval
- **Security Changes**: Security team approval
- **Community Changes**: Community vote

## References

- [Kubernetes API Versioning](https://kubernetes.io/docs/reference/using-api/api-versioning/)
- [CRD Versioning](https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definition-versioning/)
- [API Deprecation Policy](https://kubernetes.io/docs/reference/using-api/deprecation-policy/)
- [Conversion Webhooks](https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definition-versioning/#conversion-webhook)
