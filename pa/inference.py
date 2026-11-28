"""Inference interface + a constrained rule-based parser (NOT an LLM).
Backend output is untrusted: `validate` re-checks everything in application code."""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import config, control, everyday, messaging

ALLOWED = {"remember_preference", "add_note", "query_notes", "schedule_work",
           "call_contact", "find_photos", "open_app", "schedule_message", "send_message",
           "set_alarm", "set_timer", "show_alarms",
           "device_info", "add_todo", "list_todos", "done_todo", "plan_day",
           "create_routine", "run_routine", "list_routines", "delete_routine",
           "schedule_routine", "unschedule_routine", "auto_send", "schedule_notice", "schedule_task",
           "list_automations",
           "change_setting", "smalltalk", "phone_control",
           "save_handle", "list_handles", "delete_handle", "messaging_help", "unknown"}
UNSUPPORTED = {"change_setting"}
PHOTO_RANGES = {"today", "yesterday", "week", "month"}
# call_contact is NOT here: the user chose immediate calls when exactly one contact matches
# (see Assistant._call for the conditions that still force a question).
APPROVAL_INTENTS = {"schedule_work", "schedule_message"}  # a daily message is approved once, then runs daily
CARRIERS = {"jio", "airtel", "vi", "vodafone", "idea", "bsnl"}
FIELDS = {
    "remember_preference": {"text"},
    "add_note": {"text"},
    "query_notes": {"query"},
    "schedule_work": {"title", "date", "time", "window", "duration_minutes"},
    "call_contact": {"name", "number", "prefix", "sim", "via", "video"},
    "find_photos": {"range", "keyword"},
    "open_app": {"app"},
    "schedule_message": {"name", "number", "prefix", "text", "time", "channel", "repeat", "days"},
    "schedule_routine": {"name", "time", "days"},
    "schedule_notice": {"text", "time", "days"},      # every day / some weekdays: a reminder notification
    "schedule_task": {"command", "time", "days"},     # every day / some weekdays: run a command (tap to run)
    "list_automations": set(),
    "unschedule_routine": {"name"},
    "send_message": {"name", "number", "prefix", "text", "channel", "sim", "name_text"},
    "set_alarm": {"time", "days", "label"},
    "device_info": {"category"},
    "add_todo": {"text", "due", "time", "priority", "remind"},
    "done_todo": {"index", "text"},
    "plan_day": {"day"},
    "create_routine": {"name", "steps"},
    "run_routine": {"name"},
    "delete_routine": {"name"},
    "set_timer": {"seconds", "label"},
    "smalltalk": {"kind"},
    "phone_control": {"ui_steps"},
    "save_handle": {"name", "app", "handle"},
    "list_handles": set(),
    "delete_handle": {"name", "app"},
    "messaging_help": {"msg_app"},
}
CALL_FILLERS = set("ko to please plz karo kar do de dena lagao laga call dial phone fone ek zara jara "
                   "kardo krdo mujhe se baat karni hai karwa karwao make a the abhi sim wale wali wala "
                   "number no jiska jiske jo starting start shuru hota hoti from using via "
                   "usko unko isko inko use unhe inhe usse unse phir fir dobara again "
                   # English glue words ("call neha whose number starts with 7012 from sim 1")
                   "whose who which that his her their its starts started starting begins begin "
                   "beginning with digits digit and for me my can could you u pls kindly on in is "
                   "ka ki ke hai h hota hoti wo woh uska uski unka unki "
                   # "i want to talk to mummy", "mummy se baat karni hai", "ring mom", "give a call to papa"
                   "i back give gimme ring fon kol talk speak baat karna karni karun karu krni krna chahta chahti "
                   "chahiye chahta hu hun hoon want wanna would like need with get connect put id im".split())
# "whose number starts with 7012", "number starting 7012", "jiska number 7012 se shuru hota hai"
PREFIX_PHRASE = re.compile(
    r"\b(?:(?:whose|jiska|jiske|jinka|uska|unka)\s+)?(?:(?:phone|mobile)\s+)?(?:number|no\.?|num)?\s*(?:is\s+)?"
    r"(?:starts?|starting|begins?|beginning|shuru)\s*(?:hota\s+|hoti\s+)?(?:from|with|by|se|at)?\s*"
    r"((?:\d[\s\-]?){3,6})(?!\d)")


def _take_sim(rest):
    """(sim or None, rest without the SIM words). sim: '1' | '2' | carrier name.
    'sim 2', '1 wali sim', 'dusri sim', 'airtel se', 'from jio sim', 'via airtel'."""
    sim = None
    m = (re.search(r"\bsim\s*(?:no\.?\s*|number\s*)?([12])\b", rest, re.I)
         or re.search(r"\b([12])\s*(?:no\.?|number)?\s*(?:wali|wale|vala|wala)?\s*sim\b", rest, re.I))
    if m:
        sim = m.group(1)
    else:
        m = re.search(r"\b(pehli|pahli|pehle|first|1st|dusri|doosri|dusre|second|2nd)\s+(?:wali\s+)?sim\b",
                      rest, re.I)
        if m:
            sim = "1" if m.group(1).lower() in ("pehli", "pahli", "pehle", "first", "1st") else "2"
        else:
            m = re.search(r"\b(%s)\s+(?:(?:wali|wale|ki|ke)\s+)?(?:sim\s+)?(?:se|from|using|via)\b"
                          % "|".join(CARRIERS), rest, re.I)
            if not m:  # English order: "via airtel", "from jio sim", "using vi"
                m = re.search(r"\b(?:from|using|via|through|on|with)\s+(?:my\s+|the\s+)?(%s)\b(?:\s+sim\b)?"
                              % "|".join(CARRIERS), rest, re.I)
            if m:
                sim = m.group(1).lower()
    if m:
        rest = rest[:m.start()] + " " + rest[m.end():]
    return sim, rest


def _parse_call(t, low):
    """Entities for a call request: name, number (full), prefix (first digits), sim."""
    ent = {}
    sim, rest = _take_sim(low)
    if sim:
        ent["sim"] = sim
    p = PREFIX_PHRASE.search(rest)
    if p:
        ent["prefix"] = re.sub(r"\D", "", p.group(1))
        rest = rest[:p.start()] + " " + rest[p.end():]
    # Walk the words. A 1-2 digit number right after a name word belongs to the name
    # ("neha 2" is a contact called "Neha 2"), unless more digits follow
    # ("rahul 98 11 ..." is a spaced phone number: another short group follows).
    # "neha 2 7012" = name "neha 2" + prefix 7012. Other digits form the number/prefix.
    toks = re.findall(r"\+?\d+|[^\W\d_][\w.]*", rest)
    name, digs = [], []
    for i, tk in enumerate(toks):
        if tk[0] in "+0123456789":
            nxt = toks[i + 1] if i + 1 < len(toks) else ""
            more = nxt[:1] in tuple("+0123456789") and len(nxt) <= 2 if nxt else False
            if len(tk) <= 2 and name and i and toks[i - 1] == name[-1] and not more:
                name.append(tk)
            else:
                digs.append(tk)
        elif tk not in CALL_FILLERS:
            name.append(tk)
    digits = "" if p else re.sub(r"\D", "", "".join(digs))
    if len(digits) >= 7:
        ent["number"] = "".join(digs)
    elif 3 <= len(digits) <= 6:
        ent["prefix"] = digits
    ent["name"] = " ".join(name)
    return ent
# ---------- alarms and timers: "set an alarm of 5 am", "subah 5 baje ka alarm lagao" ----------
ALARM_RE = re.compile(r"\b(alarm|alarms|alaram|wake me|uthana|utha dena|utha do|jagana|jaga dena|jaga do)\b", re.I)
TIMER_RE = re.compile(r"\btimer\b", re.I)
WEEKDAYS = {"sunday": 1, "ravivar": 1, "monday": 2, "somvar": 2, "tuesday": 3, "mangalvar": 3,
            "wednesday": 4, "budhvar": 4, "thursday": 5, "guruvar": 5, "friday": 6, "shukravar": 6,
            "saturday": 7, "shanivar": 7}
