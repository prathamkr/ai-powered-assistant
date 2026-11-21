"""Month grid and task grouping for the Calendar screen. Pure Python (no Kivy)."""
import calendar
from datetime import date, datetime

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
WEEKDAYS = ("S", "M", "T", "W", "T", "F", "S")  # Sunday first


def parse_day(iso):
    """'2026-11-20T09:00:00+05:30' -> date(2026, 11, 20); None if it is not a date."""
    if not isinstance(iso, str):
        return None
    try:
        return datetime.fromisoformat(iso).date()
    except ValueError:
        try:
            return date.fromisoformat(iso[:10])
        except ValueError:
            return None


def parse_time(iso):
    """'09:00' for display, '' when the value has no time."""
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M")
    except (ValueError, TypeError):
        return ""


def month_weeks(year, month):
    """Weeks of the month, Sunday first; days outside the month are 0."""
    return calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)


def shift_month(year, month, delta):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def month_title(year, month):
    return "%s %d" % (MONTHS[month - 1], year)


def tasks_by_day(tasks):
    """{date: [task, ...]} sorted by start time; tasks without a usable date are skipped."""
    out = {}
    for t in tasks or []:
        d = parse_day(t.get("start_iso"))
        if d is not None:
            out.setdefault(d, []).append(t)
    for items in out.values():
        items.sort(key=lambda t: str(t.get("start_iso")))
    return out


def day_title(d, today=None):
    today = today or date.today()
    if d == today:
        return "Today, %d %s" % (d.day, MONTHS[d.month - 1])
    return "%s, %d %s" % (calendar.day_name[d.weekday()], d.day, MONTHS[d.month - 1])
