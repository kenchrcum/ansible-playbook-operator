# S3 Operator CRD Specifications

This document provides detailed specifications for all Custom Resource Definitions (CRDs) managed by the S3 Operator.

## API Group and Versioning

- **API Group**: `s3.cloud37.dev`
- **Initial Version**: `v1alpha1`
- **Version Evolution**: Follow Kubernetes versioning conventions; create `v1beta1` with conversion support when breaking changes are needed

## Common Patterns

### Status Conditions
All CRDs follow Kubernetes condition patterns:
- `type`: Condition type (e.g., `Ready`, `ProviderNotReady`)
- `status`: `True`, `False`, or `Unknown`
- `reason`: Machine-readable reason code
- `message`: Human-readable message
- `lastTransitionTime`: Timestamp of last state change
- `observedGeneration`: Generation of resource when condition was set

### Finalizers
- All CRDs use finalizer: `s3.cloud37.dev/finalizer`
- Finalizers ensure proper cleanup of provider resources

### Labels
- `s3.cloud37.dev/managed-by: s3-operator`
- `s3.cloud37.dev/provider-name: <provider-name>`
- Custom labels from spec propagated to owned resources

---

## Provider CRD

Represents an S3-compatible storage provider connection.

### Group Version
```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: providers.s3.cloud37.dev
spec:
  group: s3.cloud37.dev
  versions:
    - name: v1alpha1
```

### Spec Schema

```yaml
type: object
properties:
  spec:
    type: object
    required:
      - type
      - endpoint
      - region
      - auth
    properties:
      type:
        type: string
        enum: [wasabi, aws, minio, custom]
        description: S3 provider type

      endpoint:
        type: string
        format: uri
        description: Provider API endpoint URL (e.g., https://s3.wasabisys.com)

      region:
        type: string
        description: Provider region (e.g., us-east-1, us-west-1)

      auth:
        type: object
        required:
          - accessKeySecretRef
          - secretKeySecretRef
        properties:
          accessKeySecretRef:
            type: object
            required: [name]
            properties:
              name:
                type: string
                description: Name of Secret containing access key
              key:
                type: string
                default: access-key
                description: Key in Secret containing access key
              namespace:
                type: string
                description: Namespace of Secret (cross-namespace disallowed by default)

          secretKeySecretRef:
            type: object
            required: [name]
            properties:
              name:
                type: string
                description: Name of Secret containing secret key
              key:
                type: string
                default: secret-key
                description: Key in Secret containing secret key
              namespace:
                type: string

          sessionTokenSecretRef:
            type: object
            properties:
              name:
                type: string
              key:
                type: string
                default: session-token
              namespace:
                type: string
            description: Optional session token for temporary credentials

      tls:
        type: object
        properties:
          insecureSkipVerify:
            type: boolean
            default: false
            description: Skip TLS certificate verification

          caCertSecretRef:
            type: object
            properties:
              name:
                type: string
              key:
                type: string
                default: ca.crt
            description: CA certificate for custom TLS

      pathStyle:
        type: boolean
        default: true
        description: Use path-style addressing (required for Wasabi)

      retry:
        type: object
        properties:
          maxAttempts:
            type: integer
            default: 3
            minimum: 1
            maximum: 10

          backoffStrategy:
            type: string
            enum: [exponential, linear]
            default: exponential
```

### Status Schema

```yaml
type: object
properties:
  status:
    type: object
    properties:
      observedGeneration:
        type: integer
        description: Generation of resource when status was observed

      connected:
        type: boolean
        description: Whether provider connection is established

      lastConnectTime:
        type: string
        format: date-time
        description: Last successful connection time

      conditions:
        type: array
        items:
          type: object
          properties:
            type:
              type: string
            status:
              type: string
              enum: [True, False, Unknown]
            reason:
              type: string
            message:
              type: string
            lastTransitionTime:
              type: string
              format: date-time
            observedGeneration:
              type: integer
```

