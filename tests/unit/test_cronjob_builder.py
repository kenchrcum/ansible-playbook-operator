from typing import Any

from ansible_operator.builders.cronjob_builder import build_cronjob


def test_cronjob_builder_uses_computed_schedule_and_image():
    playbook = {"spec": {"runtime": {"image": "kenchrcum/ansible-runner:12"}}}
    schedule_spec = {
        "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}},
        "backoffLimit": 2,
        "successfulJobsHistoryLimit": 1,
        "failedJobsHistoryLimit": 1,
        "ttlSecondsAfterFinished": 3600,
        "concurrencyPolicy": "Forbid",
    }
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )
    assert cron["kind"] == "CronJob"
    assert cron["spec"]["schedule"] == "5 * * * *"
    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == "kenchrcum/ansible-runner:12"
    # Verify security context defaults
    security_context = container["securityContext"]
    assert security_context["runAsUser"] == 1000
    assert security_context["runAsGroup"] == 1000
    assert security_context["allowPrivilegeEscalation"] is False
    assert security_context["readOnlyRootFilesystem"] is True
    assert security_context["seccompProfile"]["type"] == "RuntimeDefault"
    assert security_context["capabilities"]["drop"] == ["ALL"]


def test_cronjob_builder_custom_security_context():
    playbook = {
        "spec": {
            "runtime": {
                "image": "kenchrcum/ansible-runner:12",
                "securityContext": {
                    "runAsUser": 1000,
                    "runAsGroup": 1000,
                    "allowPrivilegeEscalation": True,
                },
            }
        }
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )
    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    security_context = container["securityContext"]
    # Verify custom security context completely overrides defaults
    assert security_context["runAsUser"] == 1000
    assert security_context["runAsGroup"] == 1000
    assert security_context["allowPrivilegeEscalation"] is True
    # Fields not specified in custom context should not be present
    assert "readOnlyRootFilesystem" not in security_context
    assert "seccompProfile" not in security_context
    assert "capabilities" not in security_context


def test_cronjob_builder_vault_password_secret_ref():
    playbook = {
        "spec": {
            "playbookPath": "playbook.yml",
            "secrets": {"vaultPasswordSecretRef": {"name": "my-vault-secret"}},
        }
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    # Verify vault password volume is mounted
    volumes = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["volumes"]
    vault_volume = next((v for v in volumes if v["name"] == "vault-password"), None)
    assert vault_volume is not None
    assert vault_volume["secret"]["secretName"] == "my-vault-secret"

    # Verify vault password volume mount
    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    volume_mounts = container["volumeMounts"]
    vault_mount = next((vm for vm in volume_mounts if vm["name"] == "vault-password"), None)
    assert vault_mount is not None
    assert vault_mount["mountPath"] == "/vault-password"
    assert vault_mount["readOnly"] is True

    # Verify --vault-password-file flag is added to ansible-playbook command
    args = container["args"][0]
    assert "--vault-password-file /vault-password/password" in args


def test_cronjob_builder_no_vault_password_secret_ref():
    playbook = {
        "spec": {"playbookPath": "playbook.yml", "secrets": {}}  # No vaultPasswordSecretRef
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    # Verify no vault password volume
    volumes = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["volumes"]
    vault_volume = next((v for v in volumes if v["name"] == "vault-password"), None)
    assert vault_volume is None

    # Verify no vault password volume mount
    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    volume_mounts = container.get("volumeMounts", [])
    vault_mount = next((vm for vm in volume_mounts if vm["name"] == "vault-password"), None)
    assert vault_mount is None

    # Verify no --vault-password-file flag in ansible-playbook command
    args = container["args"][0]
    assert "--vault-password-file" not in args


def test_cronjob_builder_ansible_cfg_not_set():
    """Test that ANSIBLE_CONFIG is not set when spec.ansibleCfgPath is not provided."""
    playbook = {"spec": {"playbookPath": "playbook.yml"}}
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    # Verify ANSIBLE_CONFIG is not set in the script
    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]
    assert "export ANSIBLE_CONFIG" not in args


def test_cronjob_builder_ansible_cfg_absolute_path():
    """Test ANSIBLE_CONFIG with absolute path."""
    playbook = {
        "spec": {"playbookPath": "playbook.yml", "ansibleCfgPath": "/custom/path/ansible.cfg"}
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    # Verify ANSIBLE_CONFIG is set to the absolute path
    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]
    assert 'export ANSIBLE_CONFIG="/custom/path/ansible.cfg"' in args


def test_cronjob_builder_ansible_cfg_relative_path():
    """Test ANSIBLE_CONFIG with relative path resolves under /workspace/repo."""
    playbook = {"spec": {"playbookPath": "playbook.yml", "ansibleCfgPath": "my-ansible.cfg"}}
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    # Verify ANSIBLE_CONFIG is set to the resolved relative path
    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]
    assert 'export ANSIBLE_CONFIG="/workspace/repo/my-ansible.cfg"' in args


