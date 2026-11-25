"""Inference interface + a constrained rule-based parser (NOT an LLM).
Backend output is untrusted: `validate` re-checks everything in application code."""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import config, everyday

ALLOWED = {"remember_preference", "add_note", "query_notes", "schedule_work",
           "call_contact", "find_photos", "open_app", "schedule_message", "send_message",
           "set_alarm", "set_timer", "show_alarms",
           "device_info", "add_todo", "list_todos", "done_todo", "plan_day",
           "create_routine", "run_routine", "list_routines", "delete_routine",
           "schedule_routine", "unschedule_routine", "auto_send",
           "change_setting", "unknown"}
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
}
CALL_FILLERS = set("ko to please plz karo kar do de dena lagao laga call dial phone fone ek zara jara "
                   "kardo krdo mujhe se baat karni hai karwa karwao make a the abhi sim wale wali wala "
                   "number no jiska jiske jo starting start shuru hota hoti from using via "
                   "usko unko isko inko use unhe inhe usse unse phir fir dobara again "
                   # English glue words ("call neha whose number starts with 7012 from sim 1")
                   "whose who which that his her their its starts started starting begins begin "
                   "beginning with digits digit and for me my can could you u pls kindly on in is "
                   "ka ki ke hai h hota hoti wo woh uska uski unka unki".split())
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
MSG_FILLERS = set("send bhejo bhej bhejna do karo kar kardo message msg please plz a the wish to ko "
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
    if re.search(r"\b%s\b" % wa, s, re.I):
        ent["channel"] = "whatsapp"
    elif re.search(r"\b(sms|text)\b", s, re.I):
        ent["channel"] = "sms"
    s = re.sub(r"^\s*(?:please\s+)?open\s+%s\s+(?:and|aur|then)\s+" % wa, " ", s, flags=re.I)
    s = re.sub(r"\b(?:on|via|by|through|pe|par|se|me|mein|in)?\s*(?:%s|sms|text\s+message)"
               r"(?:\s+(?:pe|par|se|me|mein|on))?\b" % wa, " ", s, flags=re.I)
    return re.sub(r"^\s*text\b", " ", s, flags=re.I)


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


def _parse_send(t):
    """A one-off message now: 'send neha a message hi', 'neha ko hi message karo',
    'open whatsapp and send neha a message hi', 'send neha a message from airtel hi'.
    None unless both the text and the person are found (then other intents get a chance)."""
    if not re.search(r"\b(send|bhejo|bhej|message|msg|sms|text|whats\s?app)\b", t, re.I):
        return None
    if re.search(r"\b(call|dial)\b", t, re.I) and not re.search(r"\b(send|bhejo|bhej|message|msg|sms|text)\b", t, re.I):
        return None  # "neha ko whatsapp pe call karo" is a WhatsApp CALL, not a message saying "call"
    ent = {}
    s = _msg_quote_channel(t, ent)
    if re.match(r"^\s*(?:what'?s\s?app|wh?ats?app|whatsap|sms)\b", t, re.I) and not re.match(
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
    m = re.match(r"^(?:send|message|msg|text|wish|write)\b\s*(?P<rest>.*)$", s, re.I)
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
            r"^(?P<name>.+?)\s+ko\s+(?:karo|kar\s*do|kardo|bhejo|bhej\s*do)\s+(?:ki|ke|that)\s+(?P<text>.+)$",
            # mummy ko good morning (message) karo / bhejo
            r"^(?P<name>.+?)\s+ko\s+(?P<text>.+?)\s*(?:(?:ka|ki|wala|wali)\s+)?(?:message|msg|wish)?\s*"
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
OPEN_PRE = re.compile(r"^(?:please\s+|plz\s+|can you\s+|zara\s+)?(?:open|launch|start|run)\s+(?:up\s+)?(.+?)"
                      r"(?:\s+(?:please|plz|for me|now))?[.!]?$")
OPEN_POST = re.compile(r"^(?:mera\s+|meri\s+|my\s+)?(.+?)\s+(?:app\s+)?(?:kholo|khol\s*do|kholdo|khol|"
                       r"open\s*(?:karo|kar\s*do|kardo|kar)?|chalao|chala\s*do|start\s*(?:karo|kar\s*do)?|"
                       r"launch\s*(?:karo|kar\s*do)?)(?:\s+(?:please|plz|na|do|jaldi))?[.!]?$")
APP_NAME_SKIP = {"the", "my", "mera", "meri", "app", "application", "wala", "wali"}


def _parse_open(low):
    """App name for an 'open X' command, or None. Kept strict so that 'kal ki photos kholo'
    stays a photo search and 'open 45 minutes...' never becomes an app."""
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
        m = re.match(r"^(?:yaad rakho|yad rakho|remember(?: that)?)[\s,:\-]*(.+)$", low, re.S)
        if m:
            return {"intent": "remember_preference", "entities": {"text": t[m.start(1):]}}
        m = re.match(r"^note\s*(?:karo|kar do|kardo|this)?\s*[:\-]\s*(.+)$", low, re.S)
        if m:
            return {"intent": "add_note", "entities": {"text": t[m.start(1):]}}
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
        if re.search(r"\b(call|dial|phone|fone)\b", low) and not re.search(r"\b(%s)\b" % PHOTO_WORDS, low):
            # "call neha on whatsapp", "neha ko whatsapp pe call karo", "whatsapp video call neha"
            # "wa" is short for WhatsApp only next to a connector or the call word ("call neha on
            # wa", "neha ko wa pe call karo"), so a name like "Wa" is not taken for the app.
            low = re.sub(r"\b(on|via|through|par|pe|se)\s+wa\b", r"\1 whatsapp", low)
            low = re.sub(r"\bwa(?=\s+(?:pe|par|se|call|video|voice)\b)", "whatsapp", low)
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
        if re.search(r"\b(wifi|wi-fi|bluetooth|brightness|volume|airplane|torch)\b", low):
            return {"intent": "change_setting", "entities": {}}
        return {"intent": "unknown", "entities": {}}


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
                if v not in ("sms", "whatsapp"):
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
