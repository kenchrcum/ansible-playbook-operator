"""Manual run service for Playbook and Schedule ad-hoc executions."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from kubernetes import client

from ..builders.job_builder import build_manual_run_job
from ..constants import (
    ANNOTATION_RUN_NOW,
    API_GROUP,
    EXECUTOR_SERVICE_ACCOUNT_ENV,
)


class ManualRunService:
    """Service for handling manual Playbook and Schedule runs."""

    def __init__(self) -> None:
        pass

    def detect_manual_run_request(self, annotations: dict[str, Any]) -> str | None:
        """Detect if a manual run is requested via annotation.

        Returns:
            The run ID if a manual run is requested, None otherwise.
        """
        return annotations.get(ANNOTATION_RUN_NOW)

    def create_manual_run_job(
        self,
        playbook_name: str,
        namespace: str,
        playbook_spec: dict[str, Any],
        repository_obj: dict[str, Any] | None,
        run_id: str,
        owner_uid: str,
        known_hosts_available: bool = False,
    ) -> str:
        """Create a manual run Job for the Playbook.

        Returns:
            The name of the created Job.
        """
        # Build Job manifest
        job_manifest = build_manual_run_job(
            playbook_name=playbook_name,
            namespace=namespace,
            playbook_spec=playbook_spec,
            repository=repository_obj,
            known_hosts_available=known_hosts_available,
            run_id=run_id,
            owner_uid=owner_uid,
            owner_api_version=f"{API_GROUP}/v1alpha1",
            owner_kind="Playbook",
            owner_name=playbook_name,
            executor_service_account=os.getenv(EXECUTOR_SERVICE_ACCOUNT_ENV),
        )

        # Create the Job
        batch_api = client.BatchV1Api()
        job_name: str = job_manifest["metadata"]["name"]

        batch_api.create_namespaced_job(
            namespace=namespace,
            body=job_manifest,
            field_manager="ansible-operator",
        )

        return job_name

    def update_playbook_manual_run_status(
        self,
        playbook_name: str,
        namespace: str,
        run_id: str,
        job_name: str,
        status: str,
        reason: str = "",
        message: str = "",
        completion_time: str | None = None,
    ) -> None:
        """Update Playbook status with manual run information."""
        api = client.CustomObjectsApi()

        # Prepare status update
        patch_body: dict[str, Any] = {
            "status": {
                "lastManualRun": {
                    "runId": run_id,
                    "jobRef": f"{namespace}/{job_name}",
                    "startTime": datetime.now(UTC).isoformat(),
                    "status": status,
                    "reason": reason,
                    "message": message,
                }
            }
        }

        if completion_time:
            patch_body["status"]["lastManualRun"]["completionTime"] = completion_time

        # Apply the status update
        try:
            api.patch_namespaced_custom_object_status(
                group=API_GROUP,
                version="v1alpha1",
                namespace=namespace,
                plural="playbooks",
                name=playbook_name,
                body=patch_body,
                field_manager="ansible-operator",
            )
        except Exception:
            # Status update failures are non-critical
            pass

    def clear_manual_run_annotation(
        self,
        playbook_name: str,
        namespace: str,
    ) -> None:
        """Clear the manual run annotation after processing."""
        api = client.CustomObjectsApi()

        # Remove the annotation
        patch_body = {
            "metadata": {
                "annotations": {
                    ANNOTATION_RUN_NOW: None,
                }
            }
        }

        try:
            api.patch_namespaced_custom_object(
                group=API_GROUP,
                version="v1alpha1",
                namespace=namespace,
                plural="playbooks",
                name=playbook_name,
                body=patch_body,
                field_manager="ansible-operator",
            )
        except Exception:
            # Annotation cleanup failures are non-critical
            pass

    def create_schedule_manual_run_job(
        self,
        schedule_name: str,
        namespace: str,
        playbook_obj: dict[str, Any],
        repository_obj: dict[str, Any] | None,
        run_id: str,
        owner_uid: str,
        known_hosts_available: bool = False,
    ) -> str:
        """Create a manual run Job for a Schedule's referenced Playbook.

        Returns:
            The name of the created Job.
        """
        playbook_spec = playbook_obj.get("spec", {})

        # Build Job manifest with Schedule as owner
        job_manifest = build_manual_run_job(
            playbook_name=schedule_name,
            namespace=namespace,
            playbook_spec=playbook_spec,
            repository=repository_obj,
            known_hosts_available=known_hosts_available,
            run_id=run_id,
            owner_uid=owner_uid,
            owner_api_version=f"{API_GROUP}/v1alpha1",
            owner_kind="Schedule",
            owner_name=schedule_name,
            executor_service_account=os.getenv(EXECUTOR_SERVICE_ACCOUNT_ENV),
        )

        # Create the Job
        batch_api = client.BatchV1Api()
        job_name: str = job_manifest["metadata"]["name"]

        batch_api.create_namespaced_job(
            namespace=namespace,
            body=job_manifest,
            field_manager="ansible-operator",
        )

        return job_name

    def update_schedule_manual_run_status(
        self,
        schedule_name: str,
        namespace: str,
        run_id: str,
        job_name: str,
        status: str,
        reason: str = "",
        message: str = "",
        completion_time: str | None = None,
    ) -> None:
        """Update Schedule status with manual run information."""
        api = client.CustomObjectsApi()

        # Prepare status update
        patch_body: dict[str, Any] = {
            "status": {
                "lastManualRun": {
                    "runId": run_id,
                    "jobRef": f"{namespace}/{job_name}",
                    "startTime": datetime.now(UTC).isoformat(),
                    "status": status,
                    "reason": reason,
                    "message": message,
                }
            }
        }

        if completion_time:
            patch_body["status"]["lastManualRun"]["completionTime"] = completion_time

        # Apply the status update
        try:
            api.patch_namespaced_custom_object_status(
                group=API_GROUP,
                version="v1alpha1",
                namespace=namespace,
                plural="schedules",
                name=schedule_name,
                body=patch_body,
                field_manager="ansible-operator",
            )
        except Exception:
            # Status update failures are non-critical
            pass

    def clear_schedule_manual_run_annotation(
        self,
        schedule_name: str,
        namespace: str,
    ) -> None:
        """Clear the manual run annotation from Schedule after processing."""
        api = client.CustomObjectsApi()

        # Remove the annotation
        patch_body = {
            "metadata": {
                "annotations": {
                    ANNOTATION_RUN_NOW: None,
                }
            }
        }

        try:
            api.patch_namespaced_custom_object(
                group=API_GROUP,
                version="v1alpha1",
                namespace=namespace,
                plural="schedules",
                name=schedule_name,
                body=patch_body,
                field_manager="ansible-operator",
            )
        except Exception:
            # Annotation cleanup failures are non-critical
            pass


# Global instance
manual_run_service = ManualRunService()