### Condition Types
- `AuthValid`: Credentials are valid
- `EndpointReachable`: Provider endpoint is reachable
- `Ready`: Provider is ready to use

---

## Bucket CRD

Represents an S3 bucket managed by the operator.

### Group Version
```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: buckets.s3.cloud37.dev
spec:
  group: s3.cloud37.dev
  versions:
    - name: v1alpha1
```

### Spec Schema

```yaml
type: object
properties:
  spec:
    type: object
    required:
      - providerRef
      - name
    properties:
      providerRef:
        type: object
        required: [name]
        properties:
          name:
            type: string
            description: Name of Provider resource
          namespace:
            type: string
            description: Namespace of Provider (cross-namespace disallowed by default)

      name:
        type: string
        pattern: '^[a-z0-9][a-z0-9\-\.]{1,61}[a-z0-9]$'
        description: Bucket name (must be DNS-compliant)

      region:
        type: string
        description: Override provider region

      versioning:
        type: object
        properties:
          enabled:
            type: boolean
            default: false

          mfaDelete:
            type: boolean
            default: false
            description: Require MFA for delete operations

      encryption:
        type: object
        properties:
          enabled:
            type: boolean
            default: false

          algorithm:
            type: string
            enum: [AES256, aws:kms]
            default: AES256

          kmsKeyId:
            type: string
            description: KMS key ID (required when algorithm is aws:kms)

      publicAccess:
        type: object
        properties:
          blockPublicAcls:
            type: boolean
            default: true

          blockPublicPolicy:
            type: boolean
            default: true

          ignorePublicAcls:
            type: boolean
            default: true

          restrictPublicBuckets:
            type: boolean
            default: true

      lifecycle:
        type: object
        properties:
          rules:
            type: array
            items:
              type: object
              required: [id]
              properties:
                id:
                  type: string
                  description: Unique rule identifier

                status:
                  type: string
                  enum: [Enabled, Disabled]
                  default: Enabled

                prefix:
                  type: string
                  description: Apply rule to objects with this prefix

                expiration:
                  type: object
                  properties:
                    days:
                      type: integer
                      minimum: 1
                    date:
                      type: string
                      format: date
                  description: Expiration rule (one of days or date)

                transitions:
                  type: array
                  items:
                    type: object
                    required: [days, storageClass]
                    properties:
                      days:
                        type: integer
                        minimum: 1
                      storageClass:
                        type: string
                        description: Target storage class (e.g., STANDARD_IA, GLACIER)

      cors:
        type: object
        properties:
          rules:
            type: array
            items:
              type: object
              required: [allowedOrigins, allowedMethods]
              properties:
                allowedOrigins:
                  type: array
                  items:
                    type: string

                allowedMethods:
                  type: array
                  items:
                    type: string
                    enum: [GET, POST, PUT, DELETE, HEAD]

                allowedHeaders:
                  type: array
                  items:
                    type: string

                exposedHeaders:
                  type: array
                  items:
                    type: string

                maxAgeSeconds:
                  type: integer
                  default: 3600
                  minimum: 0

      tagging:
        type: object
        properties:
          tags:
            type: object
            additionalProperties:
              type: string
```

### Status Schema

```yaml
type: object
properties:
  status:
    type: object
    properties:
      observedGeneration:
        type: integer

      bucketName:
        type: string
        description: Actual bucket name (may differ from spec)

      arn:
        type: string
        description: Bucket ARN (if available)

      exists:
        type: boolean
        description: Whether bucket exists in provider

      lastSyncTime:
        type: string
        format: date-time

      conditions:
        type: array
        items:
          type: object
```

### Condition Types
- `Ready`: Bucket is ready and synchronized
- `ProviderNotReady`: Referenced Provider is not ready
- `CreationFailed`: Bucket creation failed
- `PolicyConflict`: Bucket policy conflicts detected

---

## BucketPolicy CRD

Represents an IAM-style bucket policy document.

