"""Parsing for everyday-assistant commands: phone status, to-dos and reminders, the daily plan
(decision support) and routines (workflows). Rule-based, offline.

Design credit: PokeClaw (https://github.com/agents-io/PokeClaw, Apache License 2.0)
  - device-status categories follow its GetDeviceInfoTool;
  - to-dos with optional due date and priority follow its kb_add_todo tool;
  - routines follow its Skill idea (a named recipe of steps run deterministically, no model);
  - compound commands ("... and ... then ...") follow its PipelineRouter, which detects
    and/then before single-command matching. PokeClaw hands those to an on-device LLM; here
    each part is run by the rule parser, in order.
No code was taken from OpenOmniBot (its licence forbids use by organisations).
"""
import re
from datetime import date, timedelta

WEEKDAY = {"monday": 0, "somvar": 0, "tuesday": 1, "mangalvar": 1, "wednesday": 2, "budhvar": 2,
           "thursday": 3, "guruvar": 3, "friday": 4, "shukravar": 4, "saturday": 5, "shanivar": 5,
           "sunday": 6, "ravivar": 6}

# ---------- phone status ----------
_ASK = (r"(\?|\b(kitni|kitna|kitne|kya|kaisa|kaisi|how much|how many|what|what's|whats|status|check|"
        r"batao|bata|bta|dikhao|level|left|bacha|bachi|baki|kab|when|is it|on hai|off hai|chal raha|"
        r"working|info|details|tell me)\b)")
INFO = (
    ("battery", r"\b(battery|charging|charge)\b"),
    ("storage", r"\b(storage|space|jagah)\b"),
    ("memory", r"\b(ram|memory)\b"),
    ("alarm", r"\b(next|agla|agle|upcoming)\b.*\balarms?\b|\balarms?\b.*\b(kab|when)\b"),
    ("device", r"\b(android version|phone model|phone details|device info|device details|about (?:my )?phone|"
               r"kaunsa phone|which phone|phone ki jaankari|phone ki details|os version)\b"),
    ("screen", r"\b(brightness|dark mode)\b"),
    ("network", r"\b(internet|network|wi-?fi|mobile data|online)\b"),
    ("time", r"\b(time kya|kitne baje|what time|time kitna|current time|samay|abhi kya time|time batao|"
             r"aaj ki date|today'?s date|what'?s the date|date kya|aaj kaun sa din|what day)\b"),
)
_NOT_INFO = re.compile(r"\b(send|bhejo|bhej|message|msg|call|set|lagao|laga|remind|yaad|todo|band karo|on karo)\b")


def parse_info(low):
    if _NOT_INFO.search(low):
        return None
    for cat, rx in INFO:
        if re.search(rx, low) and (cat in ("time", "device", "alarm") or re.search(_ASK, low)):
            return {"intent": "device_info", "entities": {"category": cat}}
    return None


# ---------- dates, priority ----------
def due_date(low, today):
    """(date or None, matched words removed)."""
    for rx, delta in ((r"\b(day after tomorrow|parso|parson)\b", 2), (r"\b(tomorrow|kal)\b", 1),
                      (r"\b(today|aaj|tonight)\b", 0)):
        m = re.search(rx, low)
        if m:
            return today + timedelta(days=delta), low[:m.start()] + " " + low[m.end():]
    m = re.search(r"\b(?:on\s+|next\s+|is\s+|this\s+)?(%s)\b" % "|".join(WEEKDAY), low)
    if m:
        ahead = (WEEKDAY[m.group(1)] - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead), low[:m.start()] + " " + low[m.end():]
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", low)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), low[:m.start()] + " " + low[m.end():]
        except ValueError:
            pass
    m = re.search(r"\bon\s+(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?\b", low)
    if m:
        d = int(m.group(1))
        y, mo = today.year, today.month
        if d < today.day:
            y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
        try:
            return date(y, mo, d), low[:m.start()] + " " + low[m.end():]
        except ValueError:
            pass
    return None, low


def priority(low):
    if re.search(r"\b(urgent|important|high priority|high|zaroori|zaruri|jaroori|jaruri|asap)\b", low):
        return "high"
    if re.search(r"\b(low priority|low|baad mein|whenever)\b", low):
        return "low"
    return None


_PRIO_WORDS = r"\b(urgent|important|high priority|low priority|priority|high|low|zaroori|zaruri|jaroori|jaruri|asap)\b"


# ---------- to-dos and reminders ----------
REMIND_RE = re.compile(r"\b(remind me|reminder|yaad dila(?:na|o|ye|iye|\s*dena|\s*do|\s*dijiye)?|"
                       r"yaad karwa(?:na|\s*dena|\s*do)?|yaad karana)\b")
