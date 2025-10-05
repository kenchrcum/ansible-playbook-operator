"""Unit tests for Schedule CronJob adoption logic."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from ansible_operator.constants import (
    ANNOTATION_OWNER_UID,
    LABEL_MANAGED_BY,
    LABEL_OWNER_KIND,
    LABEL_OWNER_NAME,
    LABEL_OWNER_UID,
)
from ansible_operator.main import _can_safely_adopt_cronjob


class TestScheduleAdoption:
    """Test cases for safe CronJob adoption logic."""

    def test_can_adopt_matching_owner_uid_label(self) -> None:
        """Test adoption when owner UID label matches."""
        existing_cj = Mock()
        existing_cj.metadata = Mock()
        existing_cj.metadata.labels = {
            LABEL_MANAGED_BY: "ansible-operator",
            LABEL_OWNER_UID: "test-uid-123",
        }
        existing_cj.metadata.annotations = {}
        existing_cj.metadata.owner_references = []

        can_adopt, reason = _can_safely_adopt_cronjob(
            existing_cj, "test-uid-123", "test-schedule", "test-namespace"
        )

        assert can_adopt is True
        assert reason == "matching owner UID"

    def test_can_adopt_matching_owner_uid_annotation(self) -> None:
        """Test adoption when owner UID annotation matches."""
        existing_cj = Mock()
        existing_cj.metadata = Mock()
        existing_cj.metadata.labels = {
            LABEL_MANAGED_BY: "ansible-operator",
        }
        existing_cj.metadata.annotations = {
            ANNOTATION_OWNER_UID: "test-uid-123",
        }
        existing_cj.metadata.owner_references = []

        can_adopt, reason = _can_safely_adopt_cronjob(
            existing_cj, "test-uid-123", "test-schedule", "test-namespace"
        )

        assert can_adopt is True
        assert reason == "matching owner UID"

    def test_cannot_adopt_different_owner_uid(self) -> None:
        """Test rejection when owner UID doesn't match."""
        existing_cj = Mock()
        existing_cj.metadata = Mock()
        existing_cj.metadata.labels = {
            LABEL_MANAGED_BY: "ansible-operator",
            LABEL_OWNER_UID: "different-uid-456",
        }
        existing_cj.metadata.annotations = {}
        existing_cj.metadata.owner_references = []

        can_adopt, reason = _can_safely_adopt_cronjob(
            existing_cj, "test-uid-123", "test-schedule", "test-namespace"
        )

        assert can_adopt is False
        assert "different owner UID" in reason
        assert "different-uid-456" in reason
        assert "test-uid-123" in reason

    def test_can_adopt_matching_owner_reference(self) -> None:
        """Test adoption when owner reference matches."""
        existing_cj = Mock()
        existing_cj.metadata = Mock()
        existing_cj.metadata.labels = {}  # Not managed by ansible-operator
        existing_cj.metadata.annotations = {}
        owner_ref = Mock()
        owner_ref.kind = "Schedule"
        owner_ref.name = "test-schedule"
        owner_ref.uid = "test-uid-123"
        existing_cj.metadata.owner_references = [owner_ref]

        can_adopt, reason = _can_safely_adopt_cronjob(
            existing_cj, "test-uid-123", "test-schedule", "test-namespace"
        )

        assert can_adopt is True
        assert reason == "matching owner reference"

    def test_can_adopt_matching_uid_annotation_only(self) -> None:
        """Test adoption when only UID annotation matches (manual adoption)."""
        existing_cj = Mock()
        existing_cj.metadata = Mock()
        existing_cj.metadata.labels = {}
        existing_cj.metadata.annotations = {
            ANNOTATION_OWNER_UID: "test-uid-123",
        }
        existing_cj.metadata.owner_references = []

        can_adopt, reason = _can_safely_adopt_cronjob(
            existing_cj, "test-uid-123", "test-schedule", "test-namespace"
        )

        assert can_adopt is True
        assert reason == "matching UID annotation"

    def test_cannot_adopt_no_matching_indicators(self) -> None:
        """Test rejection when no ownership indicators match."""
        existing_cj = Mock()
        existing_cj.metadata = Mock()
        existing_cj.metadata.labels = {}
        existing_cj.metadata.annotations = {}
        existing_cj.metadata.owner_references = []

        can_adopt, reason = _can_safely_adopt_cronjob(
            existing_cj, "test-uid-123", "test-schedule", "test-namespace"
        )

        assert can_adopt is False
        assert "no matching ownership indicators" in reason

    def test_cannot_adopt_different_owner_reference(self) -> None:
        """Test rejection when owner reference doesn't match."""
        existing_cj = Mock()
        existing_cj.metadata = Mock()
        existing_cj.metadata.labels = {}
        existing_cj.metadata.annotations = {}
        existing_cj.metadata.owner_references = [
            Mock(
                kind="Schedule",
                name="different-schedule",
                uid="different-uid-456",
            )
        ]

        can_adopt, reason = _can_safely_adopt_cronjob(
            existing_cj, "test-uid-123", "test-schedule", "test-namespace"
        )

        assert can_adopt is False
        assert "no matching ownership indicators" in reason

    def test_cannot_adopt_not_managed_by_operator(self) -> None:
        """Test rejection when CronJob is not managed by ansible-operator."""
        existing_cj = Mock()
        existing_cj.metadata = Mock()
        existing_cj.metadata.labels = {
            LABEL_MANAGED_BY: "other-operator",
        }
        existing_cj.metadata.annotations = {}
        existing_cj.metadata.owner_references = []

        can_adopt, reason = _can_safely_adopt_cronjob(
            existing_cj, "test-uid-123", "test-schedule", "test-namespace"
        )

        assert can_adopt is False
        assert "no matching ownership indicators" in reason

    def test_handles_none_labels_and_annotations(self) -> None:
        """Test handling of None labels and annotations."""
        existing_cj = Mock()
        existing_cj.metadata = Mock()
        existing_cj.metadata.labels = None
        existing_cj.metadata.annotations = None
        existing_cj.metadata.owner_references = None

        can_adopt, reason = _can_safely_adopt_cronjob(
            existing_cj, "test-uid-123", "test-schedule", "test-namespace"
        )

        assert can_adopt is False
        assert "no matching ownership indicators" in reason

    def test_handles_empty_labels_and_annotations(self) -> None:
        """Test handling of empty labels and annotations."""
        existing_cj = Mock()
        existing_cj.metadata = Mock()
        existing_cj.metadata.labels = {}
        existing_cj.metadata.annotations = {}
        existing_cj.metadata.owner_references = []

        can_adopt, reason = _can_safely_adopt_cronjob(
            existing_cj, "test-uid-123", "test-schedule", "test-namespace"
        )

        assert can_adopt is False
        assert "no matching ownership indicators" in reason

    def test_priority_order_owner_uid_over_annotation(self) -> None:
        """Test that owner UID label takes priority over annotation."""
        existing_cj = Mock()
        existing_cj.metadata = Mock()
        existing_cj.metadata.labels = {
            LABEL_MANAGED_BY: "ansible-operator",
            LABEL_OWNER_UID: "test-uid-123",
        }
        existing_cj.metadata.annotations = {
            ANNOTATION_OWNER_UID: "different-uid-456",
        }
        existing_cj.metadata.owner_references = []

        can_adopt, reason = _can_safely_adopt_cronjob(
            existing_cj, "test-uid-123", "test-schedule", "test-namespace"
        )

        assert can_adopt is True
        assert reason == "matching owner UID"

    def test_priority_order_owner_reference_over_annotation(self) -> None:
        """Test that owner reference takes priority over UID annotation."""
        existing_cj = Mock()
        existing_cj.metadata = Mock()
        existing_cj.metadata.labels = {}  # Not managed by ansible-operator
        existing_cj.metadata.annotations = {
            ANNOTATION_OWNER_UID: "different-uid-456",
        }
        owner_ref = Mock()
        owner_ref.kind = "Schedule"
        owner_ref.name = "test-schedule"
        owner_ref.uid = "test-uid-123"
        existing_cj.metadata.owner_references = [owner_ref]

        can_adopt, reason = _can_safely_adopt_cronjob(
            existing_cj, "test-uid-123", "test-schedule", "test-namespace"
        )

        assert can_adopt is True
        assert reason == "matching owner reference"