### Group Version
```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: bucketpolicies.s3.cloud37.dev
spec:
  group: s3.cloud37.dev
  versions:
    - name: v1alpha1
```

### Spec Schema

```yaml
type: object
properties:
  spec:
    type: object
    required:
      - bucketRef
      - policy
    properties:
      bucketRef:
        type: object
        required: [name]
        properties:
          name:
            type: string
            description: Name of Bucket resource
          namespace:
            type: string

      policy:
        type: object
        required: [version, statement]
        properties:
          version:
            type: string
            default: "2012-10-17"

          statement:
            type: array
            items:
              type: object
              required: [effect, principal, action, resource]
              properties:
                sid:
                  type: string
                  description: Statement ID

                effect:
                  type: string
                  enum: [Allow, Deny]

                principal:
                    oneOf:
                      - type: string
                      - type: object

                action:
                    oneOf:
                      - type: string
                      - type: array
                        items:
                          type: string

                resource:
                    oneOf:
                      - type: string
                      - type: array
                        items:
                          type: string

                condition:
                  type: object
                  description: Condition block for policy
```

### Status Schema

```yaml
type: object
properties:
  status:
    type: object
    properties:
      observedGeneration:
        type: integer

      applied:
        type: boolean
        description: Whether policy is applied to bucket

      lastSyncTime:
        type: string
        format: date-time

      conditions:
        type: array
        items:
          type: object
```

### Condition Types
- `Ready`: Policy is applied and synchronized
- `BucketNotReady`: Referenced Bucket is not ready
- `PolicyInvalid`: Policy document validation failed
- `ApplyFailed`: Failed to apply policy to bucket

---

## AccessKey CRD

Represents an access key pair for S3 authentication.

### Group Version
```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: accesskeys.s3.cloud37.dev
spec:
  group: s3.cloud37.dev
  versions:
    - name: v1alpha1
```

### Spec Schema

```yaml
type: object
properties:
  spec:
    type: object
    required:
      - providerRef
    properties:
      providerRef:
        type: object
        required: [name]
        properties:
          name:
            type: string
            description: Name of Provider resource
          namespace:
            type: string

      displayName:
        type: string
        description: Human-readable identifier

      policy:
        type: object
        description: Inline policy document (for IAM-like providers)

      tags:
        type: object
        additionalProperties:
          type: string

      rotate:
        type: object
        properties:
          enabled:
            type: boolean
            default: false

          intervalDays:
            type: integer
            default: 90
            minimum: 1
            maximum: 365

          previousKeysRetentionDays:
            type: integer
            default: 7
            minimum: 0
            maximum: 30
```

### Status Schema

```yaml
type: object
properties:
  status:
    type: object
    properties:
      observedGeneration:
        type: integer

      accessKeyId:
        type: string
        description: Access key ID (generated)

      created:
        type: boolean
        description: Whether key was created in provider

      lastRotateTime:
        type: string
        format: date-time

      nextRotateTime:
        type: string
        format: date-time

      conditions:
        type: array
        items:
          type: object
```

### Condition Types
- `Ready`: Access key is ready and synchronized
- `ProviderNotReady`: Referenced Provider is not ready
- `CreationFailed`: Access key creation failed
- `RotationFailed`: Access key rotation failed

---

## References and Cross-Resources

### Owner References
- `Bucket` → `Provider` (ownerReference)
- `BucketPolicy` → `Bucket` (ownerReference)
- `AccessKey` → `Provider` (ownerReference)

### Dependency Management
When `Provider` is deleted:
1. Check for dependent `Bucket`, `BucketPolicy`, and `AccessKey` resources
2. Block deletion if dependencies exist (or cascade delete based on configuration)
3. Update dependent resources with `ProviderNotReady` condition

When `Bucket` is deleted:
1. Check for dependent `BucketPolicy` resources
2. Optionally cascade delete policies
3. Update dependent resources with `BucketNotReady` condition