def test_cronjob_builder_cache_pvc_strategy():
    """Test PVC-backed cache volume is mounted when Repository.spec.cache.strategy is 'pvc'."""
    playbook = {"spec": {"playbookPath": "playbook.yml"}}
    repository = {"spec": {"cache": {"strategy": "pvc", "pvcName": "my-cache-pvc"}}}
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        repository=repository,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    # Verify cache volume is added
    volumes = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["volumes"]
    cache_volume = next((v for v in volumes if v["name"] == "ansible-cache"), None)
    assert cache_volume is not None
    assert cache_volume["persistentVolumeClaim"]["claimName"] == "my-cache-pvc"

    # Verify cache volume mount
    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    volume_mounts = container["volumeMounts"]
    cache_mount = next((vm for vm in volume_mounts if vm["name"] == "ansible-cache"), None)
    assert cache_mount is not None
    assert cache_mount["mountPath"] == "/home/ansible/.ansible"


def test_cronjob_builder_cache_none_strategy():
    """Test no cache volume is mounted when Repository.spec.cache.strategy is 'none'."""
    playbook = {"spec": {"playbookPath": "playbook.yml"}}
    repository = {"spec": {"cache": {"strategy": "none"}}}
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        repository=repository,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    # Verify no cache volume
    volumes = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["volumes"]
    cache_volume = next((v for v in volumes if v["name"] == "ansible-cache"), None)
    assert cache_volume is None

    # Verify no cache volume mount
    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    volume_mounts = container.get("volumeMounts", [])
    cache_mount = next((vm for vm in volume_mounts if vm["name"] == "ansible-cache"), None)
    assert cache_mount is None


def test_cronjob_builder_cache_pvc_strategy_empty_pvc_name():
    """Test no cache volume is mounted when PVC strategy is used but pvcName is empty."""
    playbook = {"spec": {"playbookPath": "playbook.yml"}}
    repository = {"spec": {"cache": {"strategy": "pvc", "pvcName": ""}}}
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        repository=repository,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    # Verify no cache volume (because pvcName is empty)
    volumes = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["volumes"]
    cache_volume = next((v for v in volumes if v["name"] == "ansible-cache"), None)
    assert cache_volume is None

    # Verify no cache volume mount
    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    volume_mounts = container.get("volumeMounts", [])
    cache_mount = next((vm for vm in volume_mounts if vm["name"] == "ansible-cache"), None)
    assert cache_mount is None


def test_cronjob_builder_no_repository_cache():
    """Test no cache volume is mounted when no repository is provided."""
    playbook = {"spec": {"playbookPath": "playbook.yml"}}
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    # Verify no cache volume
    volumes = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["volumes"]
    cache_volume = next((v for v in volumes if v["name"] == "ansible-cache"), None)
    assert cache_volume is None

    # Verify no cache volume mount
    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    volume_mounts = container.get("volumeMounts", [])
    cache_mount = next((vm for vm in volume_mounts if vm["name"] == "ansible-cache"), None)
    assert cache_mount is None


def test_cronjob_builder_execution_tags():
    """Test execution tags are added to ansible-playbook command."""
    playbook = {
        "spec": {
            "playbookPath": "playbook.yml",
            "execution": {"tags": ["deploy", "config"]},
        }
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]
    assert "--tags deploy,config" in args


def test_cronjob_builder_execution_skip_tags():
    """Test execution skip tags are added to ansible-playbook command."""
    playbook = {
        "spec": {
            "playbookPath": "playbook.yml",
            "execution": {"skipTags": ["test", "debug"]},
        }
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]
    assert "--skip-tags test,debug" in args


def test_cronjob_builder_execution_check_mode():
    """Test check mode flag is added to ansible-playbook command."""
    playbook = {
        "spec": {
            "playbookPath": "playbook.yml",
            "execution": {"checkMode": True},
        }
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]
    assert "--check" in args


def test_cronjob_builder_execution_diff():
    """Test diff flag is added to ansible-playbook command."""
    playbook = {
        "spec": {
            "playbookPath": "playbook.yml",
            "execution": {"diff": True},
        }
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]
    assert "--diff" in args


def test_cronjob_builder_execution_verbosity():
    """Test verbosity flags are added to ansible-playbook command."""
    playbook = {
        "spec": {
            "playbookPath": "playbook.yml",
            "execution": {"verbosity": 3},
        }
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]
    assert "-vvv" in args


def test_cronjob_builder_execution_verbosity_max():
    """Test verbosity is capped at 4."""
    playbook = {
        "spec": {
            "playbookPath": "playbook.yml",
            "execution": {"verbosity": 10},
        }
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]
    assert "-vvvv" in args


