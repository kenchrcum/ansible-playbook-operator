# Troubleshooting Guide

This guide helps you diagnose and resolve common issues with the Ansible Playbook Operator.

## Table of Contents

- [Common Issues](#common-issues)
- [Authentication Problems](#authentication-problems)
- [Repository Connectivity](#repository-connectivity)
- [Schedule Execution](#schedule-execution)
- [RBAC Permission Errors](#rbac-permission-errors)
- [Resource Quota Issues](#resource-quota-issues)
- [Debugging Techniques](#debugging-techniques)
- [Getting Help](#getting-help)

## Common Issues

### Operator Not Starting

**Symptoms:**
- Operator pod is in `CrashLoopBackOff` or `Error` state
- No logs from the operator
- CRDs not being processed

**Diagnosis:**
```bash
# Check operator pod status
kubectl get pods -n ansible-operator-system

# Check operator logs
kubectl logs -n ansible-operator-system deployment/ansible-playbook-operator

# Check operator events
kubectl get events -n ansible-operator-system --field-selector involvedObject.name=ansible-playbook-operator
```

**Common Causes:**
1. **Missing RBAC permissions**: Operator cannot access required resources
2. **Invalid configuration**: Check Helm values for syntax errors
3. **Resource constraints**: Insufficient CPU/memory limits
4. **Network issues**: Cannot reach Kubernetes API server

**Solutions:**
1. Verify RBAC configuration:
   ```bash
   kubectl auth can-i get pods --as=system:serviceaccount:ansible-operator-system:ansible-playbook-operator
   ```
2. Check resource limits in Helm values
3. Verify network connectivity to API server

### CRDs Not Being Processed

**Symptoms:**
- Repository/Playbook/Schedule resources remain in `Unknown` state
- No reconciliation events in operator logs
- Resources not updating status

**Diagnosis:**
```bash
# Check CRD status
kubectl get crd playbooks.ansible.cloud37.dev -o yaml

# Check resource status
kubectl get playbook my-playbook -o yaml

# Check operator logs for reconciliation
kubectl logs -n ansible-operator-system deployment/ansible-playbook-operator | grep "reconcile"
```

**Solutions:**
1. Ensure CRDs are properly installed
2. Check operator watch scope configuration
3. Verify resource is in the correct namespace

## Authentication Problems

### SSH Authentication Failures

**Symptoms:**
- Repository shows `AuthValid: False` condition
- Connectivity probe jobs failing
- Error: "Permission denied (publickey)"

**Diagnosis:**
```bash
# Check Repository status
kubectl get repository my-repo -o yaml

# Check probe job logs
kubectl logs job/my-repo-probe

# Verify SSH secret
kubectl get secret ssh-secret -o yaml
```

**Solutions:**
1. **Verify SSH key format**:
   ```bash
   # SSH key should be in OpenSSH format
   kubectl get secret ssh-secret -o jsonpath='{.data.ssh-privatekey}' | base64 -d | head -1
   # Should start with: -----BEGIN OPENSSH PRIVATE KEY-----
   ```

2. **Check known_hosts configuration**:
   ```bash
   # Verify known_hosts ConfigMap exists
   kubectl get configmap github-known-hosts

   # Check known_hosts content
   kubectl get configmap github-known-hosts -o jsonpath='{.data.known_hosts}'
   ```

3. **Test SSH connectivity manually**:
   ```bash
   # Create a test pod with SSH key
   kubectl run ssh-test --image=alpine/git --rm -it -- sh
   # Inside the pod:
   ssh -T git@github.com
   ```

### HTTPS Token Authentication Failures

**Symptoms:**
- Repository shows `AuthValid: False` condition
- Error: "Authentication failed"

**Diagnosis:**
```bash
# Check token secret
kubectl get secret github-token -o yaml

# Verify token format
kubectl get secret github-token -o jsonpath='{.data.token}' | base64 -d
```

**Solutions:**
1. **Verify token format**: Token should be a valid GitHub Personal Access Token
2. **Check token permissions**: Ensure token has `repo` scope
3. **Test token manually**:
   ```bash
   curl -H "Authorization: token YOUR_TOKEN" https://api.github.com/user
   ```

### Vault Password Issues

**Symptoms:**
- Ansible Vault files cannot be decrypted
- Error: "Vault password file not found"

**Diagnosis:**
```bash
# Check vault password secret
kubectl get secret vault-password -o yaml

# Verify secret key
kubectl get secret vault-password -o jsonpath='{.data.password}' | base64 -d
```

**Solutions:**
1. Ensure vault password secret exists and has correct key
2. Verify password matches the one used to encrypt vault files
3. Check Playbook configuration references the correct secret

## Repository Connectivity

### Git Clone Failures

**Symptoms:**
- Repository shows `CloneReady: False` condition
- Probe jobs failing with git errors

**Diagnosis:**
```bash
# Check probe job status
kubectl get jobs -l ansible.cloud37.dev/probe-type=connectivity

# Check probe job logs
kubectl logs job/my-repo-probe
```

**Common Errors:**
1. **"Repository not found"**: Invalid Git URL or insufficient permissions
2. **"Network unreachable"**: Network connectivity issues
3. **"SSL certificate problem"**: Certificate validation issues

**Solutions:**
1. **Verify Git URL**: Ensure URL is correct and accessible
2. **Check network policies**: Verify egress rules allow Git traffic
3. **Test connectivity manually**:
   ```bash
   kubectl run git-test --image=alpine/git --rm -it -- sh
   # Inside the pod:
   git ls-remote https://github.com/your-org/your-repo.git
   ```

### Branch/Revision Issues

**Symptoms:**
- Repository shows `CloneReady: False` condition
- Error: "Revision not found"

**Diagnosis:**
```bash
# Check Repository spec
kubectl get repository my-repo -o yaml

# Verify branch/revision exists
git ls-remote https://github.com/your-org/your-repo.git
```

**Solutions:**
1. **Verify branch exists**: Check if specified branch exists in repository
2. **Check revision format**: Ensure revision is a valid commit SHA
3. **Update branch/revision**: Use correct values in Repository spec

## Schedule Execution

### CronJob Not Creating Jobs

**Symptoms:**
- Schedule shows `Ready: False` condition
- No CronJob created
- Error: "CronJob not found"

**Diagnosis:**
```bash
# Check Schedule status
kubectl get schedule my-schedule -o yaml

# Check for CronJob
kubectl get cronjob schedule-my-schedule

# Check operator logs
kubectl logs -n ansible-operator-system deployment/ansible-playbook-operator | grep "schedule"
```

**Solutions:**
1. **Verify Playbook reference**: Ensure referenced Playbook exists and is ready
2. **Check schedule format**: Verify cron expression is valid
3. **Check RBAC permissions**: Ensure operator can create CronJobs

### Jobs Failing to Start

**Symptoms:**
- CronJob created but Jobs fail to start
- Pods in `Pending` state
- Error: "Insufficient resources"

**Diagnosis:**
```bash
# Check Job status
kubectl get jobs -l ansible.cloud37.dev/managed-by=ansible-operator

# Check Pod status
kubectl get pods -l ansible.cloud37.dev/managed-by=ansible-operator

# Check events
kubectl get events --field-selector involvedObject.kind=Pod
```

**Solutions:**
1. **Check resource quotas**: Ensure namespace has sufficient resources
2. **Verify node selectors**: Check if nodes match selector requirements
3. **Check tolerations**: Ensure nodes can tolerate required taints

### Jobs Running But Failing

**Symptoms:**
- Jobs start but fail with Ansible errors
- Pods in `Failed` state
- Ansible execution errors

**Diagnosis:**
```bash
# Check Job logs
kubectl logs job/my-job

# Check Pod logs
kubectl logs pod/my-job-xxxxx

# Check Job status
kubectl get job my-job -o yaml
```

**Common Ansible Errors:**
1. **"Host unreachable"**: Network connectivity to target hosts
2. **"Authentication failed"**: SSH key or password issues
3. **"Module not found"**: Missing Ansible modules or collections

**Solutions:**
1. **Check target host connectivity**: Ensure pods can reach target hosts
2. **Verify authentication**: Check SSH keys and credentials
3. **Install required modules**: Add missing Ansible modules to requirements.yml

## RBAC Permission Errors

### Operator Cannot Access Resources

**Symptoms:**
- Operator logs show "Forbidden" errors
- Resources not being reconciled
- Error: "User cannot access resource"

**Diagnosis:**
```bash
# Check operator permissions
kubectl auth can-i get pods --as=system:serviceaccount:ansible-operator-system:ansible-playbook-operator

# Check RBAC configuration
kubectl get role ansible-playbook-operator -o yaml
kubectl get rolebinding ansible-playbook-operator -o yaml
```

**Solutions:**
1. **Verify RBAC preset**: Ensure correct preset is configured
2. **Check ServiceAccount**: Verify operator uses correct ServiceAccount
3. **Update permissions**: Add missing permissions to Role/ClusterRole

### Executor Jobs Cannot Access Secrets

**Symptoms:**
- Executor pods fail to start
- Error: "Secret not found" or "Forbidden"

**Diagnosis:**
```bash
# Check executor ServiceAccount
kubectl get serviceaccount ansible-playbook-operator-executor

# Check executor permissions
kubectl auth can-i get secrets --as=system:serviceaccount:ansible-operator-system:ansible-playbook-operator-executor
```

**Solutions:**
1. **Verify executor RBAC**: Ensure executor ServiceAccount has required permissions
2. **Check secret references**: Verify secrets exist and are accessible
3. **Update executor permissions**: Add missing permissions to executor Role

## Resource Quota Issues

### Insufficient CPU/Memory

**Symptoms:**
- Pods in `Pending` state
- Error: "Insufficient cpu" or "Insufficient memory"

**Diagnosis:**
```bash
# Check namespace quotas
kubectl get resourcequota -n ansible-operator-system

# Check node resources
kubectl top nodes

# Check pod resource requests
kubectl get pods -o custom-columns=NAME:.metadata.name,CPU:.spec.containers[*].resources.requests.cpu,MEMORY:.spec.containers[*].resources.requests.memory
```

**Solutions:**
1. **Increase resource quotas**: Update namespace resource quotas
2. **Optimize resource requests**: Reduce resource requests in Helm values
3. **Scale cluster**: Add more nodes to the cluster

### Storage Issues

**Symptoms:**
- PVCs in `Pending` state
- Error: "No available persistent volumes"

**Diagnosis:**
```bash
# Check PVC status
kubectl get pvc -n ansible-operator-system

# Check available storage classes
kubectl get storageclass

# Check persistent volumes
kubectl get pv
```

**Solutions:**
1. **Configure storage class**: Ensure storage class is available
2. **Increase storage capacity**: Add more storage to the cluster
3. **Use different storage**: Switch to a different storage class

## Debugging Techniques

### Enable Verbose Logging

**Method 1: Update Helm Values**
```yaml
operator:
  env:
    - name: KOPF_DEBUG
      value: "true"
    - name: PYTHONUNBUFFERED
      value: "1"
```

**Method 2: Patch Deployment**
```bash
kubectl patch deployment ansible-playbook-operator -n ansible-operator-system -p '{"spec":{"template":{"spec":{"containers":[{"name":"operator","env":[{"name":"KOPF_DEBUG","value":"true"}]}]}}}}'
```

### Check Resource Status

**Repository Status:**
```bash
kubectl get repository my-repo -o yaml | grep -A 20 "status:"
```

**Playbook Status:**
```bash
kubectl get playbook my-playbook -o yaml | grep -A 20 "status:"
```

**Schedule Status:**
```bash
kubectl get schedule my-schedule -o yaml | grep -A 20 "status:"
```

### Monitor Events

**Operator Events:**
```bash
kubectl get events -n ansible-operator-system --field-selector involvedObject.name=ansible-playbook-operator --sort-by='.lastTimestamp'
```

**Resource Events:**
```bash
kubectl get events --field-selector involvedObject.kind=Repository --sort-by='.lastTimestamp'
kubectl get events --field-selector involvedObject.kind=Playbook --sort-by='.lastTimestamp'
kubectl get events --field-selector involvedObject.kind=Schedule --sort-by='.lastTimestamp'
```

### Check Metrics

**Prometheus Metrics:**
```bash
# If metrics are enabled
kubectl port-forward -n ansible-operator-system service/ansible-playbook-operator 8080:8080
curl http://localhost:8080/metrics
```

## Getting Help

### Collect Debug Information

**Create debug script:**
```bash
#!/bin/bash
echo "=== Ansible Playbook Operator Debug Information ==="
echo "Date: $(date)"
echo "Kubernetes Version: $(kubectl version --short)"
echo ""

echo "=== Operator Status ==="
kubectl get pods -n ansible-operator-system
echo ""

echo "=== Operator Logs (last 100 lines) ==="
kubectl logs -n ansible-operator-system deployment/ansible-playbook-operator --tail=100
echo ""

echo "=== CRD Status ==="
kubectl get crd | grep ansible.cloud37.dev
echo ""

echo "=== Resource Status ==="
kubectl get repositories,playbooks,schedules --all-namespaces
echo ""

echo "=== Recent Events ==="
kubectl get events --all-namespaces --sort-by='.lastTimestamp' | tail -20
```

### Community Support

1. **GitHub Issues**: Report bugs and feature requests
2. **Documentation**: Check this troubleshooting guide and README
3. **Examples**: Review examples in the `examples/` directory
4. **Logs**: Always include relevant logs when reporting issues

### Professional Support

For production environments requiring professional support:
- Review the security and performance guides
- Consider enterprise support options
- Implement monitoring and alerting as described in the monitoring guide