TODO_ADD_RE = re.compile(r"\b(add (?:a )?(?:todo|to-?do|task)|todo|to-?do|to do list|task list)\b")
LIST_RE = re.compile(r"\b(my|mere|meri|show|list|dikhao|dikha|pending|open|kya kya|what are|batao)\b.*"
                     r"\b(todos?|to-?dos|to do|tasks?|kaam|reminders?)\b|\b(kya kya karna hai|what do i have to do)\b")
DONE_RE = re.compile(r"\b(done|complete|completed|finished|ho gaya|ho gayi|ho gya|kar liya|kar diya|"
                     r"kar li|kar di|mark)\b")


def _clean_text(s):
    # "reminder" is a command word only at the start ("reminder: pay bill", "set a reminder to ...");
    # inside the text ("to test the reminder") it stays.
    s = re.sub(r"^\s*(?:set\s+(?:a|an)\s+)?reminder\b\s*(?:for|to|:)?", " ", s)
    s = re.sub(r"\b(remind me|set a|set an|add|a|an|to-?do|todo|to do list|task list|list|"
               r"mein|me daalo|me dalo|daalo|dalo|daal do|add karo|likho|mujhe|please|plz|at|on|baje|for)\b"
               r"|yaad dila\w*(\s*(dena|do|dijiye))?|yaad karwa\w*(\s*(dena|do))?|yaad karana", " ", s)
    s = re.sub(_PRIO_WORDS, " ", s)
    s = re.sub(r"\s+", " ", s).strip(" ,.:-")
    s = re.sub(r"^(to|ki|ke|that|about)\s+", "", s)
    s = re.sub(r"\s+(ko|ki|ke|that)$", "", s)
    return s.strip(" ,.:-")


def parse_todo(t, today, daily_time):
    """add_todo (with optional due date/time -> reminder), list_todos, done_todo, or None."""
    low = t.lower().strip()
    if LIST_RE.search(low) and not REMIND_RE.search(low) and not re.search(r"\badd\b", low):
        return {"intent": "list_todos", "entities": {}}
    m = re.match(r"^mark\s+(?:the\s+)?(?:todo\s+|task\s+)?(.+?)\s+(?:as\s+)?(?:done|complete|completed|finished)$", low)
    if m:
        idx = re.fullmatch(r"#?(\d{1,2})", m.group(1).strip())
        return {"intent": "done_todo", "entities": {"index": int(idx.group(1))} if idx else {"text": m.group(1).strip()}}
    if DONE_RE.search(low) and re.search(r"\b(todo|to-?do|task|#?\d+)\b", low) and not REMIND_RE.search(low):
        m = re.search(r"#?\b(\d{1,2})\b", low)
        rest = re.sub(r"\b(todo|to-?do|task|done|complete|completed|finished|ho gaya|ho gayi|ho gya|kar liya|"
                      r"kar diya|kar li|kar di|mark|as|is|the|number|no)\b|#?\b\d{1,2}\b", " ", low)
        rest = re.sub(r"\s+", " ", rest).strip(" ,.")
        ent = {"index": int(m.group(1))} if m and not rest else ({"text": rest} if rest else {})
        return {"intent": "done_todo", "entities": ent}
    remind = bool(REMIND_RE.search(low))
    hinglish_add = re.search(r"^(.+?)\s+(?:ko\s+)?(?:todo|to-?do|to do)(?:\s+list)?\s+(?:mein|me|main)\s+"
                             r"(?:daalo|dalo|daal do|add karo|likho|add kar do)$", low)
    if not (remind or hinglish_add or re.match(r"^(add\s+(?:a\s+)?)?(todo|to-?do|task)\b", low)):
        return None
    ent = {}
    d, rest = due_date(low, today)
    time, rest = daily_time(rest)
    if time and not re.search(r"\d", low) and not re.search(r"\b(subah|morning|shaam|evening|raat|night|dopahar|"
                                                           r"afternoon)\b", low):
        time = None
    if time and not re.search(r"\b(am|pm|a\.m\.|p\.m\.|subah|morning|dopahar|afternoon|shaam|sham|evening|raat|"
                              r"night)\b|:\d\d", low):
        h = int(time[:2])
        if 1 <= h <= 7:  # "5 baje yaad dilana": in speech an unqualified 1-7 o'clock usually means evening
            time = "%02d%s" % (h + 12, time[2:])
    p = priority(low)
    text = _clean_text(hinglish_add.group(1) if hinglish_add else rest)
    if text:
        ent["text"] = text
    if d:
        ent["due"] = d.isoformat()
    if time:
        ent["time"] = time
        ent.setdefault("due", today.isoformat())  # "remind me at 5 pm" = today (assistant moves past times)
    if p:
        ent["priority"] = p
    ent["remind"] = remind or bool(time)
    return {"intent": "add_todo", "entities": ent}


# ---------- decision support: the day's plan ----------
BRIEF_RE = re.compile(
    r"\b(plan my day|my day|day plan|daily plan|briefing|agenda|aaj ka plan|kal ka plan|aaj kya karna|"
    r"kal kya karna|ab kya karun|ab kya karu|kya karna chahiye|what should i do|what's my plan|whats my plan|"
    r"what is my plan|plan for today|plan for tomorrow|today'?s plan|tomorrow'?s plan|summary of my day|"
    r"aaj ka schedule|kal ka schedule|my schedule)\b")