TIMER_UNITS = r"(seconds?|secs?|sec|minutes?|mins?|min|minat|hours?|hrs?|hr|ghante|ghanta)"


def _parse_alarm(t):
    """{'intent': set_alarm | set_timer | show_alarms, ...} or None."""
    low = t.lower()
    if TIMER_RE.search(low):
        secs = 0
        for m in re.finditer(r"(\d+)\s*%s\b" % TIMER_UNITS, low):
            n, unit = int(m.group(1)), m.group(2)
            secs += n * 3600 if unit.startswith(("h", "g")) else n * 60 if unit.startswith("m") else n
        return {"intent": "set_timer", "entities": {"seconds": secs} if secs else {}}
    if not ALARM_RE.search(low):
        return None
    if not re.search(r"\d", low) and re.search(r"\b(show|dikhao|dikha|list|open|kholo|my|mere|meri)\b", low):
        return {"intent": "show_alarms", "entities": {}}
    ent = {}
    if re.search(r"\b(har\s*din|roz|rozana|daily|every\s*day|everyday)\b", low):
        ent["days"] = [1, 2, 3, 4, 5, 6, 7]
    else:
        days = sorted({d for w, d in WEEKDAYS.items() if re.search(r"\b%ss?\b" % w, low)})
        if days:
            ent["days"] = days
    if re.search(r"\d", low):
        time, rest = _daily_time(t)
        if time is None:  # "alarm for 5", "alarm 6:15": a bare number is the hour
            m = re.search(r"\b(\d{1,2})(?:[:.](\d{2}))?\b", rest)
            if m and int(m.group(1)) < 24 and int(m.group(2) or 0) < 60:
                time = "%02d:%02d" % (int(m.group(1)), int(m.group(2) or 0))
        if time:
            ent["time"] = time
    m = (re.search(r"\b(?:for|to|label|named|called)\s+(?!\d)([a-z][a-z ]{1,30}?)\s*$", low)
         or re.search(r"\b([a-z][a-z ]{1,30}?)\s+ke\s+liye\b", low))
    if m:
        label = re.sub(r"\b(the|my|a|an|alarm|set|at|am|pm|subah|morning|tomorrow|kal|lagao|lagana)\b", " ",
                       m.group(1)).strip()
        if label and not re.fullmatch(r"(am|pm|baje|me|up)", label):
            ent["label"] = label
    return {"intent": "set_alarm", "entities": ent}


# ---------- daily messages: "har subah 8 baje mummy ko good morning message karo" ----------
DAILY_RE = re.compile(r"\b(har|roz|rozana|daily|every|everyday)\b", re.I)
DAILY_MSG_RE = re.compile(r"\b(message|msg|sms|text|whats\s?app|bhejo|bhej|send|wish)\b", re.I)
# repeats we cannot express as "these weekdays at this time"
DAILY_NOT_DAILY = re.compile(r"\b(month|months|mahine|mahina|hour|hours|ghante|ghanta|every other|alternate)\b", re.I)


def weekday_days(low):
    """Calendar weekday numbers (1=Sunday..7=Saturday) named in the text, or None (= every day).
    'weekdays'/'working days' -> Mon-Fri, 'weekend' -> Sat+Sun, 'monday aur friday' -> [2, 6]."""
    if re.search(r"\b(weekdays?|working days?|office days?|somvar se shukravar|monday (?:to|se) friday)\b", low):
        return [2, 3, 4, 5, 6]
    if re.search(r"\b(weekends?|saturday (?:and|aur) sunday|shanivar (?:aur|and) ravivar)\b", low):
        return [1, 7]
    days = sorted({d for w, d in WEEKDAYS.items() if re.search(r"\b%ss?\b" % w, low)})
    return days or None


_WEEKDAY_WORDS = (r"\b(?:on\s+|every\s+|har\s+|each\s+)?(?:weekdays?|working days?|office days?|weekends?|"
                  r"somvar se shukravar|monday (?:to|se) friday|%s)s?\b(?:\s+(?:and|aur|,)\s+)?" % "|".join(WEEKDAYS))
DAY_PARTS = {"subah": "am", "morning": "am", "dopahar": "noon", "afternoon": "noon", "shaam": "pm",
             "sham": "pm", "evening": "pm", "raat": "night", "night": "night"}
DAY_PART_DEFAULT = {"am": "08:00", "noon": "13:00", "pm": "18:00", "night": "21:00"}
_PART_WORDS = "|".join(DAY_PARTS)
_TIME_PATS = (
    r"\b(?:at\s+)?(\d{1,2}):(\d{2})\s*(am|pm|a\.m\.|p\.m\.)?(?:\s*(?:baje|bje))?",
    r"\b(?:at\s+)?(\d{1,2})()\s*(am|pm|a\.m\.|p\.m\.|baje|bje|o'?clock)(?=\W|$)",
    r"\b(?:%s)\s+(?:ke\s+|ko\s+|at\s+)?(\d{1,2})()()\b(?!\s*\d)" % _PART_WORDS,
    r"\bat\s+(\d{1,2})()()\b(?!\s*\d)",
)
MSG_FILLERS = set("send bhejo bhej bhejna do karo kar kardo message msg dm please plz a the wish to ko "
                  "saying say that ki ke ka wala text in at pe".split())


_PART_CONTEXT = (  # a part-of-day word only counts as the schedule time in these positions
    r"\b(?:har|roz|rozana|every|daily|each)\s+(?:din\s+)?(%s)\b",      # har subah, every morning
    r"\b(%s)\s+(?:ke\s+|ko\s+|at\s+)?\d",                               # subah 8, shaam ko 6
    r"\d\s*(?::\d\d)?\s*(?:am|pm|baje|bje)?\s+(?:in the\s+)?(%s)\b",    # 8 baje subah, 8 in the morning
    r"\b(?:in the|at|every)\s+(%s)\b",                                  # in the morning, at night
)


def _merge(spans):
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(b, out[-1][1]))
        else:
            out.append((a, b))
    return out


def _daily_time(s):
    """('HH:MM' or None, s without the time words). 'subah 8 baje' -> 08:00, 'raat 10' -> 22:00,
    'har shaam' -> 18:00 (default for the part of day). 'good morning' inside the message is
    left alone: only a part-of-day word in a schedule position is used."""
    part, spans = None, []
    for pat in _PART_CONTEXT:
        pm = re.search(pat % _PART_WORDS, s, re.I)
        if pm:
            part = DAY_PARTS[pm.group(1).lower()]
            spans.append(pm.span(1))
            break
    hour = None
    for pat in _TIME_PATS:
        m = re.search(pat, s, re.I)
        if m:
            hour, minute = int(m.group(1)), int(m.group(2) or 0)
            ampm = (m.group(3) or "").lower().replace(".", "")
            spans.append(m.span())
            break
    # remove the time and the part-of-day word (merge overlaps, cut from the end)
    for a, b in sorted(_merge(spans), reverse=True):
        s = s[:a] + " " + s[b:]
    s = re.sub(r"\b(?:in the|at|ko|ke)\s*(?=\s(?:har|roz|every|daily)\b|$)", " ", s, flags=re.I)
    if hour is None:
        return (DAY_PART_DEFAULT[part] if part else None), s
    if hour > 23 or minute > 59:
        return None, s
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    elif ampm not in ("am", "pm"):
        if part == "pm" and hour < 12:
            hour += 12
        elif part == "night" and 5 <= hour < 12:
            hour += 12
        elif part == "night" and hour == 12:
            hour = 0
        elif part == "noon" and hour < 7:
            hour += 12
    return "%02d:%02d" % (hour, minute), s


