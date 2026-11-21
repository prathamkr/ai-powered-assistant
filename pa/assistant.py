"""Orchestrator: text -> intent -> (memory | plan -> proposal -> approval -> adapter)."""
import re
import secrets
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import config, planner
from .adapters.base import UnsupportedAdapter
from .adapters.daily_android import days_text
from .approval import ApprovalEngine, Unsupported
from .inference import UNSUPPORTED, validate

READ_CONTACTS = "android.permission.READ_CONTACTS"
READ_PHONE_STATE = "android.permission.READ_PHONE_STATE"


DAY_NAMES = {1: "Sunday", 2: "Monday", 3: "Tuesday", 4: "Wednesday", 5: "Thursday", 6: "Friday", 7: "Saturday"}


def _bytes(n):
    return "%.1f GB" % (n / 1e9) if n >= 1e9 else "%.0f MB" % (n / 1e6)


def _day_word(d, today):
    delta = (d - today).days
    return {0: "today", 1: "tomorrow", -1: "yesterday"}.get(delta, d.strftime("%a %d %b"))


# "Did you mean": when nothing matched, show the closest example commands (offline, no model).
EXAMPLES = (
    ("call phone dial lagao fone baat", "call mummy from sim 1"),
    ("message msg whatsapp sms send bhejo text", "send hi to neha on whatsapp"),
    ("alarm wake uthana jagana", "set an alarm for 6 am"),
    ("timer minute minutes", "10 minute ka timer lagao"),
    ("remind reminder yaad dilana bhoolna", "remind me at 6 pm to drink water"),
    ("todo task tasks list karna kaam pending", "todo: buy milk"),
    ("photo photos pic pics gallery tasveer screenshot", "kal ki photos dikhao"),
    ("open app kholo chalao launch start", "open whatsapp"),
    ("battery charge storage space ram phone memory", "battery kitni hai"),
    ("plan day today aaj schedule agenda kya karun", "aaj ka plan kya hai"),
    ("routine morning workflow steps", "routine good morning: set an alarm for 7 am; open whatsapp"),
    ("note likho write save", "Note: buy milk"),
    ("pasand prefer like remember preference", "Yaad rakho mujhe subah kaam karna pasand hai"),
    ("calendar meeting kaam work project time nikalo slot", "kal project par 45 minutes kaam karne ka time nikalo"),
    ("daily roz har every subah morning", "har subah 8 baje mummy ko good morning message karo"),
    ("time date din baje samay", "what time is it"),
)


def _suggest(text):
    import difflib
    words = set(re.findall(r"\w+", (text or "").lower()))
    scored = []
    for keys, example in EXAMPLES:
        hits = len(words & set(keys.split()))
        ratio = difflib.SequenceMatcher(None, (text or "").lower(), example.lower()).ratio()
        if hits or ratio >= 0.5:
            scored.append((hits, ratio, example))
    scored.sort(reverse=True)
    picks = [e for _, _, e in scored[:3]] or ["call mummy", "send hi to neha on whatsapp", "aaj ka plan kya hai"]
    return " Try:\n" + "\n".join("- " + p for p in picks)


PRONOUN_RE = re.compile(r"\b(usko|unko|unhe|usse|unse|isko|inko|him|her|them|same person|wahi|whi|usi ko)\b", re.I)


def _clock12(h, m):
    return "%d:%02d %s" % (h % 12 or 12, m, "AM" if h < 12 else "PM")


def _duration_words(secs):
    h, rem = divmod(int(secs), 3600)
    m, s = divmod(rem, 60)
    parts = [("%d hour" % h) + ("s" if h != 1 else "")] if h else []
    parts += [("%d minute" % m) + ("s" if m != 1 else "")] if m else []
    parts += [("%d second" % s) + ("s" if s != 1 else "")] if s else []
    return " ".join(parts)


def daily_permissions_of(adapter, channel):
    fn = getattr(adapter, "missing_permissions", None)
    return list(fn(channel)) if fn else []


RANGE_LABEL = {"today": "today", "yesterday": "yesterday", "week": "last 7 days", "month": "last 30 days"}


def _norm_name(s):
    """'Neha  Office.' -> 'neha office' (case, spaces and punctuation ignored)."""
    return " ".join(re.findall(r"\w+", (s or "").lower()))


def _national(num):
    """Digits of a phone number without +91 / leading 0, for prefix matching."""
    d = re.sub(r"\D", "", num or "")
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    return d

APP_ALIASES = {"insta": "instagram", "ig": "instagram", "yt": "youtube", "fb": "facebook", "gpay": "google pay",
               "wa": "whatsapp", "whats app": "whatsapp", "watsapp": "whatsapp", "play store": "play store",
               "playstore": "play store", "dialer": "phone", "sms": "messages", "maps": "maps",
               "gmaps": "maps", "photos": "gallery", "photo": "gallery", "calculator": "calculator",
               "setting": "settings", "chrome": "chrome", "browser": "chrome"}


