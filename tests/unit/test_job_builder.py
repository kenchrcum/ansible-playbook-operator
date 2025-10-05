from ansible_operator.builders.job_builder import build_connectivity_probe_job


def test_connectivity_probe_job_basic_structure():
    """Test that connectivity probe job has correct basic structure."""
    repo_spec = {"url": "https://github.com/example/repo.git"}
    job = build_connectivity_probe_job(
        repository_name="test-repo",
        namespace="default",
        repository_spec=repo_spec,
        owner_uid="uid-1234",
    )

    assert job["kind"] == "Job"
    assert job["metadata"]["name"] == "test-repo-probe"
    assert job["metadata"]["namespace"] == "default"
    assert job["metadata"]["labels"]["ansible.cloud37.dev/probe-type"] == "connectivity"

    # Check owner references
    owner_refs = job["metadata"]["ownerReferences"]
    assert len(owner_refs) == 1
    assert owner_refs[0]["kind"] == "Repository"
    assert owner_refs[0]["uid"] == "uid-1234"

    # Check job spec
    spec = job["spec"]
    assert spec["backoffLimit"] == 0
    assert spec["ttlSecondsAfterFinished"] == 300

    # Check pod template
    template = spec["template"]["spec"]
    assert template["restartPolicy"] == "Never"
    assert template["securityContext"]["runAsNonRoot"] is True

    # Check container
    container = template["containers"][0]
    assert container["name"] == "connectivity-probe"
    assert "git ls-remote" in container["args"][0]


def test_connectivity_probe_job_security_context():
    """Test that connectivity probe job has correct security context."""
    repo_spec = {"url": "https://github.com/example/repo.git"}
    job = build_connectivity_probe_job(
        repository_name="test-repo",
        namespace="default",
        repository_spec=repo_spec,
        owner_uid="uid-1234",
    )

    container = job["spec"]["template"]["spec"]["containers"][0]
    security_context = container["securityContext"]

    assert security_context["runAsUser"] == 1000
    assert security_context["runAsGroup"] == 1000
    assert security_context["allowPrivilegeEscalation"] is False
    assert security_context["readOnlyRootFilesystem"] is True
    assert security_context["seccompProfile"]["type"] == "RuntimeDefault"
    assert security_context["capabilities"]["drop"] == ["ALL"]


