"""Orchestrator: text -> intent -> (memory | plan -> proposal -> approval -> adapter)."""
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import config, planner
from .adapters.base import UnsupportedAdapter
from .approval import ApprovalEngine, Unsupported
from .inference import UNSUPPORTED, validate

RANGE_LABEL = {"today": "aaj", "yesterday": "kal", "week": "pichle 7 din", "month": "pichle 30 din"}


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
            return Response("error", "Kuch likhiye.")
        now = self.clock()
        if self._choices and text.isdigit():
            return self.choose_contact(int(text) - 1)
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
            return Response("unsupported", "Yeh abhi supported nahi hai (%s): adapter implement nahi hua." % n)
        return Response("info", "Samajh nahi aaya. Parser: %s" % self.backend.name)

    # ---------- memory ----------
    def _remember(self, it):
        if it.missing_fields:
            return Response("need_info", "Kya yaad rakhna hai?")
        text = it.entities["text"]
        if TEMP_RE.search(text):
            return Response("info", "Yeh temporary lag raha hai, isliye permanent preference ke roop mein save nahi kiya.")
        tags = {}
        for tag, rx in TOD:
            if re.search(rx, text, re.I):
                tags["time_of_day"] = tag
        self.store.put("pref", {"text": text, "tags": tags}, vector_text=text)
        self.store.audit("-", "save_preference", "n/a", "done")
        return Response("info", "Preference save ho gayi: %s" % text)

    def _note(self, it):
        if it.missing_fields:
            return Response("need_info", "Note mein kya likhna hai?")
        self.store.put("note", {"text": it.entities["text"]}, vector_text=it.entities["text"])
        self.store.audit("-", "save_note", "n/a", "done")
        return Response("info", "Note save ho gaya.")

    def _query(self, it):
        q = it.entities.get("query", "")
        hits = self.store.search("note", q, config.RETRIEVE_K, config.RETRIEVE_MIN_SCORE)
        if not hits:
            return Response("info", "Koi matching note nahi mila.")
        # retrieved text is shown as data only; it is never parsed as an instruction
        lines = ["- " + h["text"][:config.SNIPPET_CHARS] for _, h in hits]
        return Response("info", "Aapke notes:\n" + "\n".join(lines))

    # ---------- scheduling ----------
    def _schedule(self, ent, now, missing=None):
        missing = missing if missing is not None else [f for f in ("title", "duration_minutes", "date") if f not in ent]
        if missing:
            self._pending = dict(ent)
            return Response("need_info", "Yeh detail chahiye: " + ", ".join(missing))
        prefs = self.store.all("pref")
        win = planner.resolve_window(ent, prefs)
        if win is None:
            self._pending = dict(ent)
            return Response("need_info", "Kis samay kaam karna chahte ho? (subah / dopahar / shaam ya HH:MM)")
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
            return Response("info", "Slot nahi mila: " + res["reason"])
        payload = {"title": ent["title"], "start_iso": res["start"].isoformat(), "end_iso": res["end"].isoformat()}
        try:
            action, preview = self.engine.propose("calendar_event", payload)
        except Unsupported:
            return Response("unsupported", "Calendar action is device par available nahi hai.")
        except ValueError as ex:
            return Response("error", "Invalid plan: %s" % ex)
        note = "" if known else "\n(Note: calendar ki availability check nahi ho payi, sirf app ke tasks se overlap dekha.)"
        return Response("proposal", "Prastaav: " + preview + note + "\nApprove karein?",
                        action.id, action.hash)

    # ---------- calls ----------
    # User's choice: call immediately (no Approve tap) when the target is unambiguous.
    # Still asks when: several contacts match, the named SIM is not in the phone, or a
    # permission is missing. Audit records that no approval was required, never who/which number.
    def _call(self, it):
        if it.missing_fields:
            return Response("need_info", "Kisko call karna hai? Naam ya number likhiye.")
        if not self.phone.capability_check():
            return Response("unsupported", "Call is device par available nahi hai.")
        if not it.entities.get("number") and not self.contacts.capability_check():
            return Response("unsupported", "Contacts is device par available nahi hain. Seedha number boliye.")
        need = self._call_permissions_missing(it.entities)
        if need:
            return Response("need_permission",
                            "Seedhi call ke liye Contacts, Phone aur SIM ki permission chahiye. "
                            "Allow karke dobara boliye.", permissions=need)
        sim = self._resolve_sim(it.entities.get("sim"))
        if isinstance(sim, Response):
            return sim
        if it.entities.get("number"):
            return self._direct_call(it.entities["number"], it.entities["number"], sim)
        name, prefix = it.entities["name"], it.entities.get("prefix")
        try:
            matches, exact = self._match_contacts(name, prefix)
        except Exception as ex:
            return Response("error", "Contacts padh nahi paya: %s" % type(ex).__name__)
        self.store.audit("-", "contact_lookup", "n/a", "done", "matches=%d" % len(matches))
        who = "'%s'%s" % (name, (" (number %s... se shuru)" % prefix) if prefix else "")
        if not matches:
            return Response("info", "%s naam ka koi contact nahi mila. Kuch call nahi hua." % who)
        if len(matches) == 1 and exact:
            return self._direct_call(matches[0]["name"], matches[0]["number"], sim)
        self._choices = (matches[:5], sim)
        labels = ["%d. %s (%s)" % (i + 1, m["name"], m["number"]) for i, m in enumerate(matches[:5])]
        if not exact:
            return Response("choose", "%s poora naam nahi mila, yeh milte-julte contacts hain. "
                            "Kisko call karna hai?" % who, options=labels)
        hint = "" if prefix else " (Agli baar number ke shuru ke 4 ank bhi bol sakte hain.)"
        return Response("choose", "%s ke %d contacts mile. Kisko call karna hai?%s" % (who, len(matches), hint),
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
        have = ", ".join("SIM %d (%s)" % (s["slot"], s["label"]) for s in sims) or "koi nahi"
        return Response("error", "'%s' wali SIM pakki nahi hui. Phone mein SIMs: %s. Kuch call nahi hua."
                        % (want, have))

    def choose_contact(self, index):
        choices, self._choices = self._choices, None
        if not choices or not 0 <= index < len(choices[0]):
            return Response("error", "Yeh vikalp ab valid nahi hai. Dobara boliye.")
        m = choices[0][index]
        return self._direct_call(m["name"], m["number"], choices[1])

    def _direct_call(self, name, number, sim):
        payload = {"name": name, "number": number, "sim_slot": sim[0] if sim else None}
        try:
            res = self.engine.run_direct("phone_call", payload, "user_setting_direct_call")
        except Unsupported:
            return Response("unsupported", "Call is device par available nahi hai.")
        except ValueError as ex:
            return Response("error", "Number sahi nahi lag raha: %s. Kuch call nahi hua." % ex)
        via = (" SIM %d (%s) se" % sim) if sim else ""
        if res.status == "done":
            return Response("info", "%s (%s) ko%s call lag rahi hai." % (name, number, via))
        if res.status == "handed_off":
            return Response("info", "Dialer khul gaya (%s). Call button aap dabayenge." % number)
        return Response("error", "Call nahi lagi: %s" % res.detail)

    # ---------- photos ----------
    def _find_photos(self, it, now):
        if not self.photos.capability_check():
            return Response("unsupported", "Photos is device par available nahi hain.")
        perm = self.photos.permission_check()
        if perm == "denied":
            return Response("need_permission", "Photos dekhne ki permission chahiye. Allow karke dobara boliye.",
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
            return Response("error", "Photos padh nahi paya: %s" % type(ex).__name__)
        self.store.audit("-", "photo_search", "n/a", "done", "count=%d" % res["count"])
        what = " ".join(x for x in (RANGE_LABEL.get(rng, ""), ("'%s'" % kw) if kw else "") if x) or "sabhi"
        note = "\n(Sirf woh photos dikh rahi hain jinki aapne access di hai.)" if perm == "partial" else ""
        if not res["count"]:
            self._photo_ids = set()
            return Response("info", "Koi photo nahi mili (%s).%s" % (what, note))
        items = []
        for p in res["items"]:
            when = datetime.fromtimestamp(p["taken_ms"] / 1000, now.tzinfo).strftime("%d %b %H:%M")
            items.append({"id": p["id"], "label": "%s  %s" % (when, p["album"] or p["name"])})
        self._photo_ids = {p["id"] for p in items}
        return Response("photos", "%d photos mili (%s). Sabse nayi %d:%s" % (res["count"], what, len(items), note),
                        items=items)

    def open_photo(self, photo_id):
        if photo_id not in self._photo_ids:  # only ids we just showed; never arbitrary input
            return Response("error", "Yeh photo ab list mein nahi hai. Dobara dhoondhiye.")
        r = self.photos.open(photo_id)
        self.store.audit("-", "open_photo", "n/a", r.status)
        return Response("info", "Photo gallery/viewer mein khol di." if r.status == "handed_off"
                        else "Photo khul nahi payi: " + r.detail)

    # ---------- approval ----------
    def approve(self, action_id, shown_hash):
        res = self.engine.approve(action_id, shown_hash)
        a = self.engine.actions.get(action_id)
        if a and a.type == "calendar_event" and res.status in ("done", "handed_off"):
            self.store.put("task", {"title": a.payload["title"], "start_iso": a.payload["start_iso"],
                                    "end_iso": a.payload["end_iso"], "status": "scheduled",
                                    "calendar": res.status})
        specific = {
            ("calendar_event", "done"): "Calendar event ban gaya.",
            ("calendar_event", "handed_off"): "System calendar screen khul gayi. Event tab hi banega jab aap "
                                              "wahan Save dabayenge. Task app mein save ho gaya.",
            ("phone_call", "done"): "Call shuru kar di (%s)." % (a.payload.get("name", "") if a else ""),
            ("phone_call", "handed_off"): "Dialer khul gaya, number bhara hua hai. Call button aap dabayenge.",
        }
        generic = {
            "denied": "Android permission nahi mili, kuch nahi badla.",
            "duplicate": "Yeh action pehle hi process ho chuka hai.",
            "invalidated": "Action badal gaya tha, isliye approve nahi hua. Dobara maangein.",
            "unsupported": "Yeh device par supported nahi hai.",
        }
        msg = specific.get((a.type if a else "", res.status)) or generic.get(res.status, "Fail hua: " + res.detail)
        return Response("info", msg)

    def reject(self, action_id):
        return Response("info", "Reject kar diya, kuch nahi badla." if self.engine.reject(action_id)
                        else "Is action ko ab reject nahi kar sakte.")

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