def _msg_quote_channel(s, ent):
    """Take a quoted message text and the channel (whatsapp/sms) out of s. Returns the rest."""
    q = re.search(r"[\"“”](.+?)[\"“”]|(?:^|\s)['‘](.+?)['’](?=\s|$|[.,!?])", s)
    if q:
        ent["text"] = (q.group(1) or q.group(2)).strip()
        s = s[:q.start()] + " " + s[q.end():]
    # speech recognizers write WhatsApp in many ways: "whatsapp", "what's app", "whats app", "watsapp"
    wa = r"(?:what'?s\s?app|wh?ats?app|whatsap)"
    # Truecaller's messages are SMS: "rahul ko truecaller se sms karo hi" = an SMS
    if re.search(r"\btrue\s?caller\b", s, re.I):
        ent["channel"] = "sms"
        s = re.sub(r"\b(?:on|via|by|through|pe|par|se|me|mein|in)?\s*true\s?caller(?:\s+(?:pe|par|se|me|mein|on))?\b",
                   " ", s, count=1, flags=re.I)
    soc = re.search(r"\b(%s)\b" % control.SOCIAL_WORDS, s, re.I)
    if re.search(r"\b%s\b" % wa, s, re.I):
        ent["channel"] = "whatsapp"
    elif re.search(r"\b(?:g\s?mail|e-?mail|mail)\b", s, re.I) and not soc:
        # "rahul ko mail karo ki ...", "send an email to rahul saying hi", "email rahul hi"
        ent["channel"] = "email"
        # only the FIRST mention is the channel: "rahul ko mail karo ki email check karo" keeps the second
        s = re.sub(r"\b(?:on|via|by|through|pe|par|se|me|mein|in)?\s*(?:an?\s+)?(?:g\s?mail|e-?mail|mail)"
                   r"(?:\s+(?:pe|par|se|me|mein|on))?\b", " ", s, count=1, flags=re.I)
    elif soc:
        # "rahul ko instagram pe hi bhejo", "send hi to rahul on snapchat", "insta rahul hi"
        ent["channel"] = control.social_app(soc.group(1))
        s = re.sub(r"^\s*(?:please\s+)?open\s+(?:%s)\s+(?:and|aur|then)\s+" % control.SOCIAL_WORDS, " ", s, flags=re.I)
        s = re.sub(r"\b(?:on|via|by|through|pe|par|se|me|mein|in)?\s*(?:%s)(?:\s+(?:pe|par|se|me|mein|on))?\b"
                   % control.SOCIAL_WORDS, " ", s, count=1, flags=re.I)   # first mention only
    elif ent.get("channel") != "sms" and re.search(r"\b(sms|text)\b", s, re.I):
        ent["channel"] = "sms"
    s = re.sub(r"^\s*(?:please\s+)?open\s+%s\s+(?:and|aur|then)\s+" % wa, " ", s, flags=re.I)
    s = re.sub(r"\b(?:on|via|by|through|pe|par|se|me|mein|in)?\s*(?:%s|sms|text\s+message)"
               r"(?:\s+(?:pe|par|se|me|mein|on))?\b" % wa, " ", s, flags=re.I)
    return re.sub(r"^\s*text\b", " message", s, flags=re.I)  # "text mummy hi" = "message mummy hi"


def _parse_daily(t):
    """Entities for a daily message, or None if this is not one."""
    repeats = DAILY_RE.search(t) or (weekday_days(t.lower()) and re.search(r"\d", t))  # "weekend pe 10 baje ..."
    if not (repeats and DAILY_MSG_RE.search(t)):
        return None
    ent = {"repeat": "unsupported" if DAILY_NOT_DAILY.search(t) else "daily"}
    days = weekday_days(t.lower())
    if days:
        ent["days"] = days
    s = _msg_quote_channel(t, ent)
    s = re.sub(_WEEKDAY_WORDS, " ", s, flags=re.I)  # weekday words are not part of name or message
    ent["time"], s = _daily_time(s)
    if ent["time"] is None:
        ent.pop("time")
    s = re.sub(r"\b(?:har|roz|rozana|daily|every\s*day|everyday|each\s+day|every|din)\b", " ", s, flags=re.I)
    _msg_text_and_who(s, ent)
    return ent


# ---------- automations: "daily subah 9 baje mujhe padhna hai", "har din 7 baje youtube kholo phir ..." ----------
_REMIND_WORDS = re.compile(r"\b(remind|reminder|reminders|yaad\s+(?:dila|dilana|dilaana|dilao|dila\s*do|dila\s*dena|"
                           r"karwa|karwana|karwa\s*do)|notification|notify|alert)\b", re.I)
_MSG_LIKE = re.compile(r"\b(message|msg|sms|text|bhejo|bhej|bhejna|send|wish|dm|mail|email)\b", re.I)
_AUTO_LIST = re.compile(r"(?:(?:show|list|see|open)\s+(?:me\s+)?(?:all\s+)?(?:my\s+)?|(?:meri|mere|saare|sare|sab|sabhi)\s+)?"
                        r"automations?(?:\s+(?:dikhao|dikha\s*do|batao|list\s+karo|kya\s+hain|kaun\s+kaun\s+si\s+hain|"
                        r"kholo|please))?", re.I)


def _notice_text(s):
    """'mujhe padhna hai' / 'remind me to study' / 'padhai ka reminder do' -> the reminder's text."""
    s = re.sub(r"\s+", " ", s)
    for pat in (r"\b(?:please|plz)\b",
                r"\bremind\s+me\s*(?:to|that|about|of)?\b",
                r"\b(?:ka|ki|ke)?\s*reminders?\s*(?:do|de\s*do|dedo|dena|lagao|laga\s*do|set\s*karo|set|chahiye|bhejo|send)?\b",
                r"\byaad\s+(?:dilana|dilaana|dilao|dila\s*do|dila\s*dena|dila|karwana|karwa\s*do|karwa)\b\s*(?:ki|ke|that)?",
                r"\b(?:notification|alert)\s*(?:do|de\s*do|dedo|bhejo|chahiye|send\s*karo)?\b",
                r"\bnotify\s+me\s*(?:to|about|of|that)?\b",
                r"^\s*(?:mujhe|me|i\s+want\s+a)\b"):
        s = re.sub(pat, " ", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" ,.:;-")
    s = re.sub(r"^(?:ki|ke|to|that|at|pe|ko)\s+|\s+(?:ki|ke|to|at|pe|ko)$", "", s, flags=re.I).strip(" ,.:;-")
    return s or None


def _parse_automation(t, low, parse_command, today):
    """Something to do again and again at a time: a reminder notification ('schedule_notice') or a
    command to run ('schedule_task'). Alarms, routines and daily messages have their own parsers."""
    if _AUTO_LIST.fullmatch(low.strip(" .!?")):
        return {"intent": "list_automations", "entities": {}}
    repeats = DAILY_RE.search(low) or (weekday_days(low) and re.search(r"\d", low))
    if not repeats or DAILY_NOT_DAILY.search(low) or re.search(r"\b(alarm|routine|timer)\b", low):
        return None
    if _MSG_LIKE.search(low) and not _REMIND_WORDS.search(low):
        return None                     # a daily message: _parse_daily
    ent = {}
    days = weekday_days(low)
    if days:
        ent["days"] = days
    rest = re.sub(_WEEKDAY_WORDS, " ", t, flags=re.I)
    tm, rest = _daily_time(rest)
    rest = re.sub(r"\b(?:har\s+roz|har\s+din|har|roz|rozana|daily|every\s*day|everyday|each\s+day|every|din|"
                  r"subah|shaam|sham|raat|dopahar|morning|evening|night|afternoon)\b", " ", rest, flags=re.I)
    rest = re.sub(r"\s+", " ", rest).strip(" ,.:;-")
    rest = re.sub(r"^(?:at|on|ko|ke|ki|pe|in\s+the|then|phir)\s+|\s+(?:at|ko|pe|in\s+the)$", "", rest, flags=re.I).strip()
    if tm:
        ent["time"] = tm
    if _REMIND_WORDS.search(low):
        ent["text"] = _notice_text(rest)
        return {"intent": "schedule_notice", "entities": {k: v for k, v in ent.items() if v}}
    if not tm:
        return None                     # no time and no "remind": not an automation
    command = re.sub(r"^\s*mujhe\s+", "", rest, flags=re.I).strip()
    sub = parse_command(command, today)["intent"] if command else "unknown"
    if sub in ("send_message", "schedule_message", "call_contact"):
        return None                     # "mummy ko roz 7 baje whatsapp karna hai ki ...": a daily message
    if sub in TASK_INTENTS:
        ent["command"] = command
        return {"intent": "schedule_task", "entities": ent}
    ent["text"] = _notice_text(rest)    # "daily 9 baje mujhe padhna hai": a reminder
    return {"intent": "schedule_notice", "entities": {k: v for k, v in ent.items() if v}} if ent.get("text") else None


