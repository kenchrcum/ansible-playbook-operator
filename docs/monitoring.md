# Monitoring and Alerting Setup

This guide covers monitoring, alerting, and observability for the Ansible Playbook Operator.

## Table of Contents

- [Monitoring Overview](#monitoring-overview)
- [Prometheus Metrics](#prometheus-metrics)
- [Grafana Dashboards](#grafana-dashboards)
- [Alerting Rules](#alerting-rules)
- [Log Aggregation](#log-aggregation)
- [Health Checks](#health-checks)
- [Performance Monitoring](#performance-monitoring)
- [Troubleshooting Monitoring](#troubleshooting-monitoring)

## Monitoring Overview

The operator provides comprehensive observability through:

- **Metrics**: Prometheus-compatible metrics
- **Events**: Kubernetes Events for lifecycle transitions
- **Logs**: Structured JSON logs with correlation IDs
- **Status**: Resource status conditions and fields

## Prometheus Metrics

### Enable Metrics

**Basic Configuration:**
```yaml
operator:
  metrics:
    enabled: true
```

**ServiceMonitor Configuration:**
```yaml
operator:
  metrics:
    enabled: true
    serviceMonitor:
      enabled: true
```

### Available Metrics

**Reconciliation Metrics:**
- `ansible_operator_reconcile_total{kind, result}` - Reconciliation counts
- `ansible_operator_reconcile_duration_seconds{kind}` - Reconciliation latency

**Job Execution Metrics:**
- `ansible_operator_job_runs_total{kind, result}` - Job execution counts
- `ansible_operator_job_run_duration_seconds{kind}` - Job execution duration

**Workqueue Metrics:**
- `ansible_operator_workqueue_depth` - Workqueue depth
- `ansible_operator_workqueue_adds_total` - Workqueue additions

### Metrics Endpoint

**Access Metrics:**
```bash
# Port forward to metrics endpoint
kubectl port-forward -n ansible-operator-system service/ansible-playbook-operator 8080:8080

# Query metrics
curl http://localhost:8080/metrics
```

**Sample Metrics Output:**
```
# HELP ansible_operator_reconcile_total Total number of reconciliations
# TYPE ansible_operator_reconcile_total counter
ansible_operator_reconcile_total{kind="Repository",result="success"} 42
ansible_operator_reconcile_total{kind="Repository",result="error"} 3
ansible_operator_reconcile_total{kind="Playbook",result="success"} 38
ansible_operator_reconcile_total{kind="Playbook",result="error"} 1
ansible_operator_reconcile_total{kind="Schedule",result="success"} 25
ansible_operator_reconcile_total{kind="Schedule",result="error"} 0

# HELP ansible_operator_reconcile_duration_seconds Duration of reconciliations
# TYPE ansible_operator_reconcile_duration_seconds histogram
ansible_operator_reconcile_duration_seconds_bucket{kind="Repository",le="0.1"} 15
ansible_operator_reconcile_duration_seconds_bucket{kind="Repository",le="0.5"} 35
ansible_operator_reconcile_duration_seconds_bucket{kind="Repository",le="1.0"} 42
ansible_operator_reconcile_duration_seconds_bucket{kind="Repository",le="+Inf"} 45
ansible_operator_reconcile_duration_seconds_sum{kind="Repository"} 18.5
ansible_operator_reconcile_duration_seconds_count{kind="Repository"} 45
```

## Grafana Dashboards

### Operator Dashboard

**Dashboard Configuration:**
```json
{
  "dashboard": {
    "title": "Ansible Playbook Operator",
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
        "title": "Job Execution Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(ansible_operator_job_runs_total[5m])",
            "legendFormat": "{{kind}} - {{result}}"
          }
        ]
      },
      {
        "title": "Job Duration",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, rate(ansible_operator_job_run_duration_seconds_bucket[5m]))",
            "legendFormat": "95th percentile - {{kind}}"
          }
        ]
      }
    ]
  }
}
```

### Resource Status Dashboard

**Status Metrics:**
```json
{
  "dashboard": {
    "title": "Ansible Resources Status",
    "panels": [
      {
        "title": "Repository Status",
        "type": "stat",
        "targets": [
          {
            "expr": "count by (status) (kube_customresource_status_condition{resource=\"repositories\", condition=\"Ready\"})",
            "legendFormat": "{{status}}"
          }
        ]
      },
      {
        "title": "Playbook Status",
        "type": "stat",
        "targets": [
          {
            "expr": "count by (status) (kube_customresource_status_condition{resource=\"playbooks\", condition=\"Ready\"})",
            "legendFormat": "{{status}}"
          }
        ]
      },
      {
        "title": "Schedule Status",
        "type": "stat",
        "targets": [
          {
            "expr": "count by (status) (kube_customresource_status_condition{resource=\"schedules\", condition=\"Ready\"})",
            "legendFormat": "{{status}}"
          }
        ]
      }
    ]
  }
}
```

## Alerting Rules

### Critical Alerts

**Operator Down:**
```yaml
groups:
- name: ansible-operator-critical
  rules:
  - alert: AnsibleOperatorDown
    expr: up{job="ansible-playbook-operator"} == 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Ansible Playbook Operator is down"
      description: "The operator has been down for more than 1 minute"

  - alert: HighReconciliationErrors
    expr: rate(ansible_operator_reconcile_total{result="error"}[5m]) > 0.1
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "High rate of reconciliation errors"
      description: "Reconciliation error rate is {{ $value }} errors/second"
```

### Warning Alerts

**Performance Alerts:**
```yaml
groups:
- name: ansible-operator-warning
  rules:
  - alert: HighReconciliationLatency
    expr: histogram_quantile(0.95, rate(ansible_operator_reconcile_duration_seconds_bucket[5m])) > 10
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High reconciliation latency"
      description: "95th percentile latency is {{ $value }} seconds"

  - alert: HighJobFailureRate
    expr: rate(ansible_operator_job_runs_total{result="failure"}[5m]) > 0.05
    for: 3m
    labels:
      severity: warning
    annotations:
      summary: "High job failure rate"
      description: "Job failure rate is {{ $value }} failures/second"

  - alert: WorkqueueBacklog
    expr: ansible_operator_workqueue_depth > 100
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "Workqueue backlog is high"
      description: "Workqueue depth is {{ $value }} items"
```

### Info Alerts

**Operational Alerts:**
```yaml
groups:
- name: ansible-operator-info
  rules:
  - alert: RepositoryNotReady
    expr: kube_customresource_status_condition{resource="repositories", condition="Ready", status="False"} == 1
    for: 5m
    labels:
      severity: info
    annotations:
      summary: "Repository not ready"
      description: "Repository {{ $labels.name }} is not ready"

  - alert: PlaybookNotReady
    expr: kube_customresource_status_condition{resource="playbooks", condition="Ready", status="False"} == 1
    for: 5m
    labels:
      severity: info
    annotations:
      summary: "Playbook not ready"
      description: "Playbook {{ $labels.name }} is not ready"

  - alert: ScheduleNotReady
    expr: kube_customresource_status_condition{resource="schedules", condition="Ready", status="False"} == 1
    for: 5m
    labels:
      severity: info
    annotations:
      summary: "Schedule not ready"
      description: "Schedule {{ $labels.name }} is not ready"
```

## Log Aggregation

### Structured Logging

**Log Format:**
```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "INFO",
  "controller": "Repository",
  "resource": "default/my-repo",
  "uid": "abc123-def456-ghi789",
  "runId": "run-12345",
  "event": "reconcile",
  "reason": "ReconcileSucceeded",
  "message": "Repository reconciliation completed successfully"
}
```

### Log Collection

**Fluentd Configuration:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: fluentd-config
data:
  fluent.conf: |
    <source>
      @type tail
      path /var/log/containers/ansible-playbook-operator*.log
      pos_file /var/log/fluentd-containers.log.pos
      tag kubernetes.*
      format json
    </source>

    <filter kubernetes.**>
      @type kubernetes_metadata
    </filter>

    <match kubernetes.**>
      @type elasticsearch
      host elasticsearch.logging.svc.cluster.local
      port 9200
      index_name ansible-operator
    </match>
```

**ELK Stack Integration:**
```yaml
# Elasticsearch index template
{
  "index_patterns": ["ansible-operator-*"],
  "mappings": {
    "properties": {
      "controller": {"type": "keyword"},
      "resource": {"type": "keyword"},
      "uid": {"type": "keyword"},
      "runId": {"type": "keyword"},
      "event": {"type": "keyword"},
      "reason": {"type": "keyword"}
    }
  }
}
```

### Log Analysis

**Common Queries:**
```bash
# Find reconciliation errors
kubectl logs -n ansible-operator-system deployment/ansible-playbook-operator | jq 'select(.reason == "ReconcileFailed")'

# Find authentication failures
kubectl logs -n ansible-operator-system deployment/ansible-playbook-operator | jq 'select(.reason == "ValidateFailed")'

# Find job execution issues
kubectl logs -n ansible-operator-system deployment/ansible-playbook-operator | jq 'select(.event == "job")'
```

## Health Checks

### Liveness Probe

**Configuration:**
```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
```

### Readiness Probe

**Configuration:**
```yaml
readinessProbe:
  httpGet:
    path: /readyz
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 5
  timeoutSeconds: 3
  failureThreshold: 3
```

### Health Endpoints

**Health Check Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z",
  "checks": {
    "kubernetes": "healthy",
    "reconciliation": "healthy",
    "workqueue": "healthy"
  }
}
```

## Performance Monitoring

### Resource Usage

**CPU and Memory:**
```bash
# Check operator resource usage
kubectl top pods -n ansible-operator-system

# Check resource limits
kubectl describe pod -n ansible-operator-system deployment/ansible-playbook-operator
```

**Resource Metrics:**
```yaml
# Prometheus resource metrics
- alert: HighCPUUsage
  expr: rate(container_cpu_usage_seconds_total{pod=~"ansible-playbook-operator-.*"}[5m]) > 0.8
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High CPU usage"
    description: "CPU usage is {{ $value }} cores"

- alert: HighMemoryUsage
  expr: container_memory_usage_bytes{pod=~"ansible-playbook-operator-.*"} / container_spec_memory_limit_bytes > 0.8
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High memory usage"
    description: "Memory usage is {{ $value }}% of limit"
```

### Performance Tuning

**Optimization Settings:**
```yaml
operator:
  resources:
    requests:
      cpu: 200m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 1Gi

  # Performance tuning
  env:
    - name: KOPF_MAX_WORKERS
      value: "8"
    - name: KOPF_REQUEST_TIMEOUT
      value: "60"
```

## Troubleshooting Monitoring

### Common Issues

**Metrics Not Available:**
```bash
# Check metrics endpoint
kubectl port-forward -n ansible-operator-system service/ansible-playbook-operator 8080:8080
curl http://localhost:8080/metrics

# Check ServiceMonitor
kubectl get servicemonitor -n ansible-operator-system

# Check Prometheus targets
kubectl port-forward -n monitoring service/prometheus 9090:9090
# Open http://localhost:9090/targets
```

**Alerts Not Firing:**
```bash
# Check alerting rules
kubectl get prometheusrules -n ansible-operator-system

# Check alertmanager configuration
kubectl get configmap -n monitoring alertmanager-config

# Test alert expression
kubectl port-forward -n monitoring service/prometheus 9090:9090
# Open http://localhost:9090/graph and test expression
```

**Logs Not Appearing:**
```bash
# Check log collection
kubectl logs -n logging deployment/fluentd

# Check log aggregation
kubectl logs -n logging deployment/elasticsearch

# Check log forwarding
kubectl logs -n ansible-operator-system deployment/ansible-playbook-operator
```

### Monitoring Best Practices

1. **Set up comprehensive monitoring** before production deployment
2. **Configure alerting** for critical issues
3. **Monitor resource usage** and set appropriate limits
4. **Use structured logging** for better analysis
5. **Regularly review** metrics and alerts
6. **Test alerting** to ensure it works correctly
7. **Document monitoring** setup and procedures

### Monitoring Checklist

**Pre-Deployment:**
- [ ] Enable metrics collection
- [ ] Configure ServiceMonitor
- [ ] Set up Grafana dashboards
- [ ] Configure alerting rules
- [ ] Test monitoring setup

**Post-Deployment:**
- [ ] Verify metrics collection
- [ ] Check dashboard functionality
- [ ] Test alerting rules
- [ ] Monitor resource usage
- [ ] Review log aggregation

**Ongoing Maintenance:**
- [ ] Update dashboards
- [ ] Refine alerting rules
- [ ] Monitor performance
- [ ] Review log patterns
- [ ] Optimize resource usage
