from __future__ import annotations

import hashlib

_MACROS = {
    "@hourly-random",
    "@daily-random",
    "@weekly-random",
    "@monthly-random",
    "@yearly-random",
}


def _stable_int(seed: str, salt: str, modulo: int, offset: int = 0) -> int:
    """Return a stable pseudo-random int in [offset, offset+modulo-1] based on seed+salt."""
    h = hashlib.sha256(f"{seed}:{salt}".encode()).digest()
    # Use first 8 bytes for an integer value
    value = int.from_bytes(h[:8], "big")
    return offset + (value % modulo)


def compute_computed_schedule(spec_schedule: str, uid: str) -> tuple[str, bool]:
    """Compute a concrete cron expression for schedule macros.

    Returns a tuple of (computed_cron, used_macro).
    If no macro is used, returns (spec_schedule, False).
    """
    s = (spec_schedule or "").strip()
    if s not in _MACROS:
        return s, False

    # Common fields
    minute = _stable_int(uid, "minute", 60)
    hour = _stable_int(uid, "hour", 24)

    if s == "@hourly-random":
        # minute * * * *
        return f"{minute} * * * *", True

    if s == "@daily-random":
        # minute hour * * *
        return f"{minute} {hour} * * *", True

    if s == "@weekly-random":
        # minute hour * * day_of_week(0-6)
        dow = _stable_int(uid, "dow", 7)
        return f"{minute} {hour} * * {dow}", True

    if s == "@monthly-random":
        # minute hour day_of_month(1-28) * *
        dom = _stable_int(uid, "dom", 28, offset=1)
        return f"{minute} {hour} {dom} * *", True

    if s == "@yearly-random":
        # minute hour day_of_month(1-28) month(1-12) *
        dom = _stable_int(uid, "dom", 28, offset=1)
        month = _stable_int(uid, "month", 12, offset=1)
        return f"{minute} {hour} {dom} {month} *", True

    # Fallback: return as-is
    return s, True