def test_cronjob_builder_execution_limit():
    """Test limit flag is added to ansible-playbook command."""
    playbook = {
        "spec": {
            "playbookPath": "playbook.yml",
            "execution": {"limit": "web_servers"},
        }
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]
    assert "--limit web_servers" in args


def test_cronjob_builder_execution_connection_timeout():
    """Test connection timeout flag is added to ansible-playbook command."""
    playbook = {
        "spec": {
            "playbookPath": "playbook.yml",
            "execution": {"connectionTimeout": 30},
        }
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]
    assert "--timeout 30" in args


def test_cronjob_builder_execution_forks():
    """Test forks flag is added to ansible-playbook command."""
    playbook = {
        "spec": {
            "playbookPath": "playbook.yml",
            "execution": {"forks": 10},
        }
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]
    assert "--forks 10" in args


def test_cronjob_builder_execution_strategy():
    """Test strategy flag is added to ansible-playbook command."""
    playbook = {
        "spec": {
            "playbookPath": "playbook.yml",
            "execution": {"strategy": "free"},
        }
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]
    assert "--strategy free" in args


def test_cronjob_builder_execution_strategy_default():
    """Test strategy flag is not added when using default linear strategy."""
    playbook = {
        "spec": {
            "playbookPath": "playbook.yml",
            "execution": {"strategy": "linear"},
        }
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]
    assert "--strategy" not in args


def test_cronjob_builder_execution_flush_cache():
    """Test flush cache flag is added to ansible-playbook command."""
    playbook = {
        "spec": {
            "playbookPath": "playbook.yml",
            "execution": {"flushCache": True},
        }
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]
    assert "--flush-cache" in args


def test_cronjob_builder_execution_force_handlers():
    """Test force handlers flag is added to ansible-playbook command."""
    playbook = {
        "spec": {
            "playbookPath": "playbook.yml",
            "execution": {"forceHandlers": True},
        }
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]
    assert "--force-handlers" in args


def test_cronjob_builder_execution_start_at_task():
    """Test start at task flag is added to ansible-playbook command."""
    playbook = {
        "spec": {
            "playbookPath": "playbook.yml",
            "execution": {"startAtTask": "Install packages"},
        }
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]
    assert "--start-at-task Install packages" in args


def test_cronjob_builder_execution_step():
    """Test step flag is added to ansible-playbook command."""
    playbook = {
        "spec": {
            "playbookPath": "playbook.yml",
            "execution": {"step": True},
        }
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]
    assert "--step" in args


def test_cronjob_builder_execution_multiple_options():
    """Test multiple execution options are combined correctly."""
    playbook = {
        "spec": {
            "playbookPath": "playbook.yml",
            "execution": {
                "tags": ["deploy"],
                "checkMode": True,
                "verbosity": 2,
                "limit": "web_servers",
                "connectionTimeout": 60,
                "forks": 5,
                "strategy": "free",
                "flushCache": True,
                "forceHandlers": True,
                "step": True,
            },
        }
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]

    # Verify all flags are present
    assert "--tags deploy" in args
    assert "--check" in args
    assert "-vv" in args
    assert "--limit web_servers" in args
    assert "--timeout 60" in args
    assert "--forks 5" in args
    assert "--strategy free" in args
    assert "--flush-cache" in args
    assert "--force-handlers" in args
    assert "--step" in args


def test_cronjob_builder_execution_empty():
    """Test no execution flags are added when execution is empty."""
    playbook = {
        "spec": {
            "playbookPath": "playbook.yml",
            "execution": {},
        }
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]

    # Verify no execution flags are present
    assert "--tags" not in args
    assert "--skip-tags" not in args
    assert "--check" not in args
    assert "--diff" not in args
    assert "-v" not in args
    assert "--limit" not in args
    assert "--timeout" not in args
    assert "--forks" not in args
    assert "--strategy" not in args
    assert "--flush-cache" not in args
    assert "--force-handlers" not in args
    assert "--start-at-task" not in args
    assert "--step" not in args


def test_cronjob_builder_execution_defaults():
    """Test execution defaults are applied correctly."""
    playbook = {
        "spec": {
            "playbookPath": "playbook.yml",
            "execution": {
                "checkMode": False,
                "diff": False,
                "verbosity": 0,
                "strategy": "linear",
                "flushCache": False,
                "forceHandlers": False,
                "step": False,
            },
        }
    }
    schedule_spec: dict[str, Any] = {}
    cron = build_cronjob(
        schedule_name="test-sched",
        namespace="default",
        computed_schedule="5 * * * *",
        playbook=playbook,
        schedule_spec=schedule_spec,
        owner_uid="uid-1234",
    )

    container = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    args = container["args"][0]

    # Verify default flags are not present
    assert "--check" not in args
    assert "--diff" not in args
    assert "-v" not in args
    assert "--strategy" not in args
    assert "--flush-cache" not in args
    assert "--force-handlers" not in args
    assert "--step" not in args
