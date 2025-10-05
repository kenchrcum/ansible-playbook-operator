from __future__ import annotations

from prometheus_client import Counter, Histogram, Gauge

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

WORKQUEUE_DEPTH = Gauge(
    "ansible_operator_workqueue_depth",
    "Current depth of the workqueue",
    labelnames=("kind",),
)

JOB_RUNS_TOTAL = Counter(
    "ansible_operator_job_runs_total",
    "Total number of Job runs",
    labelnames=("kind", "result"),
)

JOB_RUN_DURATION = Histogram(
    "ansible_operator_job_run_duration_seconds",
    "Duration of Job runs in seconds",
    labelnames=("kind",),
    buckets=(1, 5, 10, 30, 60, 300, 600, 1800, 3600),
)
