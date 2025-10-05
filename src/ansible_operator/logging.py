from __future__ import annotations

import json
import logging
import sys
from typing import Any


class StructuredJSONFormatter(logging.Formatter):
    """Custom formatter that outputs structured JSON logs."""

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as structured JSON."""
        # Base log entry
        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.default_time_format),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add structured fields if present in the record
        structured_fields = ["controller", "resource", "uid", "runId", "event", "reason"]
        for field in structured_fields:
            if hasattr(record, field):
                log_entry[field] = getattr(record, field)

        # Add any extra fields from the record
        if hasattr(record, "__dict__"):
            for key, value in record.__dict__.items():
                if (
                    key
                    not in [
                        "name",
                        "msg",
                        "args",
                        "levelname",
                        "levelno",
                        "pathname",
                        "filename",
                        "module",
                        "exc_info",
                        "exc_text",
                        "stack_info",
                        "lineno",
                        "funcName",
                        "created",
                        "msecs",
                        "relativeCreated",
                        "thread",
                        "threadName",
                        "processName",
                        "process",
                        "getMessage",
                    ]
                    and key not in structured_fields
                ):
                    log_entry[key] = value

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


def setup_structured_logging() -> None:
    """Configure logging to use structured JSON format."""
    # Configure the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create console handler with structured JSON formatter
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredJSONFormatter())
    root_logger.addHandler(handler)

    # Configure kopf logger to use our structured logging
    kopf_logger = logging.getLogger("kopf")
    kopf_logger.setLevel(logging.INFO)
    # Kopfs handlers will inherit from root logger


class StructuredLogger:
    """Logger that adds structured fields to log records."""

    def __init__(self, name: str):
        self._logger = logging.getLogger(name)

    def _log_with_fields(
        self,
        level: int,
        message: str,
        controller: str | None = None,
        resource: str | None = None,
        uid: str | None = None,
        run_id: str | None = None,
        event: str | None = None,
        reason: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Log with structured fields."""
        extra = {}
        if controller is not None:
            extra["controller"] = controller
        if resource is not None:
            extra["resource"] = resource
        if uid is not None:
            extra["uid"] = uid
        if run_id is not None:
            extra["runId"] = run_id
        if event is not None:
            extra["event"] = event
        if reason is not None:
            extra["reason"] = reason

        # Add any additional kwargs
        extra.update(kwargs)

        self._logger.log(level, message, extra=extra)

    def info(
        self,
        message: str,
        controller: str | None = None,
        resource: str | None = None,
        uid: str | None = None,
        run_id: str | None = None,
        event: str | None = None,
        reason: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Log info message with structured fields."""
        self._log_with_fields(
            logging.INFO, message, controller, resource, uid, run_id, event, reason, **kwargs
        )

    def error(
        self,
        message: str,
        controller: str | None = None,
        resource: str | None = None,
        uid: str | None = None,
        run_id: str | None = None,
        event: str | None = None,
        reason: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Log error message with structured fields."""
        self._log_with_fields(
            logging.ERROR, message, controller, resource, uid, run_id, event, reason, **kwargs
        )

    def warning(
        self,
        message: str,
        controller: str | None = None,
        resource: str | None = None,
        uid: str | None = None,
        run_id: str | None = None,
        event: str | None = None,
        reason: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Log warning message with structured fields."""
        self._log_with_fields(
            logging.WARNING, message, controller, resource, uid, run_id, event, reason, **kwargs
        )

    def debug(
        self,
        message: str,
        controller: str | None = None,
        resource: str | None = None,
        uid: str | None = None,
        run_id: str | None = None,
        event: str | None = None,
        reason: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Log debug message with structured fields."""
        self._log_with_fields(
            logging.DEBUG, message, controller, resource, uid, run_id, event, reason, **kwargs
        )


# Global logger instance
logger = StructuredLogger("ansible-operator")