# commands that can run from an automation's notification
TASK_INTENTS = ("phone_control", "open_app", "device_info", "plan_day", "list_todos", "briefing", "query_notes")


def _parse_send(t):
    """A one-off message now: 'send neha a message hi', 'neha ko hi message karo',
    'open whatsapp and send neha a message hi', 'send neha a message from airtel hi'.
    None unless both the text and the person are found (then other intents get a chance)."""
    if not (re.search(r"\b(send|bhejo|bhej|message|msg|sms|text|whats\s?app|dm|e-?mail|g\s?mail|mail)\b", t, re.I)
            or re.match(r"^\s*(?:%s)\s+\S+\s+\S" % control.SOCIAL_WORDS, t, re.I)  # "insta rahul hi"
            or re.search(r"\bko\s+(?:%s)\s+(?:karo|kar\s*do|kardo)\b" % control.SOCIAL_WORDS, t, re.I)
            # "rahul ko instagram pe bolo ki ...", "papa ko whatsapp pe batao ki ..."
            or (re.search(r"\b(?:%s|what'?s\s?app|wh?ats?app|e-?mail|g\s?mail|mail)\b" % control.SOCIAL_WORDS, t, re.I)
                and re.search(r"\bko\b.*\b(?:bol|bolo|kaho|keh|bata|batao|likho|likh)\b", t, re.I))
            or re.search(r"^\s*(?:please\s+|plz\s+)?(?:tell|inform)\s+(?!me\b)", t, re.I)
            or re.search(r"\bko\s+(?:bol|bolo|kaho|keh|bata|batao|likho|likh)\b", t, re.I)):
        return None
    said = re.search(r"\bko\s+(?:bol|bolo|kaho|keh|bata|batao|likho|likh)\b|^\s*(?:tell|inform)\b", t, re.I)
    if (re.search(r"\b(call|dial)\b", t, re.I) and not said
            and not re.search(r"\b(send|bhejo|bhej|message|msg|sms|text)\b", t, re.I)):
        return None  # "neha ko whatsapp pe call karo" is a WhatsApp CALL, not a message saying "call"
    ent = {}
    s = _msg_quote_channel(t, ent)
    if re.match(r"^\s*(?:what'?s\s?app|wh?ats?app|whatsap|sms|e-?mail|g\s?mail|mail|%s)\b" % control.SOCIAL_WORDS, t, re.I) and not re.match(
            r"^\s*(?:send|message|msg|text)\b", s, re.I):
        s = "message " + s  # "whatsapp aman hi": the channel word is the verb
    sim, s = _take_sim(s)
    if sim:
        ent["sim"] = sim
        ent.setdefault("channel", "sms")  # a SIM only matters for SMS
    _msg_text_and_who(s, ent)
    if ent.get("name_text"):
        return ent
    if not (ent.get("name") or ent.get("number")):
        return None
    if not ent.get("text"):
        # "message to neha on whatsapp": keep the person, the assistant asks for the text.
        # Needs a real message word, so "whatsapp kholo" stays an app to open.
        return ent if re.search(r"\b(message|msg|sms|send|bhejo|bhej)\b", t, re.I) else None
    return ent


def _real_text(text):
    """A message text is more than filler words ('message karo' has no text)."""
    return [w for w in re.findall(r"\w+", (text or "").lower()) if w not in MSG_FILLERS]


_SAY = r"(?:saying|that says|which says|that|:|-)"


def _english_msg(s):
    """(name, text) for English word orders, ('__both__', 'name text') when the split needs the
    contacts, or None. Examples:
      send a message hi to aman      | send hi to aman       | send a hi message to aman
      send a message saying hi to x     | send aman a message hi| send a message to aman saying hi
      message rahul saying I'm late     | neha 2 saying good morning | send a message to aman hi"""
    s = re.sub(r"^(?:(?:please|plz|can you|could you|kindly)\s+)+", "", s.strip(" ,.!"), flags=re.I)
    m = re.match(r"^(?:send|message|msg|text|wish|write|tell|inform|dm)\b\s*(?P<rest>.*)$", s, re.I)
    rest = m.group("rest") if m else s
    rest = re.sub(r"^(?:a|an|the|this)\s+", "", rest, flags=re.I)
    if not rest:
        return None
    if m and not re.match(r"^(?:message|msg|text|to)\b", rest, re.I):
        # send aman a message (saying) hi
        mm = re.match(r"^(?P<name>.+?)\s+(?:a\s+|an\s+)?(?:message|msg|text)\b\s*%s?\s*(?P<text>.+)$" % _SAY, rest, re.I)
        if mm and not re.match(r"^to\b", mm.group("text"), re.I):
            return mm.group("name"), mm.group("text")
    rest = re.sub(r"^(?:message|msg|text)\b\s*", "", rest, flags=re.I)
    # to aman saying hi
    mm = re.match(r"^to\s+(?P<name>.+?)\s+%s\s*(?P<text>.+)$" % _SAY, rest, re.I)
    if mm:
        return mm.group("name"), mm.group("text")
    # to aman hi  /  to aman
    mm = re.match(r"^to\s+(?P<both>.+)$", rest, re.I)
    if mm:
        both = mm.group("both").strip(" ,.")
        return ("__both__", both) if len(both.split()) > 1 else (both, None)
    # hi (how are you) to aman  -> the LAST " to " starts the name
    tos = list(re.finditer(r"\s+to\s+", rest, re.I))
    if tos and m:
        text, name = rest[:tos[-1].start()], rest[tos[-1].end():]
        text = re.sub(r"^%s\s+" % _SAY, "", text, flags=re.I)
        text = re.sub(r"\s+(?:message|msg|text)$", "", text, flags=re.I)  # "a hi message to x"
        return name, text
    # neha 2 saying good morning
    mm = re.match(r"^(?P<name>.+?)\s+(?:saying|that says|:|-)\s+(?P<text>.+)$", rest, re.I)
    if mm:
        return mm.group("name"), mm.group("text")
    if m and len(rest.split()) > 1:
        return "__both__", rest.strip(" ,.")  # message aman hi
    return None


