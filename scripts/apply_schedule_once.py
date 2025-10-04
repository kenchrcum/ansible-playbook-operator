#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import suppress
from typing import Any

from kubernetes import client, config

from ansible_operator.builders.cronjob_builder import build_cronjob
from ansible_operator.constants import API_GROUP
from ansible_operator.utils.schedule import compute_computed_schedule


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply CronJobs for Schedules once (SSA)")
    parser.add_argument("--namespace", required=True)
    args = parser.parse_args()

    # Load kube config (in-cluster or local)
    with suppress(Exception):
        config.load_incluster_config()
    with suppress(Exception):
        config.load_kube_config()

    co_api = client.CustomObjectsApi()
    batch_api = client.BatchV1Api()

    schedules = co_api.list_namespaced_custom_object(
        group=API_GROUP,
        version="v1alpha1",
        namespace=args.namespace,
        plural="schedules",
    )

    for item in schedules.get("items", []):
        name = item["metadata"]["name"]
        uid = item["metadata"]["uid"]
        spec: dict[str, Any] = item.get("spec", {})
        schedule_expr = spec.get("schedule", "")
        computed, _ = compute_computed_schedule(schedule_expr, uid)

        # Patch computedSchedule into status
        with suppress(Exception):
            co_api.patch_namespaced_custom_object_status(
                group=API_GROUP,
                version="v1alpha1",
                namespace=args.namespace,
                plural="schedules",
                name=name,
                body={"status": {"computedSchedule": computed}},
            )

        # Fetch referenced Playbook
        playbook_ref = (spec.get("playbookRef") or {}).get("name")
        playbook_obj: dict[str, Any] = {"spec": {"runtime": {}}}
        if playbook_ref:
            with suppress(Exception):
                playbook_obj = co_api.get_namespaced_custom_object(
                    group=API_GROUP,
                    version="v1alpha1",
                    namespace=args.namespace,
                    plural="playbooks",
                    name=playbook_ref,
                )

        manifest = build_cronjob(
            schedule_name=name,
            namespace=args.namespace,
            computed_schedule=computed,
            playbook=playbook_obj,
            schedule_spec=spec,
            owner_uid=uid,
            owner_api_version=f"{API_GROUP}/v1alpha1",
            owner_kind="Schedule",
            owner_name=name,
        )

        field_manager = "ansible-operator-once"
        try:
            # Try patch first
            batch_api.patch_namespaced_cron_job(
                name=name,
                namespace=args.namespace,
                body=manifest,
                field_manager=field_manager,
                force=True,
            )
            print(f"Patched CronJob {args.namespace}/{name}")
        except client.exceptions.ApiException as e:
            if e.status == 404:
                batch_api.create_namespaced_cron_job(
                    namespace=args.namespace, body=manifest, field_manager=field_manager
                )
                print(f"Created CronJob {args.namespace}/{name}")
            else:
                raise

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