def parse_briefing(low):
    if not BRIEF_RE.search(low):
        return None
    tomorrow = bool(re.search(r"\b(tomorrow|kal)\b", low))
    return {"intent": "plan_day", "entities": {"day": "tomorrow" if tomorrow else "today"}}


# ---------- routines (workflows) ----------
def split_steps(s):
    """'a; b then c' -> ['a', 'b', 'c'] (';', 'then', 'phir', 'uske baad', 'after that')."""
    parts = re.split(r"\s*;\s*|\s+(?:and then|then|aur phir|phir|uske baad|after that)\s+", s, flags=re.I)
    return [p.strip(" ,.") for p in parts if p.strip(" ,.")]


# words around a routine's name that are about WHEN, not part of the name. Part-of-day words
# (morning, shaam...) are NOT here: "good morning" is a name, and the time words next to the
# number were already removed by daily_time().
_REPEAT_WORDS = (r"\b(har\s*din|roz|rozana|daily|every\s*day|everyday|every|each|har|at|on|ko|ke|baje|chalao|"
                 r"chala do|run|start|karo|schedule|set|my|the|weekdays?|working days?|weekends?|monday|tuesday|"
                 r"wednesday|thursday|friday|saturday|sunday|somvar|mangalvar|budhvar|guruvar|shukravar|shanivar|"
                 r"ravivar)s?\b")


def parse_routine(t, daily_time=None, weekday_days=None):
    low = t.lower().strip()
    m = re.match(r"^(?:create|make|new|save|add)?\s*(?:a\s+)?routine\s+(?:called\s+|named\s+)?(?P<name>[\w ]{1,30}?)"
                 r"\s*(?:banao|bana do)?\s*[:=\-]\s*(?P<steps>.+)$", t.strip(), re.I)
    if m:
        return {"intent": "create_routine", "entities": {"name": m.group("name").strip().lower(),
                                                          "steps": split_steps(m.group("steps"))}}
    m = (re.match(r"^(?:stop|cancel|unschedule|band karo|hatao)\s+(?:the\s+|my\s+)?(?P<name>.+?)\s+routine"
                  r"(?:\s+schedule)?$", low)
         or re.match(r"^(?P<name>.+?)\s+routine\s+(?:schedule\s+)?(?:band karo|stop karo|cancel karo|stop|cancel)$", low))
    if m:
        return {"intent": "unschedule_routine", "entities": {"name": m.group("name").strip()}}
    # "good morning routine har din 7 baje", "schedule good morning routine every day at 7 am"
    if daily_time and re.search(r"\broutine\b", low) and re.search(
            r"\d|\b(subah|morning|shaam|evening|raat|night|dopahar|afternoon)\b", low):
        time, rest = daily_time(low)
        if time:
            rest = re.sub(r"\s+", " ", rest).strip()
            nm = (re.match(r"^(?:schedule|set|run|start|chalao)?\s*(?:the\s+|my\s+)?(?P<name>.+?)\s+routine\b", rest)
                  or re.match(r"^(?:schedule|set|run|start)?\s*(?:the\s+|my\s+)?routine\s+(?P<name>.+)$", rest))
            if nm:
                name = re.sub(r"\s+", " ", re.sub(_REPEAT_WORDS, " ", nm.group("name"))).strip()
                if name:
                    ent = {"name": name, "time": time}
                    days = weekday_days(low) if weekday_days else None
                    if days:
                        ent["days"] = days
                    return {"intent": "schedule_routine", "entities": ent}
    if re.search(r"\b(my|mere|meri|show|list|dikhao)\b.*\broutines?\b", low):
        return {"intent": "list_routines", "entities": {}}
    m = (re.match(r"^(?:delete|remove|hatao|mitao)\s+(?:the\s+)?routine\s+(?P<name>.+)$", low)
         or re.match(r"^(?P<name>.+?)\s+routine\s+(?:delete|remove|hatao|mitao)(?:\s+karo)?$", low))
    if m:
        return {"intent": "delete_routine", "entities": {"name": m.group("name").strip()}}
    m = (re.match(r"^(?:run|start|do|play|chalao|chala do|shuru karo)\s+(?:the\s+|my\s+)?routine\s+(?P<name>.+)$", low)
         or re.match(r"^(?:run|start|do|chalao|chala do|shuru karo)\s+(?:the\s+|my\s+)?(?P<name>.+?)\s+routine$", low)
         or re.match(r"^(?P<name>.+?)\s+routine(?:\s+(?:chalao|chala do|run|start|karo|shuru karo))?$", low))
    if m:
        return {"intent": "run_routine", "entities": {"name": m.group("name").strip()}}
    return None