def _msg_text_and_who(s, ent):
    """Fill ent['text'] (unless quoted already) and name/prefix/number from what is left."""
    s = re.sub(r"\s+", " ", s).strip(" ,.!:-")
    who = s
    if "text" not in ent:
        name = text = None
        for pat in (
            # papa ko karo ki main nikal gaya
            r"^(?P<name>.+?)\s+ko\s+(?:(?:text|msg|message|sms|dm)\s+)?(?:karo|kar\s*do|kardo|bhejo|bhej\s*do|"
            r"karna\s+hai|bhejna\s+hai)\s+(?:(?:ki|ke|that)\s+)?(?P<text>.+)$",
            # (rahul ko) daily 4 baje sms karna hai ki good morning: the time words took the "ko"
            r"^(?P<name>.+?)\s+(?:karna|bhejna)\s+hai\s+(?:ki|ke|that)\s+(?P<text>.+)$",
            # rahul ko bol do main aa raha hu / papa ko batao ki main pahunch gaya / neha ko likho hi
            r"^(?P<name>.+?)\s+ko\s+(?:bol\s*do|bol\s*dena|bolo|bol|kaho|keh\s*do|keh\s*dena|bata\s*do|"
            r"bata\s*dena|batao|bata|likho|likh\s*do|likh\s*dena|likh)\s+(?:(?:ki|ke|that)\s+)?(?P<text>.+)$",
            # mummy ko good morning (message) karo / bhejo
            r"^(?P<name>.+?)\s+ko\s+(?P<text>.+?)\s*(?:(?:ka|ki|wala|wali)\s+)?(?:message|msg|wish|dm)?\s*"
            r"(?:karo|kar\s*do|kardo|bhejo|bhej\s*do|bhejna|send\s*karo|send\s*kar\s*do|send|karna)?"
            r"\s*(?:please|plz)?$",
        ):
            m = re.match(pat, s, re.I)
            if m and _real_text(m.group("text")):
                name, text = m.group("name"), m.group("text")
                break
        else:
            r = _english_msg(s)
            if r and r[0] == "__both__":
                # "message aman hi" (what the speech recognizer wrote): where the name ends is
                # unknown here ("rahul sharma hi"?). The assistant splits it with the contacts.
                ent["name_text"] = r[1]
                return
            if r:
                name, text = r
        if name:
            who = name
            if text and _real_text(text):
                ent["text"] = text.strip(" ,.")
    who = " ".join(w for w in re.findall(r"\+?[\w.]+", who) if w.lower() not in MSG_FILLERS)
    if who:
        c = _parse_call(who, who.lower())
        ent.update({k: v for k, v in c.items() if k in ("name", "prefix", "number") and v})


# "open whatsapp", "launch the youtube app", "whatsapp kholo", "camera open karo", "insta chalao"
OPEN_PRE = re.compile(r"^(?:please\s+|plz\s+|can you\s+|could you\s+|zara\s+|i want to\s+|i wanna\s+|let'?s\s+)*"
                      r"(?:open|launch|start|run)\s+(?:up\s+)?(.+?)"
                      r"(?:\s+(?:please|plz|for me|now))?[.!]?$")
OPEN_POST = re.compile(r"^(?:mujhe\s+|mera\s+|meri\s+|my\s+)?(.+?)\s+(?:app\s+)?(?:kholo|khol\s*do|kholdo|khol|"
                       r"kholna\s+hai|kholni\s+hai|kholna\s+h|chalana\s+hai|chalani\s+hai|"
                       r"open\s*(?:karo|kar\s*do|kardo|kar)?|chalao|chala\s*do|start\s*(?:karo|kar\s*do)?|"
                       r"launch\s*(?:karo|kar\s*do)?)(?:\s+(?:please|plz|na|do|jaldi))?[.!]?$")
# "go to instagram", "take me to maps": only for well-known apps, so "I want to go to market" stays unknown
OPEN_GO = re.compile(r"^(?:please\s+|plz\s+|can you\s+|could you\s+|i want to\s+|i wanna\s+|let'?s\s+)*"
                     r"(?:go to|take me to|switch to|jump to)\s+(?:the\s+|my\s+)?(whatsapp|whats app|youtube|instagram|insta|"
                     r"facebook|fb|maps|google maps|chrome|camera|gallery|settings|calculator|play store|spotify|gmail|"
                     r"telegram|snapchat|twitter|netflix|paytm|phonepe|gpay|google pay|clock|contacts|calendar|messages|"
                     r"photos|files|notes|browser|dialer)(?:\s+app)?[.!]?$")
APP_NAME_SKIP = {"the", "my", "mera", "meri", "app", "application", "wala", "wali"}


def _parse_open(low):
    """App name for an 'open X' command, or None. Kept strict so that 'kal ki photos kholo'
    stays a photo search and 'open 45 minutes...' never becomes an app."""
    if re.fullmatch(r"(?:please\s+)?(?:camera|cam)\s+on\s*(?:karo|kar\s*do|kardo)", low.strip(" .!")):
        return "camera"  # the only "X on karo" that means an app (wifi / torch on karo are settings)
    g = OPEN_GO.match(low.strip())
    if g:
        return g.group(1)
    m = OPEN_PRE.match(low) or OPEN_POST.match(low)
    if not m:
        return None
    words = [w for w in re.findall(r"[\w&+'.-]+", m.group(1)) if w not in APP_NAME_SKIP]
    if not words or len(words) > 4 or any(w.isdigit() for w in words):
        return None
    photo = [w for w in words if re.fullmatch(PHOTO_WORDS, w)]
    if photo and len(words) > 1:  # "kal ki photos", "goa ki pics": a photo search, not an app
        return None
    return " ".join(words)


# other ways to ask for a call: "ring mom", "papa ko fon lagao", "rahul se baat karni hai", "talk to mummy"
CALLISH_RE = re.compile(r"\b(?:ring|fon|kol|baat\s+(?:kar\w*|krni|krna|karwa\w*)|talk\s+to|speak\s+(?:to|with))\b")
SETTING_RE = re.compile(r"\b(wifi|wi-fi|bluetooth|brightness|volume|airplane|torch)\b")
PHOTO_WORDS = r"photos?|pics?|pictures?|tasveer|tasvir|images?|gallery|screenshots?"
PHOTO_SKIP = set("ki ke wali wale of mere meri my aaj kal today yesterday pichle pichhle last is this "
                 "hafte week mahine month sab all saari saare dikhao dikha show find dhundo dhoondo "
                 "kholo open".split())
REQUIRED = {
    "remember_preference": ["text"], "add_note": ["text"], "query_notes": ["query"],
    "schedule_work": ["title", "duration_minutes", "date"],
    "open_app": ["app"],
}


class ModelUnavailable(Exception):
    pass


@dataclass
class Intent:
    intent: str
    entities: dict = field(default_factory=dict)
    missing_fields: list = field(default_factory=list)
    requires_approval: bool = False


class InferenceBackend:
    name = "base"
    is_llm = False

    def parse(self, text: str, today: date) -> dict:
        raise NotImplementedError


def _window_word(low):
    if re.search(r"\b(subah|morning)\b", low):
        return "morning"
    if re.search(r"\b(dopahar|afternoon)\b", low):
        return "afternoon"
    if re.search(r"\b(shaam|sham|evening)\b", low):
        return "evening"
    return None


def _time(low):
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", low)
    return "%02d:%s" % (int(m.group(1)), m.group(2)) if m else None


