"""Deterministic scheduling. The language model never does calendar arithmetic."""
from datetime import datetime, time, timedelta

from . import config


def resolve_window(entities, prefs):
    """Priority: explicit time > explicit window word > saved preference > None (ask user)."""
    if entities.get("time"):
        return "fixed"
    if entities.get("window") in config.WINDOWS:
        return entities["window"]
    for p in prefs:
        tag = (p.get("tags") or {}).get("time_of_day")
        if tag in config.WINDOWS:
            return tag
    return None


def _overlaps(s, e, busy):
    return any(s < be and bs < e for bs, be in busy)


def propose_slot(day, duration, window, fixed_time, busy, now):
    """busy = fixed commitments + already-planned tasks as [(start, end)] tz-aware.
    Returns {"ok": True, "start", "end"} or {"ok": False, "reason": str}."""
    tz = now.tzinfo
    dur = timedelta(minutes=duration)
    if fixed_time:
        h, m = map(int, fixed_time.split(":"))
        s = datetime.combine(day, time(h, m), tz)
        if s < now:
            return {"ok": False, "reason": "That time has already passed."}
        if _overlaps(s, s + dur, busy):
            return {"ok": False, "reason": "Something is already planned at that time."}
        return {"ok": True, "start": s, "end": s + dur}
    lo, hi = config.WINDOWS[window]
    cur = datetime.combine(day, time(lo), tz)
    limit = datetime.combine(day, time(hi), tz)
    if day == now.date() and cur < now:
        step = config.STEP_MINUTES
        base = now.replace(second=0, microsecond=0)
        cur = base + timedelta(minutes=(-base.minute) % step or 0)
        if cur < now:
            cur += timedelta(minutes=step)
    while cur + dur <= limit:
        if not _overlaps(cur, cur + dur, busy):
            return {"ok": True, "start": cur, "end": cur + dur}
        cur += timedelta(minutes=config.STEP_MINUTES)
    return {"ok": False, "reason": "No free %d-minute slot in the %s." % (duration, window)}
