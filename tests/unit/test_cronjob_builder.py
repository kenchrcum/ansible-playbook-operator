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
    assert security_context["runAsUser"] == 1001
    assert security_context["runAsGroup"] == 1001
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