def _compact(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def match_apps(query, apps):
    """(matches, sure) for an app name. sure=False means several candidates: ask the user.
    Order: exact name -> name starts with it -> name contains it -> close spelling."""
    import difflib
    q = _compact(query)
    if not q:
        return [], True
    wanted = [q]
    alias = _compact(APP_ALIASES.get(query.strip().lower(), ""))
    if alias and alias != q:
        wanted.append(alias)
    by = [(a, _compact(a["label"])) for a in apps]
    for w in wanted:
        exact = [a for a, c in by if c == w]
        if exact:
            return exact, len(exact) == 1
    for w in wanted:
        starts = [a for a, c in by if c.startswith(w)]
        if starts:
            return starts, len(starts) == 1
    for w in wanted:
        if len(w) >= 3:
            inside = [a for a, c in by if w in c]
            if inside:
                return inside, len(inside) == 1
    close = difflib.get_close_matches(q, [c for _, c in by], n=3, cutoff=0.75)
    hits = [a for a, c in by if c in close]
    return hits, len(hits) <= 1


_ORDINALS = {1: "one first 1st ek pehla pehli pehle pahla", 2: "two second 2nd do dusra dusri dusre doosra",
             3: "three third 3rd teen teesra teesri tisra", 4: "four fourth 4th char chaar chautha chauthi",
             5: "five fifth 5th paanch panch paanchva"}
_ORD_WORD = {w: n for n, ws in _ORDINALS.items() for w in ws.split()}
_CHOICE_FILLER = set("number no option the wala wali wale ko call karo please plz one".split())


def _choice_number(text):
    """Answer to a 'which one?' list, typed or spoken: '2', 'two', 'second one', 'dusra wala'."""
    words = re.findall(r"\w+", text.lower())
    if not words or len(words) > 4:
        return None
    nums = [int(w) if w.isdigit() else _ORD_WORD.get(w) for w in words]
    hits = [n for n in nums if n]
    # 'one' is a filler in 'second one', but alone it means 1
    if len(hits) > 1 and 1 in hits and "one" in words:
        hits = [n for n, w in zip(nums, words) if n and w != "one"]
    rest = [w for w, n in zip(words, nums) if not n and w not in _CHOICE_FILLER]
    return hits[0] if len(hits) == 1 and not rest else None


TEMP_RE = re.compile(r"\b(aaj ke liye|sirf aaj|just for today|for today|abhi ke liye|temporarily)\b", re.I)
TOD = (("morning", r"\b(subah|morning)\b"), ("afternoon", r"\b(dopahar|afternoon)\b"),
       ("evening", r"\b(shaam|sham|evening)\b"))


@dataclass
class Response:
    # info | need_info | proposal | unsupported | error | choose | photos | need_permission
    kind: str
    text: str
    action_id: str = None
    action_hash: str = None
    options: list = None      # choose: labels to pick from
    items: list = None        # photos: [{id, label}]
    permissions: list = None  # need_permission: Android permission strings to request
    extra: str = None         # follow-up for the UI, e.g. "battery_exemption"


class Assistant:
    def __init__(self, store, backend, calendar, clock, contacts=None, phone=None, photos=None, apps=None,
                 daily=None, messages=None, alarms=None, device=None):
        self.store, self.backend, self.calendar, self.clock = store, backend, calendar, clock
        self.contacts = contacts or UnsupportedAdapter("contacts")
        self.phone = phone or UnsupportedAdapter("phone_call")
        self.photos = photos or UnsupportedAdapter("photos")
        self.apps = apps or UnsupportedAdapter("apps")
        self.daily = daily or UnsupportedAdapter("daily_message")
        self.messages = messages or UnsupportedAdapter("sms_message")
        self.alarms = alarms or UnsupportedAdapter("alarms")
        self.device = device or UnsupportedAdapter("device_info")
        self._last_contact = None  # (name, number) of the last call/message, for "usko call karo"
        self._todo_view = []       # to-do ids in the order last shown (for "todo 2 done")
        self.adapters = {
            "calendar_event": calendar,
            "phone_call": self.phone,
            "daily_message": self.daily,
            "sms_message": self.messages,
            "settings": UnsupportedAdapter("settings"),
            "files": UnsupportedAdapter("files"),
        }
        self.engine = ApprovalEngine(store, self.adapters)
        self._pending = None  # schedule request waiting for a missing detail
        self._choices = None  # latest 'which one?' list: {"kind": call|app|daily_channel|daily_contact, ...}
        self._pending_msg = None  # message waiting for its missing person or text
        self._awaiting_send = None  # name whose WhatsApp auto-send result is still to be reported
        self._pending_alarm = None  # (intent, entities) waiting for a time / length
        self._photo_ids = set()  # only photos from the last search may be opened

    # ---------- main entry ----------
    def handle(self, text):
        text = (text or "").strip()[:config.MAX_INPUT_CHARS]
        if not text:
            return Response("error", "Please type something.")
        now = self.clock()
        pick = _choice_number(text) if self._choices else None
        if self._choices and not pick:
            low = text.lower().strip(" .!")
            if len(self._choices["items"]) == 1 and re.fullmatch(
                    r"(yes|yeah|yep|haan|han|ha|haa|hanji|ok|okay|sure|y|kar do|karo|call karo|bhej do)", low):
                pick = 1
            elif re.fullmatch(r"(no|nahi|nahin|na|cancel|mat karo|rehne do|chhodo|stop)", low):
                self._choices = None
                return Response("info", "Okay, nothing was done.")
        if self._choices and self._choices["kind"] in ("daily_channel", "msg_channel"):
            low = text.lower()
            pick = 1 if re.search(r"\bsms\b", low) else 2 if re.search(r"\b(what'?s\s?app|wh?ats?app)\b", low) else pick
        if pick:
            return self.choose_contact(pick - 1)
        self._choices = None
        if self._pending_alarm is not None:
            # "set an alarm" -> "What time?" -> "5 am"
            pend, self._pending_alarm = self._pending_alarm, None
            # Only a bare answer ("5 am", "10 minutes") counts. A full new command that happens to
            # contain a number is NOT an answer (phone test: "set a timer" then "kal project par 30
            # minutes kaam ..." started a real 30-minute timer).
            own = validate(self.backend.parse(text, now.date()), now.date()).intent
            if re.search(r"\d", text) and own in ("unknown", pend[0]):
                if pend[0] == "set_timer":  # read the answer as what was asked: a length
                    again = validate(self.backend.parse("timer " + text, now.date()), now.date())
                    if again.entities.get("seconds"):
                        return self._alarm("set_timer", again.entities)
                else:                       # ... or a time of day
                    again = validate(self.backend.parse("alarm " + text, now.date()), now.date())
                    if again.intent == "set_alarm" and again.entities.get("time"):
                        return self._alarm("set_alarm", dict(pend[1], **again.entities))
        if self._pending_msg is not None:
            # The previous reply asked "who?" or "what should it say?": a reply that is not a new
            # command answers that question ("hii" -> the message text).
            pend, self._pending_msg = self._pending_msg, None
            if validate(self.backend.parse(text, now.date()), now.date()).intent == "unknown":
                answer = text.strip(" .!")
                if pend["need"] == "name":
                    answer = re.sub(r"^(?:to|ko)\s+|\s+(?:ko)$", "", answer, flags=re.I)
                    key = "number" if re.fullmatch(r"\+?[\d \-]{7,}", answer) else "name"
                    return self._send(dict(pend["ent"], **{key: answer.lower() if key == "name" else answer}))
                return self._send(dict(pend["ent"], text=answer))
        if self._pending is not None and hasattr(self.backend, "followup"):
            extra = self.backend.followup(text)
            if extra:
                ent = dict(self._pending, **extra)
                self._pending = None
                return self._schedule(ent, now)
            self._pending = None
        # a routine can be started by just saying its name ("good morning")
        rname = " ".join(re.findall(r"\w+", text.lower()))
        if rname and rname in self._routines():
            return self._run_routine(rname)
        parts = self._compound_parts(text, now.date())
        if parts:
            return self._run_steps(parts)
        it = validate(self.backend.parse(text, now.date()), now.date())
        n = it.intent
        # context: "usko call karo" / "send her hi" = the person from the last call or message.
        # A guess from context is never acted on directly: the user confirms it first (phone
        # test: a pronoun call went straight out to the wrong, earlier number).
        if (n in ("call_contact", "send_message", "schedule_message") and self._last_contact
                and not (it.entities.get("name") or it.entities.get("number") or it.entities.get("name_text"))
                and PRONOUN_RE.search(text)):
            name, number = self._last_contact
            if n == "call_contact":
                wa = it.entities.get("via") == "whatsapp"
                self._choices = {"kind": "wa_call" if wa else "call", "items": [{"name": name, "number": number}],
                                 "sim": None, "video": bool(it.entities.get("video"))}
                return Response("choose", "%s %s (%s) again? Say 1 or yes." % (
                    "WhatsApp-call" if wa else "Call", name, number), options=["1. %s (%s)" % (name, number)])
            it.entities["number"], it.entities["display"] = number, name
            it.entities["confirm"] = True
            it.missing_fields = [f for f in it.missing_fields if f != "name"]
        if n == "auto_send":
            return self.auto_send_status()
        if n == "device_info":
            return self._info(it.entities.get("category"))
        if n == "add_todo":
            return self._add_todo(it.entities)
        if n == "list_todos":
            return self._list_todos()
        if n == "done_todo":
            return self._done_todo(it.entities)
        if n == "plan_day":
            return self._plan(it.entities.get("day", "today"))
        if n == "create_routine":
            return self._create_routine(it.entities)
        if n == "run_routine":
            return self._run_routine(it.entities.get("name", ""))
        if n == "list_routines":
            rs = self.list_routines()
            return Response("info", "Your routines:\n" + "\n".join(
                "- %s (%d step%s)" % (r["name"], len(r["steps"]), "" if len(r["steps"]) == 1 else "s")
                for r in rs) if rs else
                "No routines yet. Example: routine good morning: set an alarm for 7 am; open whatsapp")
        if n == "delete_routine":
            r = self._routines().get(it.entities.get("name", "").strip().lower())
            if not r:
                return Response("info", "No routine called '%s'." % it.entities.get("name", ""))
            self.delete_routine(r["id"])
            return Response("info", "Deleted routine '%s'." % r["name"])
        if n == "schedule_routine":
            return self._schedule_routine(it.entities)
        if n == "unschedule_routine":
            return self._unschedule_routine(it.entities.get("name", ""))
        if n == "remember_preference":
            return self._remember(it)
        if n == "add_note":
            return self._note(it)
        if n == "query_notes":
            return self._query(it)
        if n == "schedule_work":
            return self._schedule(it.entities, now, it.missing_fields)
        if n == "call_contact":
            return self._call(it)
        if n == "find_photos":
            return self._find_photos(it, now)
        if n == "open_app":
            return self._open_app(it)
        if n == "schedule_message":
            return self._daily(it.entities)
        if n == "send_message":
            return self._send(it.entities)
        if n in ("set_alarm", "set_timer", "show_alarms"):
            return self._alarm(n, it.entities)
        if n in UNSUPPORTED:
            return Response("unsupported", "This is not supported yet (%s): no adapter is implemented." % n)
        return Response("info", "Sorry, I did not understand that." + _suggest(text))

    # ---------- memory ----------
    def _remember(self, it):
        if it.missing_fields:
            return Response("need_info", "What should I remember?")
        text = it.entities["text"]
        if TEMP_RE.search(text):
            return Response("info", "This sounds temporary, so I did not save it as a permanent preference.")
        tags = {}
        for tag, rx in TOD:
            if re.search(rx, text, re.I):
                tags["time_of_day"] = tag
        self.store.put("pref", {"text": text, "tags": tags}, vector_text=text)
        self.store.audit("-", "save_preference", "n/a", "done")
        return Response("info", "Preference saved: %s" % text)

    def _note(self, it):
        if it.missing_fields:
            return Response("need_info", "What should the note say?")
        self.store.put("note", {"text": it.entities["text"]}, vector_text=it.entities["text"])
        self.store.audit("-", "save_note", "n/a", "done")
        return Response("info", "Note saved.")

    def _query(self, it):
        q = it.entities.get("query", "")
        hits = self.store.search("note", q, config.RETRIEVE_K, config.RETRIEVE_MIN_SCORE)
        if not hits:
            return Response("info", "No matching note found.")
        # retrieved text is shown as data only; it is never parsed as an instruction
        lines = ["- " + h["text"][:config.SNIPPET_CHARS] for _, h in hits]
        return Response("info", "Your notes:\n" + "\n".join(lines))

    # ---------- scheduling ----------
    def _schedule(self, ent, now, missing=None):
        missing = missing if missing is not None else [f for f in ("title", "duration_minutes", "date") if f not in ent]
        if missing:
            self._pending = dict(ent)
            return Response("need_info", "I need these details: " + ", ".join(missing))
        prefs = self.store.all("pref")
        win = planner.resolve_window(ent, prefs)
        if win is None:
            self._pending = dict(ent)
            return Response("need_info", "What time do you want to work? (morning / afternoon / evening or HH:MM)")
        day = date.fromisoformat(ent["date"])
        busy = self.calendar.busy(day, now.tzinfo)
        known = busy is not None
        busy = list(busy or [])
        for t in self.store.all("task"):  # already-planned in-app tasks count as busy
            try:
                s, e = datetime.fromisoformat(t["start_iso"]), datetime.fromisoformat(t["end_iso"])
                if s.date() == day:
                    busy.append((s, e))
            except (KeyError, ValueError):
                pass
        res = planner.propose_slot(day, ent["duration_minutes"], None if win == "fixed" else win,
                                   ent.get("time") if win == "fixed" else None, busy, now)
        if not res["ok"]:
            return Response("info", "No free slot found: " + res["reason"])
        payload = {"title": ent["title"], "start_iso": res["start"].isoformat(), "end_iso": res["end"].isoformat()}
        try:
            action, preview = self.engine.propose("calendar_event", payload)
        except Unsupported:
            return Response("unsupported", "Calendar is not available on this device.")
        except ValueError as ex:
            return Response("error", "Invalid plan: %s" % ex)
        note = "" if known else "\n(Note: could not check calendar availability; only checked overlap with in-app tasks.)"
        return Response("proposal", "Proposal: " + preview + note + "\nApprove?",
                        action.id, action.hash)

    # ---------- calls ----------
    # User's choice: call immediately (no Approve tap) when the target is unambiguous.
    # Still asks when: several contacts match, the named SIM is not in the phone, or a
    # permission is missing. Audit records that no approval was required, never who/which number.
    # ---------- WhatsApp calls ----------
    # Same rules as phone calls (user's choice: no Approve tap when exactly one contact matches);
    # the call is started through WhatsApp's own contact entry, not by pressing buttons.
    def _wa_call(self, ent):
        if not ent.get("name") and not ent.get("number"):
            return Response("need_info", "Who should I call on WhatsApp?")
        if not hasattr(self.messages, "whatsapp_call") or not self.messages.capability_check():
            return Response("unsupported", "WhatsApp calls are not available on this device.")
        if self.contacts.permission_check() == "denied":
            return Response("need_permission", "WhatsApp calls need permission to read contacts. Allow it and say "
                            "the same thing again.", permissions=[READ_CONTACTS])
        video = bool(ent.get("video"))
        if ent.get("number"):
            return self._wa_call_go(ent.get("display") or ent["number"], ent["number"], video)
        try:
            matches, exact = self._match_contacts(ent["name"], ent.get("prefix"))
        except Exception as ex:
            return Response("error", "Could not read contacts: %s" % type(ex).__name__)
        if not matches:
            return Response("info", "No contact found for '%s'. No call was made." % ent["name"])
        if len(matches) == 1 and exact:
            return self._wa_call_go(matches[0]["name"], matches[0]["number"], video)
        self._choices = {"kind": "wa_call", "items": matches[:5], "sim": None, "video": video}
        return Response("choose", "Whom should I call on WhatsApp?",
                        options=["%d. %s (%s)" % (i + 1, m["name"], m["number"]) for i, m in enumerate(matches[:5])])

    def _wa_call_go(self, name, number, video):
        kind = "video" if video else "voice"
        r = self.messages.whatsapp_call(number, video)
        self.store.audit("-", "whatsapp_call", "not_required:user_setting_direct_call", r.status)
        if r.status == "done":
            self._last_contact = (name, number)
            return Response("info", "Starting a WhatsApp %s call with %s." % (kind, name))
        if r.detail == "not_on_whatsapp":
            o = self.messages.open_whatsapp(number, "")
            if o.status == "handed_off":
                self._last_contact = (name, number)
                return Response("info", "WhatsApp has no call entry for %s (not on WhatsApp, or not synced yet). "
                                        "Opened the chat: tap the %s call button." % (name, kind))
            return Response("error", "%s does not seem to be on WhatsApp. No call was made." % name)
        return Response("error", "Could not start the WhatsApp call: %s. No call was made." % r.detail)

    def _call(self, it):
        if it.entities.get("via") == "whatsapp":
            return self._wa_call(it.entities)
        if it.missing_fields:
            return Response("need_info", "Who should I call? Type a name or number.")
        if not self.phone.capability_check():
            return Response("unsupported", "Calling is not available on this device.")
        if not it.entities.get("number") and not self.contacts.capability_check():
            return Response("unsupported", "Contacts are not available on this device. Please say the number instead.")
        need = self._call_permissions_missing(it.entities)
        if need:
            return Response("need_permission",
                            "Direct calls need Contacts, Phone and SIM permissions. "
                            "Please allow them and try again.", permissions=need)
        sim = self._resolve_sim(it.entities.get("sim"))
        if isinstance(sim, Response):
            return sim
        if it.entities.get("number"):
            return self._direct_call(it.entities.get("display") or it.entities["number"], it.entities["number"], sim)
        name, prefix = it.entities["name"], it.entities.get("prefix")
        try:
            matches, exact = self._match_contacts(name, prefix)
        except Exception as ex:
            return Response("error", "Could not read contacts: %s" % type(ex).__name__)
        self.store.audit("-", "contact_lookup", "n/a", "done", "matches=%d" % len(matches))
        who = "'%s'%s" % (name, (" (number starting %s...)" % prefix) if prefix else "")
        if not matches:
            return Response("info", "No contact found for %s. No call was made." % who)
        if len(matches) == 1 and exact:
            return self._direct_call(matches[0]["name"], matches[0]["number"], sim)
        self._choices = {"kind": "call", "items": matches[:5], "sim": sim}
        labels = ["%d. %s (%s)" % (i + 1, m["name"], m["number"]) for i, m in enumerate(matches[:5])]
        if not exact:
            return Response("choose", "No contact is named exactly %s. These are similar. "
                            "Who should I call?" % who, options=labels)
        hint = "" if prefix else " (Tip: you can also say the first 4 digits of the number.)"
        return Response("choose", "Found %s: %d contacts. Who should I call?%s" % (who, len(matches), hint),
                        options=labels)

    def _match_contacts(self, name, prefix):
        """Full name first. If that finds nothing (e.g. the sentence left an extra word like
        'neha whose'), try each word alone, longest first, and keep the first word that
        matches. Words under 3 letters are skipped so 'me'/'ji' never match everyone."""
        def find(q):
            ms = self.contacts.search(q)
            if prefix:
                ms = [m for m in ms if _national(m["number"]).startswith(prefix)]
            return ms
        matches = find(name)
        # Say exactly as much name as you mean: "neha" -> only the contact named exactly
        # "Neha", not "Neha 2" / "Neha Office". Longer names are only offered when no
        # contact has exactly the spoken name.
        exact = [m for m in matches if _norm_name(m["name"]) == _norm_name(name)]
        if exact:
            return exact, True
        words = name.split()
        if matches or len(words) < 2:
            return matches, True
        for w in sorted({w for w in words if len(w) >= 3}, key=len, reverse=True):
            matches = find(w)
            if matches:
                return matches, False  # partial match: caller must ask, never dial directly
        return [], True

    def _call_permissions_missing(self, ent):
        missing = []
        if not ent.get("number") and self.contacts.permission_check() == "denied":
            missing += self.contacts.required_permissions()
        if not self.phone.can_call_directly() or (ent.get("sim") and self.phone.sims() is None):
            missing += self.phone.required_permissions()
        return list(dict.fromkeys(missing))

    def _resolve_sim(self, want):
        """None (phone default), a (slot, label) tuple, or a Response explaining the problem."""
        if not want:
            return None
        sims = self.phone.sims() or []
        if want in ("1", "2"):
            hit = [s for s in sims if s["slot"] == int(want)]
        else:
            hit = [s for s in sims if any(want in n for n in (s.get("names") or []) + [s["label"].lower()])]
        if len(hit) == 1:
            return hit[0]["slot"], hit[0]["label"]
        have = ", ".join("SIM %d (%s)" % (s["slot"], s["label"]) for s in sims) or "none"
        return Response("error", "Could not find the SIM '%s'. SIMs in this phone: %s. No call was made."
                        % (want, have))

    # ---------- apps ----------
    def _open_app(self, it):
        if it.missing_fields:
            return Response("need_info", "Which app should I open?")
        if not self.apps.capability_check():
            return Response("unsupported", "Opening apps is not available on this device.")
        name = it.entities["app"]
        try:
            apps = self.apps.list_apps()
        except Exception as ex:
            return Response("error", "Could not read the app list: %s" % type(ex).__name__)
        matches, sure = match_apps(name, apps)
        if not matches:
            return Response("info", "No app called '%s' found on this phone." % name)
        if sure:
            return self._launch(matches[0])
        self._choices = {"kind": "app", "items": matches[:5]}
        return Response("choose", "Found %d apps for '%s'. Which one should I open?" % (len(matches), name),
                        options=["%d. %s" % (i + 1, a["label"]) for i, a in enumerate(matches[:5])])

    def _launch(self, app):
        r = self.apps.open(app["package"])
        self.store.audit("-", "open_app", "not_required:read_only", r.status)
        if r.status == "handed_off":
            return Response("info", "Opening %s." % app["label"])
        return Response("error", "Could not open %s: %s" % (app["label"], r.detail))

    def choose_contact(self, index):
        """Answer to the latest 'which one?' list: a contact to call, an app, or a daily-message
        detail (SMS/WhatsApp, which contact). Lists are single-use."""
        c, self._choices = self._choices, None
        if not c or not 0 <= index < len(c["items"]):
            return Response("error", "This option is no longer valid. Please ask again.")
        item = c["items"][index]
        if c["kind"] == "app":
            return self._launch(item)
        if c["kind"] == "daily_channel":
            return self._daily(dict(c["ent"], channel=item))
        if c["kind"] == "daily_contact":
            return self._daily_propose(c["ent"], item["name"], item["number"])
        if c["kind"] == "msg_channel":
            return self._send(dict(c["ent"], channel=item))
        if c["kind"] == "msg_contact":
            return self._send_to(c["ent"], item["name"], item["number"], c["sim"])
        if c["kind"] == "wa_call":
            return self._wa_call_go(item["name"], item["number"], c.get("video"))
        return self._direct_call(item["name"], item["number"], c["sim"])

    # ---------- message now ----------
    # WhatsApp: the chat opens with the text typed, the user presses Send (no approval needed:
    # WhatsApp itself is the confirmation). SMS: approval card first, it cannot be taken back.
    # ---------- phone status (ported from PokeClaw's GetDeviceInfoTool, Apache-2.0) ----------
    def _info(self, cat):
        now = self.clock()
        if cat == "time":
            return Response("info", "It is %s, %s." % (_clock12(now.hour, now.minute), now.strftime("%A %d %B %Y")))
        if not self.device.capability_check():
            return Response("unsupported", "Phone status is not available on this device.")
        try:
            d = self.device.get(cat)
        except Exception as ex:
            return Response("error", "Could not read the %s: %s" % (cat, type(ex).__name__))
        if cat == "battery":
            msg = "Battery: %d%%, %s" % (d["level"], "charging" if d["charging"] else "not charging")
            if d.get("temp_c"):
                msg += ", %.1f°C" % d["temp_c"]
            msg += "."
            if d["level"] <= 20 and not d["charging"]:
                msg += " Battery is low: charge the phone soon."
            elif d.get("temp_c") and d["temp_c"] >= 42:
                msg += " The battery is hot: let it cool down."
            return Response("info", msg)
        if cat == "storage":
            msg = "Storage: %s free of %s (%d%% used)." % (_bytes(d["free"]), _bytes(d["total"]), d["used_pct"])
            if d["used_pct"] >= 90:
                msg += " Storage is almost full: delete old videos or apps you do not use."
            return Response("info", msg)
        if cat == "memory":
            return Response("info", "RAM: %s free of %s%s." % (_bytes(d["free"]), _bytes(d["total"]),
                                                                ", running low" if d["low"] else ""))
        if cat == "device":
            return Response("info", "%s %s, Android %s (API %d)%s." % (
                d["maker"].capitalize(), d["model"], d["android"], d["api"],
                (", security patch " + d["patch"]) if d["patch"] else ""))
        if cat == "screen":
            parts = []
            if d["brightness_pct"] is not None:
                parts.append("brightness %d%%%s" % (d["brightness_pct"], " (auto)" if d["auto"] else ""))
            parts.append("dark mode %s" % ("on" if d["dark"] else "off"))
            return Response("info", "Screen: " + ", ".join(parts) + ".")
        if cat == "network":
            if not d["online"]:
                return Response("info", "No internet right now. (This assistant works fully offline.)")
            return Response("info", "Online via %s." % d["type"])
        if cat == "alarm":
            if not d["next_ms"]:
                return Response("info", "No alarm is set.")
            at = datetime.fromtimestamp(d["next_ms"] / 1000, now.tzinfo)
            return Response("info", "Next alarm: %s %s." % (_day_word(at.date(), now.date()), _clock12(at.hour, at.minute)))
        return Response("error", "Unknown status: %s" % cat)

    # ---------- to-dos and reminders (to-do shape from PokeClaw's kb_add_todo, Apache-2.0) ----------
    PRIO_RANK = {"high": 0, "medium": 1, "low": 2}

    def _open_todos(self, today):
        """Open to-dos, most urgent first: overdue, due today, then by priority and date."""
        def key(t):
            due = t.get("due")
            bucket = 0 if due and due < today.isoformat() else 1 if due == today.isoformat() else 2
            return (bucket, self.PRIO_RANK.get(t.get("priority"), 1), due or "9999", t.get("time") or "99")
        return sorted([t for t in self.store.all("todo") if not t.get("done")], key=key)

    def _todo_label(self, t, today):
        bits = []
        if t.get("priority") == "high":
            bits.append("high")
        if t.get("due"):
            d = date.fromisoformat(t["due"])
            bits.append(("overdue since " if d < today else "") + _day_word(d, today)
                        + (" " + _clock12(*map(int, t["time"].split(":"))) if t.get("time") else ""))
        return t["text"] + (" (%s)" % ", ".join(bits) if bits else "")

    def _add_todo(self, ent):
        if not ent.get("text"):
            return Response("need_info", "What should I remind you about? Example: remind me at 6 pm to drink water")
        now = self.clock()
        rec = {"text": ent["text"], "due": ent.get("due"), "time": ent.get("time"),
               "priority": ent.get("priority") or "medium", "done": False, "reminder_id": None}
        at = None
        if rec["time"]:
            h, m = map(int, rec["time"].split(":"))
            at = datetime.combine(date.fromisoformat(rec["due"]), datetime.min.time(), now.tzinfo).replace(hour=h, minute=m)
            if at <= now:
                if rec["due"] != now.date().isoformat():
                    return Response("error", "That time has already passed. Nothing was added.")
                at += timedelta(days=1)  # "remind me at 6 pm" said after 6 pm -> tomorrow
                rec["due"] = at.date().isoformat()
            if not self.daily.capability_check():
                return Response("unsupported", "Reminders are not available on this device.")
            need = daily_permissions_of(self.daily, "whatsapp")  # notification permission
            if need:
                return Response("need_permission", "Reminders need permission to show notifications. Allow it "
                                "and say the same thing again.", permissions=need)
            rid = secrets.randbelow(2 ** 31 - 2) + 1
            r = self.daily.set_reminder(rid, rec["text"], int(at.timestamp() * 1000))
            if r.status != "done":
                return Response("error", "Could not set the reminder: %s" % r.detail)
            rec["reminder_id"] = rid
        self.store.put("todo", rec)
        self.store.audit("-", "add_todo", "not_required:local_only", "done", "reminder=%s" % bool(at))
        if at:
            return self._with_battery_check(Response("info", "Reminder set for %s %s: %s" % (
                _day_word(at.date(), now.date()), _clock12(at.hour, at.minute), rec["text"])))
        extra = "" if not ent.get("remind") else " Say a time to get a notification, e.g. 'remind me at 6 pm to %s'." % rec["text"]
        return Response("info", "Added to your to-do list: %s.%s" % (self._todo_label(rec, now.date()), extra))

    def _list_todos(self):
        today = self.clock().date()
        todos = self._open_todos(today)
        self._todo_view = [t["id"] for t in todos]
        if not todos:
            return Response("info", "Your to-do list is empty.")
        return Response("info", "Your to-dos:\n" + "\n".join(
            "%d. %s" % (i + 1, self._todo_label(t, today)) for i, t in enumerate(todos[:20])))

    def _done_todo(self, ent):
        today = self.clock().date()
        todos = self._open_todos(today)
        if ent.get("index"):
            ids = self._todo_view or [t["id"] for t in todos]
            pick = [t for t in todos if ids and ent["index"] <= len(ids) and t["id"] == ids[ent["index"] - 1]]
        elif ent.get("text"):
            import difflib
            want = ent["text"].lower()
            pick = [t for t in todos if want in t["text"].lower() or t["text"].lower() in want] or [
                t for t in todos if difflib.SequenceMatcher(None, want, t["text"].lower()).ratio() >= 0.6]
        else:
            return Response("need_info", "Which to-do is done? Say its number from 'show my todos'.")
        if len(pick) != 1:
            return Response("info", "No open to-do matches that." if not pick else
                            "Several to-dos match. Say its number from 'show my todos'.")
        return self._finish_todo(pick[0])

    def mark_todo_done(self, rid):
        t = next((x for x in self.store.all("todo") if x["id"] == rid and not x.get("done")), None)
        return self._finish_todo(t) if t else Response("info", "That to-do is already done.")

    def _finish_todo(self, t):
        if t.get("reminder_id"):
            try:
                self.daily.cancel(t["reminder_id"])
            except Exception:
                pass
        self.store.update(t["id"], dict({k: v for k, v in t.items() if k not in ("id", "created_at")}, done=True))
        return Response("info", "Done: %s" % t["text"])

    def delete_todo(self, rid):
        t = next((x for x in self.store.all("todo") if x["id"] == rid), None)
        if t and t.get("reminder_id") and self.daily.capability_check():
            try:
                self.daily.cancel(t["reminder_id"])
            except Exception:
                pass
        return self.store.delete(rid)

    def list_todos(self):
        return self._open_todos(self.clock().date())

    # ---------- decision support: the day's plan ----------
    def _plan(self, which):
        now = self.clock()
        today = now.date()
        day = today + timedelta(days=1 if which == "tomorrow" else 0)
        lines = ["Plan for %s (%s):" % (which, day.strftime("%A %d %b"))]
        busy = []
        cal = self.calendar.busy(day, now.tzinfo) if self.calendar else None
        for s, e in (cal or []):
            busy.append((s, e))
            lines.append("- %s-%s busy (calendar)" % (s.strftime("%H:%M"), e.strftime("%H:%M")))
        for t in self.store.all("task"):
            try:
                s, e = datetime.fromisoformat(t["start_iso"]), datetime.fromisoformat(t["end_iso"])
            except (KeyError, ValueError):
                continue
            if s.date() == day:
                busy.append((s, e))
                lines.append("- %s-%s %s" % (s.strftime("%H:%M"), e.strftime("%H:%M"), t["title"]))
        cal_day = (day.weekday() + 1) % 7 + 1  # Calendar numbering: 1=Sunday .. 7=Saturday
        for sch in sorted(self.store.all("schedule"), key=lambda x: x.get("time", "")):
            if which == "today" and sch.get("time", "") < now.strftime("%H:%M"):
                continue
            if sch.get("days") and cal_day not in sch["days"]:
                continue  # weekly message, not on this day
            lines.append("- %s daily %s to %s" % (sch["time"], "SMS" if sch["channel"] == "sms" else "WhatsApp",
                                                   sch["name"]))
        todos = self._open_todos(today)
        due_day = [t for t in todos if t.get("due") == day.isoformat()]
        overdue = [t for t in todos if t.get("due") and t["due"] < today.isoformat()]
        floating = [t for t in todos if not t.get("due") and t.get("priority") == "high"]
        for t in sorted(due_day, key=lambda x: x.get("time") or "99"):
            passed = which == "today" and t.get("time") and t["time"] < now.strftime("%H:%M")
            lines.append("- %s%s%s" % ((t["time"] + " ") if t.get("time") else "", t["text"],
                                       (" (high)" if t.get("priority") == "high" else "")
                                       + (" (passed)" if passed else "")))
        if which == "today":
            for t in overdue:
                lines.append("- overdue: %s" % t["text"])
        if self.device.capability_check():
            try:
                nxt = self.device.get("alarm").get("next_ms")
                if nxt:
                    at = datetime.fromtimestamp(nxt / 1000, now.tzinfo)
                    if at.date() == day:
                        lines.append("- alarm at %s" % _clock12(at.hour, at.minute))
                if which == "today":
                    b = self.device.get("battery")
                    if b["level"] <= 30 and not b["charging"]:
                        lines.append("- battery is %d%%: charge the phone" % b["level"])
            except Exception:
                pass
        if len(lines) == 1:
            lines.append("- nothing planned yet")
        # Suggestion: the most urgent to-do without a fixed time goes into the first free 30 minutes.
        cand = [t for t in (overdue + due_day + floating) if not t.get("time")] if which == "today" else \
            [t for t in (due_day + floating) if not t.get("time")]
        if cand:
            top = sorted(cand, key=lambda t: (self.PRIO_RANK.get(t.get("priority"), 1), t.get("due") or "9999"))[0]
            pref = planner.resolve_window({}, self.store.all("pref"))
            for win in ([pref] if pref else []) + [w for w in ("morning", "afternoon", "evening") if w != pref]:
                res = planner.propose_slot(day, 30, win, None, busy, now)
                if res["ok"]:
                    lines.append("Suggestion: do '%s' at %s-%s (first free 30 minutes%s)." % (
                        top["text"], res["start"].strftime("%H:%M"), res["end"].strftime("%H:%M"),
                        ", your preferred %s" % win if win == pref else ""))
                    break
            else:
                lines.append("Suggestion: no free 30 minutes left %s for '%s'; move it to another day." % (
                    which, top["text"]))
        if cal is None:
            lines.append("(Calendar not checked: no permission.)")
        return Response("info", "\n".join(lines))

    # ---------- routines (PokeClaw "skills" idea: a named recipe of steps, no model) ----------
    def _routines(self):
        return {r["name"]: r for r in self.store.all("routine")}

    def _create_routine(self, ent):
        name, steps = ent.get("name", "").strip().lower(), ent.get("steps") or []
        if not name or not steps:
            return Response("need_info", "Example: routine good morning: set an alarm for 7 am; battery kitni hai; "
                                         "open whatsapp")
        today = self.clock().date()
        bad = [s for s in steps if validate(self.backend.parse(s, today), today).intent in
               ("unknown", "create_routine", "run_routine", "delete_routine", "list_routines")]
        if bad:
            return Response("error", "I do not understand these steps, so the routine was not saved: "
                            + "; ".join(bad))
        old = self._routines().get(name)
        if old:
            self.store.delete(old["id"])
        self.store.put("routine", {"name": name, "steps": steps})
        return Response("info", "Saved routine '%s' (%d step%s):\n%s\nSay '%s routine' or just '%s' to run it. "
                        "To run it at a time: '%s routine har din 7 baje'." % (
                            name, len(steps), "" if len(steps) == 1 else "s",
                            "\n".join("%d. %s" % (i + 1, s) for i, s in enumerate(steps)), name, name, name))

    def _run_routine(self, name):
        r = self._routines().get(name.strip().lower())
        if not r:
            have = ", ".join(sorted(self._routines())) or "none yet"
            return Response("info", "No routine called '%s'. Your routines: %s." % (name, have))
        self.store.audit("-", "run_routine", "not_required:user_created_routine", "started", "steps=%d" % len(r["steps"]))
        return self._run_steps(r["steps"], "Routine '%s'" % r["name"])

    def list_routines(self):
        return self.store.all("routine")

    def delete_routine(self, rid):
        r = next((x for x in self.store.all("routine") if x["id"] == rid), None)
        if r and r.get("trigger") and self.daily.capability_check():
            try:
                self.daily.cancel(r["trigger"]["sched_id"])  # stop its timed notification too
            except Exception:
                pass
        return self.store.delete(rid)

    def _schedule_routine(self, ent):
        r = self._routines().get(ent.get("name", "").strip().lower())
        if not r:
            have = ", ".join(sorted(self._routines())) or "none yet"
            return Response("info", "No routine called '%s'. Your routines: %s." % (ent.get("name", ""), have))
        if not self.daily.capability_check():
            return Response("unsupported", "Timed routines are not available on this device.")
        need = daily_permissions_of(self.daily, "whatsapp")  # notification permission
        if need:
            return Response("need_permission", "Timed routines need permission to show notifications. Allow it "
                            "and say the same thing again.", permissions=need)
        days = ent.get("days") if ent.get("days") and len(ent["days"]) < 7 else None
        sid = secrets.randbelow(2 ** 31 - 2) + 1
        res = self.daily.set_routine_trigger(sid, r["name"], ent["time"], days)
        if res.status != "done":
            return Response("error", "Could not schedule the routine: %s" % res.detail)
        if r.get("trigger"):
            try:
                self.daily.cancel(r["trigger"]["sched_id"])  # replace the old time
            except Exception:
                pass
        rec = {k: v for k, v in r.items() if k not in ("id", "created_at")}
        rec["trigger"] = {"sched_id": sid, "time": ent["time"], "days": days}
        self.store.update(r["id"], rec)
        return self._with_battery_check(Response(
            "info", "Every %s at %s you will get a notification 'Routine: %s'. Tap it and the routine runs."
            % (days_text(days), ent["time"], r["name"])))

    def _with_battery_check(self, res):
        """Timed features need the phone to leave the app alone in the background (vivo removed a
        routine's next alarm when it froze the app: dumpsys alarm 'Reason=frozen')."""
        if self.daily_battery_ok():
            return res
        return Response(res.kind, res.text + "\nImportant: allow Lazey to run in the background on the "
                        "next screen, or your phone may cancel it.", extra="battery_exemption")

    def _unschedule_routine(self, name):
        r = self._routines().get(name.strip().lower())
        if not r or not r.get("trigger"):
            return Response("info", "Routine '%s' has no set time." % name)
        try:
            self.daily.cancel(r["trigger"]["sched_id"])
        except Exception:
            pass
        rec = {k: v for k, v in r.items() if k not in ("id", "created_at", "trigger")}
        self.store.update(r["id"], rec)
        return Response("info", "Routine '%s' will no longer run at a set time (you can still say it)." % r["name"])

    # ---------- several commands in one line / a routine ----------
    LEAVES_APP = ("Opening", "Calling", "Dialer", "Sending on WhatsApp")

    def _compound_parts(self, text, today):
        """'set an alarm for 6 and open whatsapp' -> 2 parts, only if every part is a command."""
        if re.match(r"^\s*(note|remember|yaad rakho|routine|create routine|make routine)\b", text, re.I):
            return None
        parts = [p.strip(" ,.") for p in re.split(
            r"\s*;\s*|\s+(?:and then|then|aur phir|phir|uske baad|after that|and|aur)\s+", text, flags=re.I)]
        parts = [p for p in parts if p]
        if len(parts) < 2:
            return None
        parsed = [validate(self.backend.parse(p, today), today) for p in parts]
        intents = [p.intent for p in parsed]
        # "open whatsapp and send neha a message hi" is ONE command (the message opens WhatsApp itself)
        if (len(parts) == 2 and intents == ["open_app", "send_message"]
                and re.search(r"what'?s\s?app|whatsapp", parts[0], re.I)):
            return None
        return parts if all(i not in ("unknown", "create_routine") for i in intents) else None

    def _run_steps(self, steps, title=None):
        out, left_app, skipped = [], False, []
        today = self.clock().date()
        for i, step in enumerate(steps):
            intent = validate(self.backend.parse(step, today), today).intent
            if left_app and intent in ("open_app", "call_contact", "send_message", "show_alarms", "find_photos"):
                skipped.append(step)  # another app is already open; opening one more would cut it off
                continue
            r = self.handle(step)
            out.append("%d. %s" % (i + 1, r.text))
            if r.text.startswith(self.LEAVES_APP) or r.extra in ("await_auto_send", "auto_send_setup"):
                left_app = True
            if r.kind in ("choose", "proposal", "need_info", "need_permission", "photos"):
                rest = steps[i + 1:]
                if rest:
                    out.append("(Stopped here. Not run yet: %s)" % "; ".join(rest))
                head = (title + ":\n") if title else ""
                return Response(r.kind, head + "\n".join(out), r.action_id, r.action_hash, r.options, r.items,
                                r.permissions, r.extra)
        if skipped:
            out.append("Not run because another app is already open: %s. Say them after you come back." %
                       "; ".join(skipped))
        extra = next((x for x in ("await_auto_send",) if self._awaiting_send), None)
        return Response("info", ((title + " done:\n") if title else "") + "\n".join(out), extra=extra)

    # ---------- alarms & timers (phone's Clock app) ----------
    def _alarm(self, kind, ent):
        if not self.alarms.capability_check():
            return Response("unsupported", "Alarms are not available on this device.")
        if kind == "show_alarms":
            r = self.alarms.show_alarms()
            return Response("info", "Opening your alarms." if r.status == "handed_off"
                            else "Could not open the alarms: %s" % r.detail)
        if kind == "set_timer":
            if not ent.get("seconds"):
                self._pending_alarm = ("set_timer", ent)
                return Response("need_info", "For how long? Example: 10 minutes")
            r = self.alarms.set_timer(ent["seconds"], ent.get("label"))
            self.store.audit("-", "set_timer", "not_required:read_only_clock", r.status)
            if r.status != "handed_off":
                return Response("error", "Could not set the timer: %s" % r.detail)
            return Response("info", "Timer set for %s." % _duration_words(ent["seconds"]))
        if not ent.get("time"):
            self._pending_alarm = ("set_alarm", ent)
            return Response("need_info", "What time should the alarm ring? Example: 5 am")
        h, m = (int(x) for x in ent["time"].split(":"))
        r = self.alarms.set_alarm(h, m, ent.get("label"), ent.get("days"))
        self.store.audit("-", "set_alarm", "not_required:user_can_delete_in_clock", r.status)
        if r.status != "handed_off":
            return Response("error", "Could not set the alarm: %s" % r.detail)
        days = ent.get("days")
        when = "" if not days else " every day" if len(days) == 7 else " every " + ", ".join(
            DAY_NAMES[d] for d in days)
        label = " (%s)" % ent["label"] if ent.get("label") else ""
        return Response("info", "Alarm set for %s%s%s in your Clock app." % (_clock12(h, m), when, label))

    AUTO_SEND_RECHECK = 0.8   # seconds: one more look when the first answer is 'off' (tests set 0)
    AUTO_SEND_SETTLE = 15.0   # seconds to keep looking right after the Settings screen was opened

    def auto_send_ready(self):
        """Is WhatsApp auto-send on? Runs on the worker thread. On the test phone (vivo) opening the
        Accessibility settings screen switched the service off while it was shown, and it came back
        on by itself ~10 s after leaving it: within 30 s of that screen, keep looking for up to 15 s
        before answering 'off'. Otherwise one more look after 0.8 s."""
        ask = getattr(self.messages, "auto_send_ready", lambda: False)
        ready = bool(ask())
        if ready or self.AUTO_SEND_RECHECK <= 0 or not hasattr(self.messages, "arm_auto_send"):
            return ready
        recent = time.time() - float(getattr(self.messages, "settings_opened_at", 0) or 0) < 30
        end = time.time() + (self.AUTO_SEND_SETTLE if recent else self.AUTO_SEND_RECHECK)
        while time.time() < end:
            time.sleep(min(1.0, self.AUTO_SEND_RECHECK))
            if ask():
                return True
        return False

    def auto_send_status(self):
        """'auto send on karo' / Menu > WhatsApp auto-send: say whether it is on; offer the switch."""
        if not hasattr(self.messages, "arm_auto_send"):
            return Response("info", "WhatsApp auto-send works only in the phone app.")
        if self.auto_send_ready():
            return Response("info", "Yes, WhatsApp auto-send is ON: after I open a chat with your message "
                            "typed, I press Send for you. (To switch it off: tap 'Auto-send settings'.)",
                            extra="auto_send_settings")
        return Response("info", "No, WhatsApp auto-send is OFF, so WhatsApp messages wait for you to press "
                        "Send. Tap 'Turn on auto-send' to switch it on.", extra="auto_send_setup")

    def auto_send_report(self):
        """Called when the app comes back to the front after an auto-send: what happened?"""
        name, self._awaiting_send = self._awaiting_send, None
        if not name:
            return None
        r = self.messages.take_auto_send_result()
        self.store.audit("-", "whatsapp_auto_send", "not_required:user_setting_auto_send", r or "none")
        if r == "sent":
            return Response("info", "WhatsApp message sent to %s." % name)
        if r == "waiting":
            self._awaiting_send = name  # still within the time window; check again on next return
            return None
        if r == "click_failed":
            return Response("error", "WhatsApp opened but the Send press did not work. Please press Send yourself.")
        return Response("error", "Not sent: WhatsApp did not show the message in time (is %s on WhatsApp?). "
                                 "Check the chat and press Send yourself." % name)

    def _split_name_text(self, both):
        """'aman hi' -> name 'aman', text 'hi'. The longest start (up to 3 words) that is
        exactly a contact's name wins, so 'neha 2 good night' -> 'Neha 2' + 'good night'."""
        words = both.split()
        if re.fullmatch(r"\+?[\d\-]{7,}", words[0]):
            return {"number": words[0], "text": " ".join(words[1:])}
        if self.contacts.capability_check() and self.contacts.permission_check() != "denied":
            for k in range(min(3, len(words) - 1), 0, -1):
                cand = " ".join(words[:k])
                try:
                    matches, exact = self._match_contacts(cand, None)
                except Exception:
                    break
                if matches and exact and any(_norm_name(m["name"]) == _norm_name(cand) for m in matches):
                    return {"name": cand, "text": " ".join(words[k:])}
        return {"name": words[0], "text": " ".join(words[1:])}

    def _send(self, ent):
        ent = dict(ent)
        if ent.get("name_text") and not ent.get("text"):
            if not ent.get("number") and self.contacts.permission_check() == "denied":
                return Response("need_permission", "Sending this needs permission (read contacts). Allow it and "
                                "say the same thing again.", permissions=[READ_CONTACTS])
            ent.update(self._split_name_text(ent["name_text"]))
        ent.pop("name_text", None)
        # ask one thing at a time and remember the answer (see handle: _pending_msg)
        if not (ent.get("name") or ent.get("number")):
            self._pending_msg = {"ent": ent, "need": "name"}
            return Response("need_info", "Who should get the message?")
        if not ent.get("text"):
            self._pending_msg = {"ent": ent, "need": "text"}
            return Response("need_info", "What should the message to %s say?" % (ent.get("name") or ent["number"]))
        if not self.messages.capability_check():
            return Response("unsupported", "Sending messages is not available on this device.")
        if not ent.get("channel"):
            self._choices = {"kind": "msg_channel", "items": ["sms", "whatsapp"], "ent": ent}
            return Response("choose", "How should I send it?",
                            options=["1. SMS", "2. WhatsApp (you press Send)"])
        need = []
        if not ent.get("number") and self.contacts.permission_check() == "denied":
            need.append(READ_CONTACTS)
        if ent["channel"] == "sms":
            if self.messages.permission_check() == "denied":
                need += self.messages.required_permissions()
            if ent.get("sim") and self.phone.sims() is None:
                need.append(READ_PHONE_STATE)
        if need:
            return Response("need_permission", "Sending this needs permission (%s). Allow it and say the same "
                            "thing again." % ", ".join(p.rsplit(".", 1)[-1].replace("_", " ").lower() for p in need),
                            permissions=need)
        sim = None
        if ent["channel"] == "sms":
            sim = self._resolve_sim(ent.get("sim"))
            if isinstance(sim, Response):
                return Response(sim.kind, sim.text.replace("No call was made", "No message was sent"))
        if ent.get("number"):
            return self._send_to(ent, ent.get("display") or ent["number"], ent["number"], sim)
        try:
            matches, exact = self._match_contacts(ent["name"], ent.get("prefix"))
        except Exception as ex:
            return Response("error", "Could not read contacts: %s" % type(ex).__name__)
        if not matches:
            return Response("info", "No contact found for '%s'. No message was sent." % ent["name"])
        if len(matches) == 1 and exact:
            return self._send_to(ent, matches[0]["name"], matches[0]["number"], sim)
        self._choices = {"kind": "msg_contact", "items": matches[:5], "ent": ent, "sim": sim}
        return Response("choose", "Who should get the message?",
                        options=["%d. %s (%s)" % (i + 1, m["name"], m["number"]) for i, m in enumerate(matches[:5])])

    def _send_to(self, ent, name, number, sim):
        if ent.get("confirm") and ent["channel"] == "whatsapp":
            # the person came from context ("send her hi"): confirm before anything opens or sends
            self._choices = {"kind": "msg_contact", "items": [{"name": name, "number": number}],
                             "ent": {k: v for k, v in ent.items() if k != "confirm"}, "sim": sim}
            return Response("choose", "Send '%s' to %s (%s) on WhatsApp? Say 1 or yes." % (ent["text"], name, number),
                            options=["1. %s (%s)" % (name, number)])
        if ent["channel"] == "whatsapp":
            # User's choice: no confirmation card; if auto-send is switched on, Send is pressed for them.
            auto = self.auto_send_ready()
            if auto:
                self.messages.arm_auto_send(ent["text"])
            r = self.messages.open_whatsapp(number, ent["text"])
            self.store.audit("-", "whatsapp_compose", "not_required:user_setting_auto_send" if auto
                             else "not_required:user_presses_send", r.status)
            if r.status != "handed_off":
                return Response("error", "Could not open WhatsApp: %s" % r.detail)
            self._last_contact = (name, number)  # only after something really happened with this person
            if auto:
                self._awaiting_send = name
                return Response("info", "Sending on WhatsApp to %s..." % name, extra="await_auto_send")
            return Response("info", "Opening WhatsApp chat with %s. The message is typed: press Send.\n"
                            "To let the app press Send for you, tap 'Turn on auto-send'." % name,
                            extra="auto_send_setup")
        payload = {"name": name, "number": number, "text": ent["text"],
                   "sim_slot": sim[0] if sim else None, "sim_label": sim[1] if sim else None}
        try:
            action, preview = self.engine.propose("sms_message", payload)
        except Unsupported:
            return Response("unsupported", "Sending SMS is not available on this device.")
        except ValueError as ex:
            return Response("error", "Cannot send this: %s" % ex)
        return Response("proposal", "Proposal: " + preview + "\nApprove?", action.id, action.hash)

    # ---------- daily messages ----------
    # Created through the approval card (approved once), then sent every day by the phone's
    # alarm even when the app is closed. SMS goes automatically; WhatsApp needs one tap on Send.
    def _daily(self, ent):
        if ent.get("repeat") == "unsupported":
            return Response("unsupported", "I can repeat a message every day or on chosen weekdays "
                                           "(e.g. 'har monday', 'weekdays'), but not monthly or hourly.")
        if not ent.get("text"):
            return Response("need_info", "What should the message say? Example: har subah 8 baje mummy ko "
                                         "\"Good morning\" bhejo.")
        if not ent.get("time"):
            return Response("need_info", "At what time? Example: every day at 8 am send \"Good morning\" to mummy.")
        if not (ent.get("name") or ent.get("number")):
            return Response("need_info", "Who should get the message?")
        if not self.daily.capability_check():
            return Response("unsupported", "Daily messages are not available on this device.")
        if not ent.get("channel"):
            self._choices = {"kind": "daily_channel", "items": ["sms", "whatsapp"], "ent": ent}
            return Response("choose", "How should I send it every day?",
                            options=["1. SMS (sent automatically)", "2. WhatsApp (you tap Send)"])
        need = []
        if not ent.get("number") and self.contacts.permission_check() == "denied":
            need.append(READ_CONTACTS)
        need += daily_permissions_of(self.daily, ent["channel"])
        if need:
            why = "send SMS and show notifications" if ent["channel"] == "sms" else "show notifications"
            return Response("need_permission", "Daily messages need permission to %s%s. Allow it and say "
                            "the same thing again." % (why, " and read contacts" if READ_CONTACTS in need else ""),
                            permissions=need)
        if ent.get("number"):
            return self._daily_propose(ent, ent["number"], ent["number"])
        try:
            matches, exact = self._match_contacts(ent["name"], ent.get("prefix"))
        except Exception as ex:
            return Response("error", "Could not read contacts: %s" % type(ex).__name__)
        if not matches:
            return Response("info", "No contact found for '%s'. Nothing was scheduled." % ent["name"])
        if len(matches) == 1 and exact:
            return self._daily_propose(ent, matches[0]["name"], matches[0]["number"])
        self._choices = {"kind": "daily_contact", "items": matches[:5], "ent": ent}
        return Response("choose", "Who should get the daily message?",
                        options=["%d. %s (%s)" % (i + 1, m["name"], m["number"]) for i, m in enumerate(matches[:5])])

    def _daily_propose(self, ent, name, number):
        payload = {"sched_id": secrets.randbelow(2 ** 31 - 2) + 1, "channel": ent["channel"], "name": name,
                   "number": number, "text": ent["text"], "time": ent["time"]}
        if ent.get("days") and len(ent["days"]) < 7:
            payload["days"] = list(ent["days"])
        try:
            action, preview = self.engine.propose("daily_message", payload)
        except Unsupported:
            return Response("unsupported", "Daily messages are not available on this device.")
        except ValueError as ex:
            return Response("error", "Cannot schedule this: %s" % ex)
        note = ("\nSMS charges may apply." if ent["channel"] == "sms"
                else "\nEach day you get a notification; tap it and press Send in WhatsApp.")
        return Response("proposal", "Proposal: " + preview + note + "\nApprove?", action.id, action.hash)

    def list_schedules(self):
        return self.store.all("schedule")

    def delete_schedule(self, rid):
        rec = next((r for r in self.store.all("schedule") if r["id"] == rid), None)
        if rec is None:
            return False
        try:
            self.daily.cancel(rec["sched_id"])  # stop the alarm first
        except Exception:
            return False
        self.store.audit("-", "daily_message_deleted", "n/a", "done")
        return self.store.delete(rid)

    def resume_schedules(self):
        """On app start: make the phone's alarms match the encrypted records (alarms are lost when
        the app is force-stopped). Returns how many are active."""
        if not self.daily.capability_check():
            return 0
        recs = {r["sched_id"]: r for r in self.store.all("schedule")}
        # one-time reminders live in the same Java store; keep those that belong to open to-dos
        keep = set(recs) | {t["reminder_id"] for t in self.store.all("todo")
                            if t.get("reminder_id") and not t.get("done")} | {
            r["trigger"]["sched_id"] for r in self.store.all("routine") if r.get("trigger")}
        for sid in self.daily.java_ids() - keep:
            self.daily.cancel(sid)  # left over from deleted data
        for sid in set(recs) - self.daily.java_ids():
            r = recs[sid]
            self.daily.execute({k: r[k] for k in ("sched_id", "channel", "name", "number", "text", "time", "days")
                                if k in r})
        return self.daily.reschedule_all()

    def _direct_call(self, name, number, sim):
        payload = {"name": name, "number": number, "sim_slot": sim[0] if sim else None}
        try:
            res = self.engine.run_direct("phone_call", payload, "user_setting_direct_call")
        except Unsupported:
            return Response("unsupported", "Calling is not available on this device.")
        except ValueError as ex:
            return Response("error", "The number does not look right: %s. No call was made." % ex)
        via = (" from SIM %d (%s)" % sim) if sim else ""
        if res.status in ("done", "handed_off"):
            self._last_contact = (name, number)  # only after the call really started
        if res.status == "done":
            return Response("info", "Calling %s (%s)%s." % (name, number, via))
        if res.status == "handed_off":
            return Response("info", "Dialer opened (%s). Tap the call button to call." % number)
        return Response("error", "Call failed: %s" % res.detail)

    # ---------- photos ----------
    def _find_photos(self, it, now):
        if not self.photos.capability_check():
            return Response("unsupported", "Photos are not available on this device.")
        perm = self.photos.permission_check()
        if perm == "denied":
            return Response("need_permission", "I need permission to see your photos. Please allow it and try again.",
                            permissions=self.photos.required_permissions())
        rng, kw = it.entities.get("range"), it.entities.get("keyword")
        today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start, end = {
            "today": (today0, now + timedelta(minutes=1)),
            "yesterday": (today0 - timedelta(days=1), today0),
            "week": (now - timedelta(days=7), now + timedelta(minutes=1)),
            "month": (now - timedelta(days=30), now + timedelta(minutes=1)),
        }.get(rng, (datetime(1970, 1, 2, tzinfo=now.tzinfo), now + timedelta(days=1)))
        try:
            res = self.photos.search(start.timestamp() * 1000, end.timestamp() * 1000, kw)
        except Exception as ex:
            return Response("error", "Could not read photos: %s" % type(ex).__name__)
        self.store.audit("-", "photo_search", "n/a", "done", "count=%d" % res["count"])
        what = " ".join(x for x in (RANGE_LABEL.get(rng, ""), ("'%s'" % kw) if kw else "") if x) or "all"
        note = "\n(Only showing the photos you gave access to.)" if perm == "partial" else ""
        if not res["count"]:
            self._photo_ids = set()
            return Response("info", "No photos found (%s).%s" % (what, note))
        items = []
        for p in res["items"]:
            when = datetime.fromtimestamp(p["taken_ms"] / 1000, now.tzinfo).strftime("%d %b %H:%M")
            items.append({"id": p["id"], "label": "%s  %s" % (when, p["album"] or p["name"])})
        self._photo_ids = {p["id"] for p in items}
        return Response("photos", "Found %d photos (%s). Newest %d:%s" % (res["count"], what, len(items), note),
                        items=items)

    def open_photo(self, photo_id):
        if photo_id not in self._photo_ids:  # only ids we just showed; never arbitrary input
            return Response("error", "This photo is no longer in the list. Please search again.")
        r = self.photos.open(photo_id)
        self.store.audit("-", "open_photo", "n/a", r.status)
        return Response("info", "Opened the photo in the gallery/viewer." if r.status == "handed_off"
                        else "Could not open the photo: " + r.detail)

    # ---------- approval ----------
    def approve(self, action_id, shown_hash):
        res = self.engine.approve(action_id, shown_hash)
        a = self.engine.actions.get(action_id)
        if a and a.type == "calendar_event" and res.status in ("done", "handed_off"):
            self.store.put("task", {"title": a.payload["title"], "start_iso": a.payload["start_iso"],
                                    "end_iso": a.payload["end_iso"], "status": "scheduled",
                                    "calendar": res.status})
        if a and a.type == "sms_message" and res.status == "done":
            self._last_contact = (a.payload["name"], a.payload["number"])  # sent, not just proposed
        if a and a.type == "daily_message" and res.status == "done":
            self.store.put("schedule", dict(a.payload))  # encrypted record; the alarm is already set
        specific = {
            ("daily_message", "done"): ("Daily message scheduled for %s every day." % a.payload.get("time")
                                        if a else "Daily message scheduled.")
                                       + " You can see or delete it under Tasks.",
            ("sms_message", "done"): "SMS handed to the phone for sending to %s." % (a.payload.get("name", "")
                                                                                if a else ""),
            ("sms_message", "denied"): "SMS permission is off, so nothing was sent.",
            ("daily_message", "denied"): "A permission is missing, so nothing was scheduled. Say it again "
                                         "and allow the permission.",
            ("calendar_event", "done"): "Calendar event created.",
            ("calendar_event", "handed_off"): "The calendar screen is open. The event is created only when you "
                                              "tap Save there. The task is saved in the app.",
            ("phone_call", "done"): "Call started (%s)." % (a.payload.get("name", "") if a else ""),
            ("phone_call", "handed_off"): "Dialer opened with the number filled in. Tap the call button to call.",
        }
        generic = {
            "denied": "Android permission was not given. Nothing changed.",
            "duplicate": "This action was already done.",
            "invalidated": "The action changed, so it was not approved. Please ask again.",
            "unsupported": "This is not supported on this device.",
        }
        msg = specific.get((a.type if a else "", res.status)) or generic.get(res.status, "Failed: " + res.detail)
        if a and a.type == "daily_message" and res.status == "done" and not self.daily_battery_ok():
            return Response("info", msg + "\nImportant: allow Lazey to run in the background on the "
                            "next screen, or your phone may stop daily messages after the first day.",
                            extra="battery_exemption")
        return Response("info", msg)

    def daily_battery_ok(self):
        fn = getattr(self.daily, "battery_exempt", None)
        return fn() if fn else True

    def reject(self, action_id):
        return Response("info", "Rejected. Nothing changed." if self.engine.reject(action_id)
                        else "This action can no longer be rejected.")

    # ---------- chat history (encrypted like everything else) ----------
    CHAT_KEEP = 500   # older lines are deleted
    CHAT_SHOW = 100   # lines shown when the app opens

    def log_chat(self, who, text):
        if who not in ("user", "bot", "sys") or not text:
            return
        self.store.put("chat", {"who": who, "text": str(text)[:4000]})

    def chat_history(self, limit=None):
        self.store.trim("chat", self.CHAT_KEEP)
        return [h for h in self.store.recent("chat", limit or self.CHAT_SHOW) if h.get("who") in ("user", "bot", "sys")]

    def clear_chat(self):
        n = self.store.delete_kind("chat")
        self.store.audit("-", "clear_chat", "n/a", "done", "lines=%d" % n)
        return n

    # ---------- user data controls ----------
    def list_preferences(self):
        return self.store.all("pref")

    def list_tasks(self):
        return self.store.all("task")

    def update_preference(self, rid, text):
        tags = {}
        for tag, rx in TOD:
            if re.search(rx, text, re.I):
                tags["time_of_day"] = tag
        return self.store.update(rid, {"text": text, "tags": tags}, vector_text=text)

    def delete_record(self, rid):
        return self.store.delete(rid)

    def delete_all_data(self):
        if self.daily.capability_check():
            try:
                self.daily.cancel_all()  # stop every daily alarm before the records go
            except Exception:
                pass
        self.store.delete_all()
        self.store.audit("-", "delete_all_data", "n/a", "done")
