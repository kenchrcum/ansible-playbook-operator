from __future__ import annotations

from prometheus_client import Counter, Histogram

RECONCILE_TOTAL = Counter(
    "ansible_operator_reconcile_total",
    "Number of reconciliations",
    labelnames=("kind", "result"),
)

RECONCILE_DURATION = Histogram(
    "ansible_operator_reconcile_duration_seconds",
    "Duration of reconciliations in seconds",
    labelnames=("kind",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
