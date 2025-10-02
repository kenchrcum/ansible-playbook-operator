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