class ConstrainedParser(InferenceBackend):
    """Fixed patterns for English + Romanized Hindi. Only understands the phrasings below."""
    name = "constrained rule parser (NOT an LLM)"
    is_llm = False

    def followup(self, text):
        """Answer to 'which time?' question."""
        return {k: v for k, v in (("window", _window_word(text.lower())), ("time", _time(text.lower()))) if v}

    def parse(self, text, today):
        t = text.strip()
        low = t.lower()
        kind = smalltalk_kind(low)
        if kind:
            return {"intent": "smalltalk", "entities": {"kind": kind}}
        # "hello lazey, call mummy" / "ok open whatsapp": drop the greeting, keep the command
        lead = re.match(r"^(?:(?:hi+|hello+|hey+|ok(?:ay)?|acha|accha|lazey|lazy)[\s,!.]+)+(?=\S)", t, re.I)
        if lead:
            t = t[lead.end():]
            low = t.lower()
        handle = parse_handle(low)
        if handle is not None:
            return handle
        how = parse_messaging_help(low)
        if how is not None:
            return how
        m = re.match(r"^(?:mujhe\s+)?(?:yaad rakho|yad rakho|yaad rakhna|yad rakhna|remember(?: that)?)[\s,:\-]*"
                     r"(?:ki\s+|ke\s+)?(.+)$", low, re.S)
        if m:
            return {"intent": "remember_preference", "entities": {"text": t[m.start(1):]}}
        m = re.match(r"^note\s*(?:karo|kar do|kardo|kar lo|karlo|this|this down|down)?\s*[:\-]\s*(.+)$", low, re.S) or \
            re.match(r"^(?:ye\s+|yeh\s+|isko\s+|ise\s+)?note\s+(?:karo|kar do|kardo|kar lo|karlo|this down|this|down)\s*"
                     r"(?:ki\s+|ke\s+)?(.+)$", low, re.S) or \
            re.match(r"^(?:please\s+|plz\s+)?(?:make|take|add|write|create|save|jot|put)\s+(?:a\s+|down\s+|this\s+)?"
                     r"(?:quick\s+)?note(?:\s+(?:of|that|about))?[\s:,\-]*(.+)$", low, re.S) or \
            re.match(r"^(?:mera\s+|meri\s+|ek\s+|ye\s+|yeh\s+)?note\s+(?:save\s+karo|save\s+kar\s*do|likho|likh\s*do|"
                     r"likh\s*lo|add\s+karo|bana\s+do|banao)\s*[:\-]?\s*(?:ki\s+|ke\s+|that\s+)?(.+)$", low, re.S)
        if m:
            return {"intent": "add_note", "entities": {"text": t[m.start(1):]}}
        # automations: "daily subah 9 baje mujhe padhna hai", "har din 7 baje youtube kholo phir lofi search karo"
        auto = _parse_automation(t, low, self.parse, today)
        if auto is not None:
            return auto
        # phone control: "youtube kholo phir lofi search karo", "rahul pe click karo", "back jao"
        ctl = control.parse_control(t, _parse_open, PHOTO_WORDS)
        if ctl is not None:
            return {"intent": "phone_control", "entities": {"ui_steps": ctl["steps"]}}
        # "auto send on karo", "turn on auto-send", "autosend chalu", "is auto send on?"
        if re.search(r"\bauto[\s\-]?send\b", low):
            return {"intent": "auto_send", "entities": {}}
        for found in (everyday.parse_routine(t, _daily_time, weekday_days), everyday.parse_briefing(low),
                      everyday.parse_info(low),
                      everyday.parse_todo(t, today, _daily_time)):
            if found is not None:
                return found
        alarm = _parse_alarm(t)
        if alarm is not None:
            return alarm
        daily = _parse_daily(t)
        if daily is not None:
            return {"intent": "schedule_message", "entities": daily}
        send = _parse_send(t)
        if send is not None:
            return {"intent": "send_message", "entities": send}

        dur = re.search(r"(\d+)\s*(minutes?|mins?|min|ghante|ghanta|hours?|hrs?|hr)\b", low)
        if dur and re.search(r"\b(kaam|work|schedule|slot|time nikalo|time nikal|plan)\b", low):
            n = int(dur.group(1))
            if dur.group(2).startswith(("g", "h")):
                n *= 60
            ent = {"duration_minutes": n}
            if re.search(r"\b(kal|tomorrow)\b", low):
                ent["date"] = (today + timedelta(days=1)).isoformat()
            elif re.search(r"\bparso\b", low):
                ent["date"] = (today + timedelta(days=2)).isoformat()
            elif re.search(r"\b(aaj|today)\b", low):
                ent["date"] = today.isoformat()
            else:
                iso = re.search(r"\d{4}-\d{2}-\d{2}", low)
                if iso:
                    ent["date"] = iso.group(0)
            tm = re.search(r"^(?:(?:kal|aaj|parso|tomorrow|today)\s+)?(.+?)\s+(?:par|pe)\s+\d", t, re.I) or \
                re.search(r"work on (.+?)(?:\s+for\b|\s+tomorrow\b|\s+today\b|$)", t, re.I)
            if tm:
                ent["title"] = tm.group(1)
            ent.update(self.followup(t))
            return {"intent": "schedule_work", "entities": ent}

        if re.search(r"\bnote\b", low) and re.search(r"\b(kya|what|dikhao|show)\b", low):
            m = re.match(r"^(.+?)\s+(?:ke\s+baa?re\s+(?:mein|me)|about)\b", low)
            return {"intent": "query_notes", "entities": {"query": m.group(1) if m else low}}
        app = _parse_open(low)
        if app:
            return {"intent": "open_app", "entities": {"app": app}}
        if (re.search(r"\b(call|dial|phone|fone)\b", low)
                or (CALLISH_RE.search(low) and not SETTING_RE.search(low))) \
                and not re.search(r"\b(%s)\b" % PHOTO_WORDS, low):
            # "call neha on whatsapp", "neha ko whatsapp pe call karo", "whatsapp video call neha"
            wa = re.search(r"\b(what'?s\s?app|wh?ats?app|whatsap)\b", low)
            video = bool(re.search(r"\bvideo\b", low))
            if wa or video:
                low = re.sub(r"\b(?:on|via|par|pe|se|through|from)?\s*(?:what'?s\s?app|wh?ats?app|whatsap)\b"
                             r"(?:\s+(?:pe|par|se|on))?|\b(?:video|voice)\b", " ", low)
            ent = _parse_call(t, low)
            if wa or video:  # a video call is always a WhatsApp call here
                ent["via"] = "whatsapp"
                ent.pop("sim", None)
                if video:
                    ent["video"] = True
            return {"intent": "call_contact", "entities": ent}
        if re.search(r"\b(%s)\b" % PHOTO_WORDS, low):
            ent = {}
            if re.search(r"\b(aaj|today)\b", low):
                ent["range"] = "today"
            elif re.search(r"\b(kal|yesterday)\b", low):  # photos are in the past: kal = yesterday
                ent["range"] = "yesterday"
            elif re.search(r"(pichle|pichhle|last|is|this)\s+(hafte|week)", low):
                ent["range"] = "week"
            elif re.search(r"(pichle|pichhle|last|is|this)\s+(mahine|month)", low):
                ent["range"] = "month"
            if re.search(r"\bscreenshots?\b", low):
                ent["keyword"] = "screenshot"
            elif re.search(r"\bcamera\b", low):
                ent["keyword"] = "camera"
            elif re.search(r"\bwhatsapp\b", low):
                ent["keyword"] = "whatsapp"
            else:
                for pat in (r"([a-z0-9]+)\s+(?:ki|ke|wali|wale)\s+(?:%s)" % PHOTO_WORDS,
                            r"(?:%s)\s+(?:of|from)\s+([a-z0-9]+)" % PHOTO_WORDS):
                    km = re.search(pat, low)
                    if km and km.group(1) not in PHOTO_SKIP:
                        ent["keyword"] = km.group(1)
                        break
            return {"intent": "find_photos", "entities": ent}
        if re.search(r"\b(message|msg|sms|what'?s\s?app|wh?ats?app)\b", low):
            # no person/text yet: the assistant asks for them one at a time
            ent = {}
            _msg_quote_channel(t, ent)
            return {"intent": "send_message", "entities": {k: v for k, v in ent.items() if k == "channel"}}
        if SETTING_RE.search(low):
            return {"intent": "change_setting", "entities": {}}
        return {"intent": "unknown", "entities": {}}


_HANDLE_WORD = r"(?:username|user\s*name|user\s*id|id|handle|account)"
_OF = r"(?:'s|\s+ka|\s+ki|\s+ke)"


_EMAIL_WORDS = r"(?:e-?mail|g\s?mail|mail)(?:\s+(?:id|address|account))?"
# a QUESTION about how to message: "kaise", or "how do / can / to / should ..." (not "hi how are you" inside a message)
_HOW = re.compile(r"\b(kaise|kese|kaisey)\b|\bhow\s+(?:do|does|can|could|should|to|will|would)\b")
_MSG_WORDS = re.compile(r"\b(message|msg|messages|bhej\w*|send|mail|email|dm|text|use|chat|baat|kar\s+sakt\w*|"
                        r"karu|karun|karte|karna)\b")


