"""Orchestrator: text -> intent -> (memory | plan -> proposal -> approval -> adapter)."""
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import config, planner
from .adapters.base import UnsupportedAdapter
from .approval import ApprovalEngine, Unsupported
from .inference import UNSUPPORTED, validate

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


class Assistant:
    def __init__(self, store, backend, calendar, clock, contacts=None, phone=None, photos=None):
        self.store, self.backend, self.calendar, self.clock = store, backend, calendar, clock
        self.contacts = contacts or UnsupportedAdapter("contacts")
        self.phone = phone or UnsupportedAdapter("phone_call")
        self.photos = photos or UnsupportedAdapter("photos")
        self.adapters = {
            "calendar_event": calendar,
            "phone_call": self.phone,
            "messages": UnsupportedAdapter("messages"),
            "settings": UnsupportedAdapter("settings"),
            "files": UnsupportedAdapter("files"),
        }
        self.engine = ApprovalEngine(store, self.adapters)
        self._pending = None  # schedule request waiting for a missing detail
        self._choices = None  # contact matches waiting for the user to pick one
        self._photo_ids = set()  # only photos from the last search may be opened

    # ---------- main entry ----------
    def handle(self, text):
        text = (text or "").strip()[:config.MAX_INPUT_CHARS]
        if not text:
            return Response("error", "Please type something.")
        now = self.clock()
        pick = _choice_number(text) if self._choices else None
        if pick:
            return self.choose_contact(pick - 1)
        self._choices = None
        if self._pending is not None and hasattr(self.backend, "followup"):
            extra = self.backend.followup(text)
            if extra:
                ent = dict(self._pending, **extra)
                self._pending = None
                return self._schedule(ent, now)
            self._pending = None
        it = validate(self.backend.parse(text, now.date()), now.date())
        n = it.intent
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
        if n in UNSUPPORTED:
            return Response("unsupported", "This is not supported yet (%s): no adapter is implemented." % n)
        return Response("info", "Sorry, I did not understand that. Parser: %s" % self.backend.name)

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
    def _call(self, it):
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
            return self._direct_call(it.entities["number"], it.entities["number"], sim)
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
        self._choices = (matches[:5], sim)
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

    def choose_contact(self, index):
        choices, self._choices = self._choices, None
        if not choices or not 0 <= index < len(choices[0]):
            return Response("error", "This option is no longer valid. Please ask again.")
        m = choices[0][index]
        return self._direct_call(m["name"], m["number"], choices[1])

    def _direct_call(self, name, number, sim):
        payload = {"name": name, "number": number, "sim_slot": sim[0] if sim else None}
        try:
            res = self.engine.run_direct("phone_call", payload, "user_setting_direct_call")
        except Unsupported:
            return Response("unsupported", "Calling is not available on this device.")
        except ValueError as ex:
            return Response("error", "The number does not look right: %s. No call was made." % ex)
        via = (" from SIM %d (%s)" % sim) if sim else ""
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
        specific = {
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
        return Response("info", msg)

    def reject(self, action_id):
        return Response("info", "Rejected. Nothing changed." if self.engine.reject(action_id)
                        else "This action can no longer be rejected.")

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
        self.store.delete_all()
        self.store.audit("-", "delete_all_data", "n/a", "done")
