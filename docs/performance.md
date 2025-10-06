# Performance Tuning Guide

This guide covers performance optimization for the Ansible Playbook Operator.

## Table of Contents

- [Performance Overview](#performance-overview)
- [Resource Sizing](#resource-sizing)
- [Concurrency Tuning](#concurrency-tuning)
- [Cache Optimization](#cache-optimization)
- [Network Optimization](#network-optimization)
- [Storage Optimization](#storage-optimization)
- [Monitoring Performance](#monitoring-performance)
- [Benchmarking](#benchmarking)

## Performance Overview

The operator's performance depends on several factors:

- **Resource allocation**: CPU, memory, and storage
- **Concurrency settings**: Worker count and timeouts
- **Cache utilization**: PVC cache for Ansible collections
- **Network configuration**: Git clone and execution
- **Storage performance**: PVC performance characteristics

## Resource Sizing

### Operator Resources

**Minimum Requirements:**
```yaml
operator:
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 512Mi
```

**Recommended for Production:**
```yaml
operator:
  resources:
    requests:
      cpu: 200m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 1Gi
```

**High-Load Environments:**
```yaml
operator:
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: 2000m
      memory: 2Gi
```

### Executor Resources

**Default Configuration:**
```yaml
executorDefaults:
  resources:
    requests:
      cpu: 200m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 1Gi
```

**Resource Guidelines:**
- **CPU**: 200m-2000m depending on Ansible workload
- **Memory**: 256Mi-4Gi depending on inventory size
- **Storage**: 1Gi-10Gi for workspace and cache

### Resource Monitoring

**CPU Usage:**
```bash
# Check operator CPU usage
kubectl top pods -n ansible-operator-system

# Monitor CPU metrics
kubectl port-forward -n monitoring service/prometheus 9090:9090
# Query: rate(container_cpu_usage_seconds_total{pod=~"ansible-playbook-operator-.*"}[5m])
```

**Memory Usage:**
```bash
# Check operator memory usage
kubectl top pods -n ansible-operator-system

# Monitor memory metrics
# Query: container_memory_usage_bytes{pod=~"ansible-playbook-operator-.*"}
```

## Concurrency Tuning

### Worker Configuration

**Default Settings:**
```yaml
operator:
  env:
    - name: KOPF_MAX_WORKERS
      value: "4"
    - name: KOPF_REQUEST_TIMEOUT
      value: "30"
```

**Performance Tuning:**
```yaml
operator:
  env:
    - name: KOPF_MAX_WORKERS
      value: "8"  # Increase for high-load environments
    - name: KOPF_REQUEST_TIMEOUT
      value: "60"  # Increase for slow API responses
```

**Worker Guidelines:**
- **Low load**: 2-4 workers
- **Medium load**: 4-8 workers
- **High load**: 8-16 workers
- **Maximum**: 32 workers (Kubernetes API limits)

### Concurrency Policies

**Schedule Concurrency:**
```yaml
apiVersion: ansible.cloud37.dev/v1alpha1
kind: Schedule
metadata:
  name: high-frequency-schedule
spec:
  playbookRef:
    name: my-playbook
  schedule: "*/5 * * * *"  # Every 5 minutes
  concurrencyPolicy: "Replace"  # Allow overlapping executions
  backoffLimit: 3
  ttlSecondsAfterFinished: 300
```

**Concurrency Options:**
- **Forbid**: Prevent overlapping executions (default)
- **Allow**: Allow overlapping executions
- **Replace**: Cancel previous execution and start new one

### Performance Impact

**Worker Count Impact:**
- **Too few workers**: Resource underutilization
- **Too many workers**: API rate limiting, memory pressure
- **Optimal**: Balance between throughput and resource usage

**Timeout Impact:**
- **Too short**: Premature timeouts, failed reconciliations
- **Too long**: Resource blocking, slow response
- **Optimal**: Match expected operation duration

## Cache Optimization

### PVC Cache Strategy

**Basic Configuration:**
```yaml
executorDefaults:
  cache:
    strategy: pvc
    createPVC: true
    storageSize: "10Gi"
    storageClassName: "fast-ssd"
```

**Performance Configuration:**
```yaml
executorDefaults:
  cache:
    strategy: pvc
    createPVC: true
    storageSize: "50Gi"
    storageClassName: "ultra-fast-ssd"
```

### Cache Benefits

**Performance Improvements:**
- **Collections**: 50-80% faster Ansible Galaxy installs
- **Roles**: 30-60% faster role downloads
- **Dependencies**: 40-70% faster requirement resolution

**Storage Requirements:**
- **Small projects**: 5-10Gi
- **Medium projects**: 10-25Gi
- **Large projects**: 25-100Gi

### Cache Management

**Cache Monitoring:**
```bash
# Check cache usage
kubectl exec -n ansible-operator-system deployment/ansible-playbook-operator -- df -h /cache

# Monitor cache performance
kubectl port-forward -n monitoring service/prometheus 9090:9090
# Query: kubelet_volume_stats_used_bytes{persistentvolumeclaim="ansible-cache-pvc"}
```

**Cache Optimization:**
```yaml
# Repository-specific cache
apiVersion: ansible.cloud37.dev/v1alpha1
kind: Repository
metadata:
  name: large-repo
spec:
  url: https://github.com/company/large-ansible-repo.git
  cache:
    strategy: pvc
    pvcName: "large-repo-cache"
```

## Network Optimization

### Git Clone Optimization

**Shallow Clone:**
```yaml
apiVersion: ansible.cloud37.dev/v1alpha1
kind: Repository
metadata:
  name: optimized-repo
spec:
  url: https://github.com/company/repo.git
  branch: main
  # Shallow clone is used by default for performance
```

**Clone Performance:**
- **Shallow clone**: 50-80% faster than full clone
- **Branch-specific**: 30-50% faster than default branch
- **Revision pinning**: 20-40% faster than branch tip

### Network Policies

**Performance Impact:**
```yaml
networkPolicies:
  enabled: true
  preset: moderate  # Balance between security and performance
```

**Network Optimization:**
- **DNS caching**: Enable cluster DNS caching
- **Connection pooling**: Use persistent connections
- **Bandwidth limits**: Set appropriate limits

### Network Monitoring

**Latency Monitoring:**
```bash
# Check network latency
kubectl run network-test --image=alpine --rm -it -- sh
# Inside pod: ping github.com

# Monitor network metrics
kubectl port-forward -n monitoring service/prometheus 9090:9090
# Query: rate(container_network_receive_bytes_total[5m])
```

## Storage Optimization

### PVC Performance

**Storage Class Selection:**
```yaml
executorDefaults:
  cache:
    storageClassName: "fast-ssd"  # High IOPS for cache
```

**Performance Characteristics:**
- **SSD**: High IOPS, low latency
- **HDD**: Lower cost, higher latency
- **NVMe**: Highest performance, highest cost

### Storage Monitoring

**IOPS Monitoring:**
```bash
# Check storage performance
kubectl exec -n ansible-operator-system deployment/ansible-playbook-operator -- iostat -x 1

# Monitor storage metrics
kubectl port-forward -n monitoring service/prometheus 9090:9090
# Query: rate(container_fs_io_time_seconds_total[5m])
```

### Storage Optimization

**Cache Layout:**
```yaml
# Optimize cache layout
executorDefaults:
  cache:
    strategy: pvc
    storageSize: "20Gi"
    storageClassName: "fast-ssd"
```

**Workspace Optimization:**
- **EmptyDir**: Fast local storage for workspace
- **PVC**: Persistent storage for cache
- **Memory**: In-memory storage for temporary files

## Monitoring Performance

### Key Metrics

**Reconciliation Performance:**
```promql
# Reconciliation rate
rate(ansible_operator_reconcile_total[5m])

# Reconciliation duration
histogram_quantile(0.95, rate(ansible_operator_reconcile_duration_seconds_bucket[5m]))

# Error rate
rate(ansible_operator_reconcile_total{result="error"}[5m])
```

**Job Execution Performance:**
```promql
# Job execution rate
rate(ansible_operator_job_runs_total[5m])

# Job duration
histogram_quantile(0.95, rate(ansible_operator_job_run_duration_seconds_bucket[5m]))

# Failure rate
rate(ansible_operator_job_runs_total{result="failure"}[5m])
```

### Performance Alerts

**Performance Alerts:**
```yaml
groups:
- name: ansible-operator-performance
  rules:
  - alert: HighReconciliationLatency
    expr: histogram_quantile(0.95, rate(ansible_operator_reconcile_duration_seconds_bucket[5m])) > 10
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High reconciliation latency"
      description: "95th percentile latency is {{ $value }} seconds"

  - alert: HighJobDuration
    expr: histogram_quantile(0.95, rate(ansible_operator_job_run_duration_seconds_bucket[5m])) > 300
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High job execution duration"
      description: "95th percentile duration is {{ $value }} seconds"
```

### Performance Dashboards

**Grafana Dashboard:**
```json
{
  "dashboard": {
    "title": "Ansible Operator Performance",
    "panels": [
      {
        "title": "Reconciliation Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(ansible_operator_reconcile_total[5m])",
            "legendFormat": "{{kind}} - {{result}}"
          }
        ]
      },
      {
        "title": "Reconciliation Duration",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, rate(ansible_operator_reconcile_duration_seconds_bucket[5m]))",
            "legendFormat": "95th percentile - {{kind}}"
          }
        ]
      },
      {
        "title": "Resource Usage",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(container_cpu_usage_seconds_total{pod=~\"ansible-playbook-operator-.*\"}[5m])",
            "legendFormat": "CPU Usage"
          },
          {
            "expr": "container_memory_usage_bytes{pod=~\"ansible-playbook-operator-.*\"}",
            "legendFormat": "Memory Usage"
          }
        ]
      }
    ]
  }
}
```

## Benchmarking

### Performance Tests

**Reconciliation Benchmark:**
```bash
# Create multiple resources
for i in {1..100}; do
  kubectl apply -f - <<EOF
apiVersion: ansible.cloud37.dev/v1alpha1
kind: Repository
metadata:
  name: test-repo-$i
spec:
  url: https://github.com/company/test-repo.git
EOF
done

# Monitor reconciliation performance
kubectl get events --field-selector involvedObject.kind=Repository --sort-by='.lastTimestamp'
```

**Job Execution Benchmark:**
```bash
# Create multiple schedules
for i in {1..50}; do
  kubectl apply -f - <<EOF
apiVersion: ansible.cloud37.dev/v1alpha1
kind: Schedule
metadata:
  name: test-schedule-$i
spec:
  playbookRef:
    name: test-playbook
  schedule: "*/1 * * * *"
  concurrencyPolicy: "Allow"
EOF
done

# Monitor job execution performance
kubectl get jobs -l ansible.cloud37.dev/managed-by=ansible-operator
```

### Performance Baselines

**Expected Performance:**
- **Reconciliation**: < 1 second for simple resources
- **Job execution**: < 5 minutes for typical playbooks
- **Resource creation**: < 30 seconds for complex resources
- **Cache hit rate**: > 80% for repeated operations

**Performance Targets:**
- **Reconciliation latency**: 95th percentile < 10 seconds
- **Job execution time**: 95th percentile < 300 seconds
- **Error rate**: < 1% of total operations
- **Resource utilization**: < 80% of limits

### Optimization Checklist

**Pre-Deployment:**
- [ ] Set appropriate resource limits
- [ ] Configure concurrency settings
- [ ] Enable cache optimization
- [ ] Set up performance monitoring
- [ ] Establish performance baselines

**Post-Deployment:**
- [ ] Monitor resource usage
- [ ] Track performance metrics
- [ ] Identify bottlenecks
- [ ] Optimize configurations
- [ ] Validate improvements

**Ongoing Optimization:**
- [ ] Regular performance reviews
- [ ] Capacity planning
- [ ] Performance testing
- [ ] Optimization updates
- [ ] Performance documentation