def parse_messaging_help(low):
    """'instagram pe message kaise bheju?', 'how do I send a whatsapp message', 'kaun kaun se apps se
    message kar sakte ho' -> messaging_help (msg_app None = all apps)."""
    s = re.sub(r"\s+", " ", low.strip(" .!?"))
    if re.search(r"\b(kaun kaun|kon kon|kaun se|kon se|which|what)\b.*\bapps?\b.*\b(message|msg|mail|chat|bhej\w*|send)",
                 s) or re.fullmatch(r"(?:messaging|message) apps?(?: dikhao| batao| list)?", s):
        return {"intent": "messaging_help", "entities": {}}
    if not (_HOW.search(s) and _MSG_WORDS.search(s)) or re.match(r"(?:please\s+)?(?:send|message|msg|text|dm|email|tell)\b", s):
        return None
    for app_id in ("messenger", "whatsapp", "instagram", "snapchat", "gmail", "sms", "facebook", "telegram", "signal",
                   "linkedin", "discord", "x", "teams", "slack", "google_chat", "truecaller"):
        if re.search(r"\b(?:%s)\b" % messaging.WORDS[app_id], s):
            return {"intent": "messaging_help", "entities": {"msg_app": app_id}}
    return None


def parse_handle(low):
    """Saved usernames for Instagram / Messenger / Snapchat:
    'rahul ka instagram username rahul_23 hai', "save rahul's snapchat as rahul.snap",
    'usernames dikhao', 'rahul ka instagram username hatao'."""
    s = re.sub(r"\s+", " ", low.strip(" .!?"))
    apps = control.HANDLE_WORDS
    # Discord: the name as shown in the DMs, may have spaces ("rahul ka discord Rahul King hai")
    d = re.fullmatch(r"(?:save\s+|set\s+)?(?P<name>[a-z][\w .]*?)%s\s+discord(?:\s+(?:name|naam|username|id))?\s*"
                     r"(?:is|as|=|:|to)?\s+(?P<h>[^()]{1,32}?)(?:\s+(?:hai|h|he))?" % _OF, s)
    if d and not re.fullmatch(r"(?:hatao|hata do|delete.*|remove.*|kholo|open)", d.group("h")):
        return {"intent": "save_handle", "entities": {"name": d.group("name").strip(), "app": "discord",
                                                       "handle": d.group("h").strip()}}
    if re.fullmatch(r"(?:(?:mere|meri|my|saved|sab|all|show|list)\s+)*(?:social\s+)?(?:usernames?|handles?)"
                    r"(?:\s+(?:dikhao|batao|list|show|kya hai|kya hain))?", s):
        return {"intent": "list_handles", "entities": {}}
    m = (re.fullmatch(r"(?P<name>[a-z][\w .]*?)%s\s+(?P<app>%s)\s+%s\s+(?:hatao|hata do|delete(?: karo| kar do)?|"
                      r"remove(?: karo)?|mita do|bhool jao)" % (_OF, apps, _HANDLE_WORD), s)
         or re.fullmatch(r"(?:delete|remove|forget)\s+(?P<name>[a-z][\w .]*?)%s\s+(?P<app>%s)(?:\s+%s)?"
                         % (_OF, apps, _HANDLE_WORD), s))
    if m:
        return {"intent": "delete_handle", "entities": {"name": m.group("name").strip(),
                                                         "app": control.social_app(m.group("app"))}}
    m = (re.fullmatch(r"(?:save\s+)?(?P<name>[a-z][\w .]*?)%s\s+(?P<app>%s)\s+%s\s*(?:is|as|hai|=|:|-)?\s*"
                      r"@?(?P<h>[a-z0-9._+@-]{1,120})(?:\s+(?:hai|h|he))?" % (_OF, apps, _HANDLE_WORD), s)
         or re.fullmatch(r"(?:save\s+)?(?P<name>[a-z][\w .]*?)%s\s+(?P<app>%s)\s+(?:is|as|=|:)\s*@?(?P<h>[a-z0-9._+@-]{1,120})"
                         % (_OF, apps), s))
    if not m:   # email address: "rahul ka email rahul@gmail.com hai", "save rahul's email as x@y.com"
        e = re.fullmatch(r"(?:save\s+|set\s+)?(?P<name>[a-z][\w .]*?)%s\s+%s\s*(?:is|as|hai|=|:|-|to)?\s*"
                         r"(?P<h>%s)(?:\s+(?:hai|h|he))?" % (_OF, _EMAIL_WORDS, messaging.EMAIL_RE), s)
        if not e:   # looks like an email but is not a valid one ("rahul@gmail"): the assistant says so
            e = re.fullmatch(r"(?:save\s+|set\s+)?(?P<name>[a-z][\w .]*?)%s\s+%s\s*(?:is|as|hai|=|:|-|to)?\s*"
                             r"(?P<h>[^\s@]*@\S*)(?:\s+(?:hai|h|he))?" % (_OF, _EMAIL_WORDS), s)
        if e:
            return {"intent": "save_handle", "entities": {"name": e.group("name").strip(), "app": "gmail",
                                                           "handle": e.group("h")}}
        e = re.fullmatch(r"(?P<name>[a-z][\w .]*?)%s\s+%s\s+(?:hatao|hata do|delete(?: karo| kar do)?|remove(?: karo)?|"
                         r"mita do)|(?:delete|remove|forget)\s+(?P<name2>[a-z][\w .]*?)%s\s+%s" % (_OF, _EMAIL_WORDS, _OF, _EMAIL_WORDS), s)
        if e:
            return {"intent": "delete_handle", "entities": {"name": (e.group("name") or e.group("name2")).strip(),
                                                             "app": "gmail"}}
    if not m:   # "instagram pe rahul ka username rahul_23 hai"
        m = re.fullmatch(r"(?:on\s+|in\s+)?(?P<app>%s)\s+(?:pe|par|me|mein|main|on|in)\s+(?P<name>[a-z][\w .]*?)%s\s+%s\s*"
                         r"(?:is|hai|=|:|-)?\s*@?(?P<h>[a-z0-9._+@-]{1,120})(?:\s+(?:hai|h|he))?" % (apps, _OF, _HANDLE_WORD), s)
    if not m:   # "rahul ka snap rahul.snap hai" (no 'username', but ends with 'hai')
        m = re.fullmatch(r"(?P<name>[a-z][\w .]*?)%s\s+(?P<app>%s)\s+@?(?P<h>[a-z0-9._+@-]{1,120})\s+(?:hai|h|he)" % (_OF, apps), s)
    if not m:   # "set rahul's instagram to rahul_23"
        m = re.fullmatch(r"(?:set|save|change|update)\s+(?P<name>[a-z][\w .]*?)%s\s+(?P<app>%s)(?:\s+%s)?\s+(?:to|as|=)\s*"
                         r"@?(?P<h>[a-z0-9._+@-]{1,120})" % (_OF, apps, _HANDLE_WORD), s)
    if m and m.group("h") not in ("hai", "kya", "batao", "hatao", "delete", "kholo", "open"):
        return {"intent": "save_handle", "entities": {"name": m.group("name").strip(),
                                                       "app": control.social_app(m.group("app")),
                                                       "handle": m.group("h")}}
    return None


