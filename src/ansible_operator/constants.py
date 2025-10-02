API_GROUP = "ansible.cloud37.dev"
API_VERSION = "v1alpha1"
API_GROUP_VERSION = f"{API_GROUP}/{API_VERSION}"

# Label and annotation keys
LABEL_MANAGED_BY = f"{API_GROUP}/managed-by"
LABEL_OWNER_KIND = f"{API_GROUP}/owner-kind"
LABEL_OWNER_NAME = f"{API_GROUP}/owner-name"
LABEL_OWNER_UID = f"{API_GROUP}/owner-uid"
LABEL_RUN_ID = f"{API_GROUP}/run-id"
LABEL_REVISION = f"{API_GROUP}/revision"

FINALIZER = f"{API_GROUP}/finalizer"

# Condition types
COND_READY = "Ready"
COND_AUTH_VALID = "AuthValid"
COND_CLONE_READY = "CloneReady"
COND_BLOCKED_BY_CONCURRENCY = "BlockedByConcurrency"

# Annotation keys
ANNOTATION_RUN_NOW = f"{API_GROUP}/run-now"