def test_connectivity_probe_job_ssh_auth():
    """Test SSH authentication mounting."""
    repo_spec = {
        "url": "git@github.com:example/repo.git",
        "auth": {"method": "ssh", "secretRef": {"name": "ssh-secret"}},
    }
    job = build_connectivity_probe_job(
        repository_name="test-repo",
        namespace="default",
        repository_spec=repo_spec,
        owner_uid="uid-1234",
    )

    volumes = job["spec"]["template"]["spec"]["volumes"]
    volume_mounts = job["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]

    # Check SSH auth volume
    ssh_volume = next((v for v in volumes if v["name"] == "ssh-auth"), None)
    assert ssh_volume is not None
    assert ssh_volume["secret"]["secretName"] == "ssh-secret"

    # Check SSH auth volume mount
    ssh_mount = next((vm for vm in volume_mounts if vm["name"] == "ssh-auth"), None)
    assert ssh_mount is not None
    assert ssh_mount["mountPath"] == "/ssh-auth"
    assert ssh_mount["readOnly"] is True

    # Check SSH setup in script - should fail since strict checking is enabled by default
    # but no known_hosts provided
    args = job["spec"]["template"]["spec"]["containers"][0]["args"][0]
    assert "install -m 0600 /ssh-auth/ssh-privatekey $HOME/.ssh/id_rsa" in args
    assert "known_hosts not provided while strictHostKeyChecking=true" in args
    assert "exit 1" in args


def test_connectivity_probe_job_token_auth():
    """Test token authentication."""
    repo_spec = {
        "url": "https://github.com/example/repo.git",
        "auth": {"method": "token", "secretRef": {"name": "token-secret"}},
    }
    job = build_connectivity_probe_job(
        repository_name="test-repo",
        namespace="default",
        repository_spec=repo_spec,
        owner_uid="uid-1234",
    )

    container = job["spec"]["template"]["spec"]["containers"][0]
    env_vars = container["env"]

    # Check token env var
    token_env = next((env for env in env_vars if env["name"] == "REPO_TOKEN"), None)
    assert token_env is not None
    assert token_env["valueFrom"]["secretKeyRef"]["name"] == "token-secret"
    assert token_env["valueFrom"]["secretKeyRef"]["key"] == "token"

    # Check token setup in script
    args = container["args"][0]
    assert "printf 'machine %s login oauth2 password %s" in args


def test_connectivity_probe_job_known_hosts_strict():
    """Test known_hosts mounting when strict host key checking is enabled."""
    repo_spec = {
        "url": "git@github.com:example/repo.git",
        "auth": {"method": "ssh", "secretRef": {"name": "ssh-secret"}},
        "ssh": {
            "strictHostKeyChecking": True,
            "knownHostsConfigMapRef": {"name": "known-hosts-cm"},
        },
    }
    job = build_connectivity_probe_job(
        repository_name="test-repo",
        namespace="default",
        repository_spec=repo_spec,
        owner_uid="uid-1234",
    )

    volumes = job["spec"]["template"]["spec"]["volumes"]
    volume_mounts = job["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]

    # Check known_hosts volume
    known_hosts_volume = next((v for v in volumes if v["name"] == "ssh-known"), None)
    assert known_hosts_volume is not None
    assert known_hosts_volume["configMap"]["name"] == "known-hosts-cm"

    # Check known_hosts volume mount
    known_hosts_mount = next((vm for vm in volume_mounts if vm["name"] == "ssh-known"), None)
    assert known_hosts_mount is not None
    assert known_hosts_mount["mountPath"] == "/ssh-knownhosts"
    assert known_hosts_mount["readOnly"] is True

    # Check SSH command uses known_hosts
    args = job["spec"]["template"]["spec"]["containers"][0]["args"][0]
    assert "UserKnownHostsFile=/ssh-knownhosts/known_hosts" in args
    assert 'StrictHostKeyChecking=yes"' in args


def test_connectivity_probe_job_known_hosts_strict_missing_cm():
    """Test failure when strict host key checking is enabled but no known_hosts ConfigMap."""
    repo_spec = {
        "url": "git@github.com:example/repo.git",
        "auth": {"method": "ssh", "secretRef": {"name": "ssh-secret"}},
        "ssh": {
            "strictHostKeyChecking": True
            # No knownHostsConfigMapRef
        },
    }
    job = build_connectivity_probe_job(
        repository_name="test-repo",
        namespace="default",
        repository_spec=repo_spec,
        owner_uid="uid-1234",
    )

    # Check that script fails when strict checking but no known hosts
    args = job["spec"]["template"]["spec"]["containers"][0]["args"][0]
    assert "known_hosts not provided while strictHostKeyChecking=true" in args
    assert "exit 1" in args


def test_connectivity_probe_job_known_hosts_non_strict():
    """Test no known_hosts mounting when strict host key checking is disabled."""
    repo_spec = {
        "url": "git@github.com:example/repo.git",
        "auth": {"method": "ssh", "secretRef": {"name": "ssh-secret"}},
        "ssh": {
            "strictHostKeyChecking": False,
            "knownHostsConfigMapRef": {"name": "known-hosts-cm"},
        },
    }
    job = build_connectivity_probe_job(
        repository_name="test-repo",
        namespace="default",
        repository_spec=repo_spec,
        owner_uid="uid-1234",
    )

    volumes = job["spec"]["template"]["spec"]["volumes"]
    volume_mounts = job["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]

    # Check no known_hosts volume (not strict)
    known_hosts_volume = next((v for v in volumes if v["name"] == "ssh-known"), None)
    assert known_hosts_volume is None

    # Check no known_hosts volume mount
    known_hosts_mount = next((vm for vm in volume_mounts if vm["name"] == "ssh-known"), None)
    assert known_hosts_mount is None

    # Check SSH command doesn't use known_hosts
    args = job["spec"]["template"]["spec"]["containers"][0]["args"][0]
    assert "UserKnownHostsFile" not in args
    assert 'StrictHostKeyChecking=no"' in args


def test_connectivity_probe_job_git_ls_remote_command():
    """Test that git ls-remote command is properly constructed."""
    repo_spec = {"url": "https://github.com/example/repo.git"}
    job = build_connectivity_probe_job(
        repository_name="test-repo",
        namespace="default",
        repository_spec=repo_spec,
        owner_uid="uid-1234",
    )

    args = job["spec"]["template"]["spec"]["containers"][0]["args"][0]
    assert 'git ls-remote "https://github.com/example/repo.git" HEAD' in args
    assert "Testing connectivity to https://github.com/example/repo.git" in args
    assert "Connectivity test successful" in args


def test_connectivity_probe_job_workspace_volumes():
    """Test that workspace and home volumes are always present."""
    repo_spec = {"url": "https://github.com/example/repo.git"}
    job = build_connectivity_probe_job(
        repository_name="test-repo",
        namespace="default",
        repository_spec=repo_spec,
        owner_uid="uid-1234",
    )

    volumes = job["spec"]["template"]["spec"]["volumes"]
    volume_mounts = job["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]

    # Check workspace volume
    workspace_volume = next((v for v in volumes if v["name"] == "workspace"), None)
    assert workspace_volume is not None
    assert workspace_volume["emptyDir"] == {}

    workspace_mount = next((vm for vm in volume_mounts if vm["name"] == "workspace"), None)
    assert workspace_mount is not None
    assert workspace_mount["mountPath"] == "/workspace"

    # Check home volume
    home_volume = next((v for v in volumes if v["name"] == "home"), None)
    assert home_volume is not None
    assert home_volume["emptyDir"] == {}

    home_mount = next((vm for vm in volume_mounts if vm["name"] == "home"), None)
    assert home_mount is not None
    assert home_mount["mountPath"] == "/home/ansible"