SMALLTALK = (
    ("greet", r"(?:hi+|hello+|hey+|hiya|yo|hola|namaste|namaskar|salaam|salam|sup|good\s+(?:morning|afternoon|evening)|"
              r"gm|ram ram|sat sri akal|pranam)(?:\s+(?:lazey|lazy|there|ji|bhai|dost|buddy|assistant))*"),
    ("how_are_you", r"(?:(?:hi|hello|hey)\s+)?(?:how are you|how r u|how are u|how's it going|hows it going|what'?s up|"
                    r"wassup|whats up|kaise ho(?: aap)?|kaise hain|kaisa hai|kya haal(?: hai)?|kya hal(?: hai)?|"
                    r"aap kaise ho|tum kaise ho)(?:\s+(?:lazey|lazy|ji|bhai|dost))*"),
    ("thanks", r"(?:ok(?:ay)?\s+|acha\s+|accha\s+)?(?:thanks?|thank you|thank u|thx|ty|shukriya|dhanyavaad?|dhanyawad|"
               r"shukria|bahut shukriya|thanks a lot|many thanks|thanks lazey|thank you lazey)(?:\s+(?:lazey|lazy|ji|bhai|so much|a lot))*"),
    ("help", r"(?:help(?: me)?|what can you do|what do you do|how do you work|how to use(?: you| this)?|"
             r"tum kya kar sakte ho|aap kya kar sakte ho|tum kya kya kar sakte ho|kya kya kar sakte ho|"
             r"kya kar sakte ho|tum kya karte ho|kya kar sakta hai|commands|features|madad|madad karo|help karo|mujhe help chahiye)"),
    ("who", r"(?:who are you|who r u|what are you|what is your name|what'?s your name|your name|tum kaun ho|aap kaun ho|"
            r"tera naam kya hai|tumhara naam kya hai|aapka naam kya hai|naam kya hai tumhara|tu kaun hai)"),
    ("bye", r"(?:bye+|goodbye|good bye|see you(?: later)?|see ya|tata|ta ta|alvida|phir milte hain|chalo bye|ok bye|"
            r"good night|gn|shubh ratri|shubhratri)(?:\s+(?:lazey|lazy|ji|bhai))*"),
    ("ack", r"(?:ok(?:ay)?|okk+|k|kk|fine|cool|nice|great|awesome|got it|understood|theek hai|thik hai|theek|thik|"
            r"acha|accha|achha|badhiya|mast|sahi hai|sahi|haan theek hai|ok cool|ok done|samajh gaya|samajh gayi)"),
)


def smalltalk_kind(low):
    """'hello', 'thanks', 'kaise ho', 'what can you do' -> a kind of small talk, else None.
    Whole-message matches only, so a command that merely starts with 'hi' is never swallowed."""
    s = re.sub(r"[^\w' ]+", " ", low.lower())
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"(.)\1{2,}", r"\1\1", s)  # "hiiiii" -> "hii"
    for kind, rx in SMALLTALK:
        if re.fullmatch(rx, s):
            return kind
    return None


def _clean(s, limit):
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(s)).strip()
    return s[:limit]


def validate(raw, today: date) -> Intent:
    """Treat backend output as untrusted. Missing fields and approval need are computed HERE."""
    if not isinstance(raw, dict) or raw.get("intent") not in ALLOWED:
        return Intent("unknown")
    name = raw["intent"]
    src = raw.get("entities") if isinstance(raw.get("entities"), dict) else {}
    ent = {}
    for k in FIELDS.get(name, ()):
        v = src.get(k)
        if v in (None, ""):
            continue
        try:
            if k in ("text", "query"):
                v = _clean(v, config.MAX_INPUT_CHARS)
            elif k == "title":
                v = _clean(v, config.MAX_TITLE_CHARS)
            elif k == "date":
                d = date.fromisoformat(str(v))
                if not (today - timedelta(days=1) <= d <= today + timedelta(days=366)):
                    continue
                v = d.isoformat()
            elif k == "time":
                v = datetime.strptime(str(v), "%H:%M").strftime("%H:%M")
            elif k == "window":
                if v not in config.WINDOWS:
                    continue
            elif k == "duration_minutes":
                v = int(v)
                if not 5 <= v <= 480:
                    continue
            elif k == "name":
                v = re.sub(r"[^\w .'-]", "", _clean(v, 60)).strip()
            elif k == "number":
                v = _clean(v, 25)
                if not re.match(r"^\+?[0-9][0-9 ()\-]{2,19}$", v) or len(re.sub(r"\D", "", v)) < 3:
                    continue
            elif k == "prefix":
                v = str(v)
                if not re.match(r"^\d{3,6}$", v):
                    continue
            elif k == "sim":
                v = str(v).lower()
                if v not in ("1", "2") and v not in CARRIERS:
                    continue
            elif k == "range":
                if v not in PHOTO_RANGES:
                    continue
            elif k == "category":
                if v not in ("battery", "storage", "device", "screen", "network", "time", "alarm", "memory"):
                    continue
            elif k == "due":
                d = date.fromisoformat(str(v))
                if not (today - timedelta(days=1) <= d <= today + timedelta(days=366)):
                    continue
                v = d.isoformat()
            elif k == "priority":
                if v not in ("high", "medium", "low"):
                    continue
            elif k == "remind":
                v = bool(v)
            elif k == "index":
                v = int(v)
                if not 1 <= v <= 99:
                    continue
            elif k == "day":
                if v not in ("today", "tomorrow"):
                    continue
            elif k == "steps":
                v = [_clean(x, 300) for x in list(v)[:10] if str(x).strip()] or ""
            elif k == "ui_steps":
                keep = {"op", "app", "text", "dir", "seconds"}
                v = [{kk: (_clean(vv, control.MAX_TEXT) if isinstance(vv, str) else vv)
                      for kk, vv in s.items() if kk in keep}
                     for s in list(v)[:control.MAX_STEPS] if isinstance(s, dict) and s.get("op") in control.OPS] or ""
            elif k == "days":
                v = sorted({int(d) for d in v if 1 <= int(d) <= 7}) or ""
            elif k == "seconds":
                v = int(v)
                if not 1 <= v <= 24 * 3600:
                    continue
            elif k == "label":
                v = re.sub(r"[^\w .'-]", "", _clean(v, 40)).strip()
            elif k == "name_text":
                v = _clean(v, 300)
            elif k == "via":
                if v != "whatsapp":
                    continue
            elif k == "video":
                v = bool(v)
            elif k == "channel":
                if v not in ("sms", "whatsapp") and not (name == "send_message" and (v in control.SOCIAL or v == "email")) \
                        and not (name == "schedule_message" and v in control.SOCIAL):   # -> an app automation
                    continue
            elif k == "handle":   # a username, an email address or a +number (checked per app in the assistant)
                v = str(v).strip().lstrip("@")
                if src.get("app") == "discord":   # a display name (may have spaces)
                    v = _clean(v, 32)
                    if not re.fullmatch(r"[^\x00-\x1f()]{1,32}", v):
                        continue
                    ent[k] = v
                    continue
                if not re.fullmatch(r"[A-Za-z0-9._%+@-]{1,120}", v):
                    continue
            elif k == "msg_app":
                if v not in messaging.LABEL:
                    continue
            elif k == "repeat":
                if v not in ("daily", "unsupported"):
                    continue
            elif k == "app":
                v = _clean(v, 40).lower()
                if not re.match(r"^[\w &+'.-]{1,40}$", v):
                    continue
            elif k == "keyword":
                v = _clean(v, 40).lower()
                if not re.match(r"^[\w ]{1,40}$", v):
                    continue
        except (ValueError, TypeError):
            continue
        if v != "":
            ent[k] = v
    missing = [f for f in REQUIRED.get(name, []) if f not in ent]
    if name in ("call_contact", "schedule_message", "send_message"):
        if ent.get("number"):
            ent.pop("prefix", None)  # a full number makes the prefix meaningless
        if not (ent.get("name") or ent.get("number") or ent.get("name_text")):
            missing.append("name")
    return Intent(name, ent, missing, requires_approval=(name in APPROVAL_INTENTS))


def load_backend(model_path=None):
    """No LLM is bundled. If a model path is given but unusable, say so; never go remote."""
    if model_path:
        raise ModelUnavailable("LLM backend not implemented/provisioned; using constrained parser.")
    return ConstrainedParser()
