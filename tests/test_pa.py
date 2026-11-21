"""Tests for the pa/ core. FakeCalendar and StaticKeyProvider are TEST-ONLY mocks."""
import os
import sys
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pa import planner  # noqa: E402
from pa.adapters.base import Adapter, Result  # noqa: E402
from pa.approval import ApprovalEngine, Unsupported  # noqa: E402
from pa.assistant import Assistant  # noqa: E402
from pa.crypto import Crypto  # noqa: E402
from pa.inference import ConstrainedParser, validate  # noqa: E402
from pa.keys import DevFileKeyProvider, KeyUnavailable  # noqa: E402
from pa.storage import Store  # noqa: E402

TZ = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 20, 9, 0, tzinfo=TZ)
KEY = bytes(range(32))  # TEST-ONLY static key


class FakeCalendar(Adapter):  # TEST-ONLY mock
    name = "calendar"

    def __init__(self, busy=None, perm="not_required", cap=True):
        self.executed, self._busy, self.perm, self.cap = [], busy, perm, cap

    def capability_check(self):
        return self.cap

    def permission_check(self):
        return self.perm

    def validate(self, p):
        return [] if p.get("title") else ["title required"]

    def preview(self, p):
        s, e = datetime.fromisoformat(p["start_iso"]), datetime.fromisoformat(p["end_iso"])
        return "Event '%s' %s %s-%s" % (p["title"], s.date(), s.strftime("%H:%M"), e.strftime("%H:%M"))

    def busy(self, day, tz):
        return self._busy

    def execute(self, p):
        self.executed.append(p)
        return Result("handed_off", "opened")


def make(path, cal=None, **adapters):
    store = Store(path, Crypto(KEY))
    cal = cal or FakeCalendar(busy=[])
    return Assistant(store, ConstrainedParser(), cal, lambda: NOW, **adapters), store, cal


class FakeContacts(Adapter):  # TEST-ONLY mock
    def __init__(self, book, perm="granted"):
        self.book, self.perm, self.searched = book, perm, []

    def capability_check(self):
        return True

    def permission_check(self):
        return self.perm

    def required_permissions(self):
        return ["android.permission.READ_CONTACTS"]

    def search(self, name, limit=5):
        self.searched.append(name)
        return [c for c in self.book if name.lower() in c["name"].lower()][:limit]


TWO_SIMS = [{"slot": 1, "label": "Jio 4G"}, {"slot": 2, "label": "Airtel"}]


class FakePhone(Adapter):  # TEST-ONLY mock
    name = "phone_call"

    def __init__(self, direct=True, sims=TWO_SIMS, phone_state=True):
        self.direct, self.calls, self._sims, self.phone_state = direct, [], sims, phone_state

    def capability_check(self):
        return True

    def permission_check(self):
        return "not_required"

    def can_call_directly(self):
        return self.direct

    def required_permissions(self):
        return ["android.permission.CALL_PHONE", "android.permission.READ_PHONE_STATE"]

    def sims(self):
        return list(self._sims) if self.phone_state else None

    def validate(self, p):
        from pa.adapters.phone import AndroidPhoneAdapter
        return AndroidPhoneAdapter.validate(self, p)

    def preview(self, p):
        return "Call: %s (%s)" % (p["name"], p["number"])

    def execute(self, p):
        self.calls.append(dict(p))
        return Result("done" if self.direct else "handed_off")


class FakePhotos(Adapter):  # TEST-ONLY mock
    def __init__(self, photos, perm="granted"):
        self.photos, self.perm, self.queries, self.opened = photos, perm, [], []

    def capability_check(self):
        return True

    def permission_check(self):
        return self.perm

    def required_permissions(self):
        return ["android.permission.READ_MEDIA_IMAGES"]

    def search(self, start_ms, end_ms, keyword=None, limit=6):
        self.queries.append((start_ms, end_ms, keyword))
        hits = [p for p in self.photos if start_ms <= p["taken_ms"] < end_ms
                and (not keyword or keyword in (p["name"] + p["album"]).lower())]
        hits.sort(key=lambda p: -p["taken_ms"])
        return {"count": len(hits), "items": hits[:limit]}

    def open(self, pid):
        self.opened.append(pid)
        return Result("handed_off")


def ms(dt):
    return int(dt.timestamp() * 1000)


BOOK = [{"name": "Rahul Sharma", "number": "+91 98765 43210"},
        {"name": "Rahul Verma", "number": "98111 22233"},
        {"name": "Mummy", "number": "9000000001"}]
PICS = [{"id": 1, "name": "IMG_1.jpg", "album": "Camera", "taken_ms": ms(NOW - timedelta(hours=1))},
        {"id": 2, "name": "Screenshot_2.png", "album": "Screenshots", "taken_ms": ms(NOW - timedelta(days=1))},
        {"id": 3, "name": "IMG_3.jpg", "album": "Camera", "taken_ms": ms(NOW - timedelta(days=20))}]


class CallsAndPhotosParsing(unittest.TestCase):
    P = ConstrainedParser()
    TODAY = date(2026, 11, 20)

    def v(self, text):
        return validate(self.P.parse(text, self.TODAY), self.TODAY)

    def test_call_phrases(self):
        for text, name in (("rahul ko call karo", "rahul"), ("mummy ko phone lagao", "mummy"),
                           ("call rahul sharma", "rahul sharma"), ("Rahul ko call kar do please", "rahul")):
            i = self.v(text)
            self.assertEqual((i.intent, i.entities.get("name")), ("call_contact", name), text)
            self.assertFalse(i.requires_approval)  # user chose direct calls
        i = self.v("call 98765 43210")
        self.assertEqual((i.intent, i.entities.get("number")), ("call_contact", "9876543210"))
        self.assertEqual(self.v("call karo").missing_fields, ["name"])

    def test_sim_and_prefix_phrases(self):
        cases = {
            "rahul 9876 ko sim 2 se call karo": {"name": "rahul", "prefix": "9876", "sim": "2"},
            "Rahul ko Jio se call karo": {"name": "rahul", "sim": "jio"},
            "dusri sim se mummy ko call karo": {"name": "mummy", "sim": "2"},
            "rahul ko 1 wali sim se call karo": {"name": "rahul", "sim": "1"},
            "rahul sharma jiska number 9811 se shuru hota hai usko airtel se call karo":
                {"name": "rahul sharma", "prefix": "9811", "sim": "airtel"},
            "call 98765 43210 sim 1 se": {"number": "9876543210", "sim": "1"},
            # natural English (reported by user: second form used to fail)
            "call neha 7012 from sim 1": {"name": "neha", "prefix": "7012", "sim": "1"},
            "call neha whose number starts from 7012 from sim 1":
                {"name": "neha", "prefix": "7012", "sim": "1"},
            "call neha whose number starts with 7012 using sim 1":
                {"name": "neha", "prefix": "7012", "sim": "1"},
            "please call neha, her number begins with 7012, from sim 2":
                {"name": "neha", "prefix": "7012", "sim": "2"},
            "call rahul sharma whose number is starting with 98 11 via airtel":
                {"name": "rahul sharma", "prefix": "9811", "sim": "airtel"},
            "can you call mummy from second sim": {"name": "mummy", "sim": "2"},
            "neha ko call karo jiska number 7012 se start hota hai sim 1 se":
                {"name": "neha", "prefix": "7012", "sim": "1"},
        }
        for text, want in cases.items():
            i = self.v(text)
            got = {k: i.entities.get(k) for k in want}
            self.assertEqual(got, want, text)
        self.assertNotIn("prefix", self.v("call 98765 43210").entities)

    def test_photo_phrases(self):
        cases = {"kal ki photos dikhao": ("yesterday", None), "aaj ki photos": ("today", None),
                 "pichle hafte ke screenshots dikhao": ("week", "screenshot"),
                 "camera ki photos": (None, "camera"), "goa ki photos dikhao": (None, "goa"),
                 "pichle mahine ki photos": ("month", None), "phone ki photos dikhao": (None, "phone")}
        for text, (rng, kw) in cases.items():
            i = self.v(text)
            self.assertEqual(i.intent, "find_photos", text)
            self.assertEqual((i.entities.get("range"), i.entities.get("keyword")), (rng, kw), text)
            self.assertFalse(i.requires_approval)

    def test_untrusted_fields_rejected(self):
        i = validate({"intent": "call_contact", "entities": {"number": "tel:*#06#; rm"}}, self.TODAY)
        self.assertNotIn("number", i.entities)
        i = validate({"intent": "find_photos", "entities": {"range": "forever", "keyword": "%' OR 1=1 --"}}, self.TODAY)
        self.assertEqual(i.entities, {})


class Calls(unittest.TestCase):
    def setUp(self):
        self.contacts, self.phone = FakeContacts(BOOK), FakePhone()
        self.a, self.store, _ = make(os.path.join(tempfile.mkdtemp(), "a.db"),
                                     contacts=self.contacts, phone=self.phone)

    def mk(self, **kw):
        a, _, _ = make(os.path.join(tempfile.mkdtemp(), "a.db"), **kw)
        return a

    def test_single_match_calls_immediately(self):
        r = self.a.handle("mummy ko call karo")
        self.assertIn("Calling ", r.text)
        self.assertEqual(self.phone.calls, [{"name": "Mummy", "number": "9000000001", "sim_slot": None}])

    def test_prefix_picks_the_right_contact(self):
        self.a.handle("rahul 9811 ko call karo")
        self.assertEqual(self.phone.calls[-1]["name"], "Rahul Verma")
        self.a.handle("rahul 9876 ko call karo")  # stored as +91 98765...; country code ignored
        self.assertEqual(self.phone.calls[-1]["name"], "Rahul Sharma")

    def test_spoken_name_is_taken_exactly(self):
        book = [{"name": "Neha", "number": "9000000011"},
                {"name": "Neha 2", "number": "9000000022"},
                {"name": "Neha Office", "number": "9000000033"}]
        phone = FakePhone()
        a = self.mk(contacts=FakeContacts(book), phone=phone)
        for text, who in (("neha ko call karo", "Neha"), ("call neha", "Neha"),
                          ("neha 2 ko call karo", "Neha 2"), ("call neha 2 from sim 1", "Neha 2"),
                          ("neha office ko call karo", "Neha Office"),
                          ("call Neha Office", "Neha Office")):
            r = a.handle(text)
            self.assertEqual(phone.calls[-1]["name"], who, "%s -> %s" % (text, r.text))
        self.assertEqual(len(phone.calls), 6)

    def test_name_digit_vs_prefix(self):
        P, d = ConstrainedParser(), date(2026, 11, 20)
        e = validate(P.parse("neha 2 7012 se shuru wale ko call karo", d), d).entities
        self.assertEqual((e.get("name"), e.get("prefix")), ("neha 2", "7012"))
        e = validate(P.parse("call 98 76 54 32 10", d), d).entities
        self.assertEqual((e.get("name"), e.get("number")), (None, "9876543210"))

    def test_natural_sentence_calls_right_contact(self):
        self.a.handle("call rahul whose number starts with 9811")
        self.assertEqual(self.phone.calls[-1]["name"], "Rahul Verma")

    def test_partial_name_match_asks_never_dials(self):
        # 'rahul gupta' does not exist; word fallback finds Rahul Sharma/Verma -> must ask
        r = self.a.handle("call rahul gupta 9876")
        self.assertEqual(r.kind, "choose")
        self.assertEqual(len(r.options), 1)
        self.assertEqual(self.phone.calls, [])

    def test_prefix_without_match_calls_nobody(self):
        r = self.a.handle("rahul 7000 ko call karo")
        self.assertIn("No contact found", r.text)
        self.assertEqual(self.phone.calls, [])

    def test_ambiguous_name_asks_then_calls_choice(self):
        r = self.a.handle("rahul ko call karo")
        self.assertEqual((r.kind, len(r.options)), ("choose", 2))
        self.assertIn("first 4 digits", r.text)
        self.assertEqual(self.phone.calls, [])  # nothing before the user picks
        self.assertIn("Calling ", self.a.handle("2").text)
        self.assertEqual(self.phone.calls[0]["number"], "98111 22233")

    def test_choice_keeps_requested_sim(self):
        self.a.handle("rahul ko sim 2 se call karo")
        self.a.choose_contact(0)
        self.assertEqual(self.phone.calls[0]["sim_slot"], 2)

    def test_choice_expires_and_bad_index(self):
        self.a.handle("rahul ko call karo")
        self.assertEqual(self.a.choose_contact(9).kind, "error")
        self.assertEqual(self.a.choose_contact(0).kind, "error")  # choices consumed
        self.assertEqual(self.phone.calls, [])

    def test_sim_by_slot_and_by_carrier(self):
        r = self.a.handle("mummy ko sim 2 se call karo")
        self.assertIn("SIM 2 (Airtel)", r.text)
        self.assertEqual(self.phone.calls[-1]["sim_slot"], 2)
        self.a.handle("mummy ko jio se call karo")
        self.assertEqual(self.phone.calls[-1]["sim_slot"], 1)

    def test_unknown_sim_calls_nobody(self):
        a = self.mk(contacts=self.contacts, phone=FakePhone(sims=[{"slot": 1, "label": "Jio"}]))
        r = a.handle("mummy ko sim 2 se call karo")
        self.assertEqual(r.kind, "error")
        self.assertIn("SIM 1 (Jio)", r.text)
        r = a.handle("mummy ko airtel se call karo")
        self.assertEqual(r.kind, "error")

    def test_carrier_matched_via_alias_names(self):
        # shape returned on the real vivo phone: label is the carrier, display name is "SIM 1"
        p = FakePhone(sims=[{"slot": 1, "label": "airtel", "names": ["sim 1", "airtel"]}])
        a = self.mk(contacts=self.contacts, phone=p)
        self.assertIn("SIM 1 (airtel)", a.handle("mummy ko airtel se call karo").text)
        self.assertEqual(a.handle("mummy ko jio se call karo").kind, "error")
        self.assertEqual(len(p.calls), 1)

    def test_direct_number_with_sim(self):
        r = self.a.handle("call 98765 43210 sim 1 se")
        self.assertIn("SIM 1 (Jio 4G)", r.text)
        self.assertEqual(self.contacts.searched, [])  # number path skips contacts
        self.assertEqual(self.phone.calls[0]["sim_slot"], 1)

    def test_missing_permissions_ask_and_call_nobody(self):
        c = FakeContacts(BOOK, perm="denied")
        a = self.mk(contacts=c, phone=self.phone)
        r = a.handle("rahul ko call karo")
        self.assertEqual(r.kind, "need_permission")
        self.assertIn("android.permission.READ_CONTACTS", r.permissions)
        self.assertEqual(c.searched, [])
        p = FakePhone(direct=False)
        r = self.mk(contacts=self.contacts, phone=p).handle("mummy ko call karo")
        self.assertIn("android.permission.CALL_PHONE", r.permissions)
        p2 = FakePhone(phone_state=False)
        r = self.mk(contacts=self.contacts, phone=p2).handle("mummy ko sim 2 se call karo")
        self.assertIn("android.permission.READ_PHONE_STATE", r.permissions)
        self.assertEqual(p.calls + p2.calls + self.phone.calls, [])

    def test_audit_records_no_approval_but_no_contact_details(self):
        self.a.handle("mummy ko call karo")
        rows = str(self.store.audit_rows())
        self.assertIn("not_required:user_setting_direct_call", rows)
        self.assertNotIn("Mummy", rows)
        self.assertNotIn("9000000001", rows)


class Photos(unittest.TestCase):
    def setUp(self):
        self.ph = FakePhotos(PICS)
        self.a, self.store, _ = make(os.path.join(tempfile.mkdtemp(), "a.db"), photos=self.ph)

    def test_yesterday_range_is_exact(self):
        r = self.a.handle("kal ki photos dikhao")
        self.assertEqual(r.kind, "photos")
        self.assertEqual([i["id"] for i in r.items], [2])
        start, end, _ = self.ph.queries[0]
        self.assertEqual(start, ms(datetime(2026, 11, 19, 0, 0, tzinfo=TZ)))
        self.assertEqual(end, ms(datetime(2026, 11, 20, 0, 0, tzinfo=TZ)))

    def test_keyword_and_all(self):
        self.assertEqual([i["id"] for i in self.a.handle("camera ki photos").items], [1, 3])
        self.assertEqual([i["id"] for i in self.a.handle("pichle hafte ke screenshots").items], [2])
        self.assertIn("No photos found", self.a.handle("goa ki photos dikhao").text)

    def test_open_only_listed_photo(self):
        self.a.handle("aaj ki photos")
        self.assertEqual(self.a.open_photo(3).kind, "error")  # not in last results
        self.assertIn("Opened the photo", self.a.open_photo(1).text)
        self.assertEqual(self.ph.opened, [1])

    def test_permission_denied_and_partial(self):
        a, _, _ = make(os.path.join(tempfile.mkdtemp(), "a.db"), photos=FakePhotos(PICS, perm="denied"))
        r = a.handle("aaj ki photos")
        self.assertEqual((r.kind, r.permissions), ("need_permission", ["android.permission.READ_MEDIA_IMAGES"]))
        a, _, _ = make(os.path.join(tempfile.mkdtemp(), "a.db"), photos=FakePhotos(PICS, perm="partial"))
        self.assertIn("you gave access to", a.handle("aaj ki photos").text)

    def test_audit_has_only_count(self):
        self.a.handle("camera ki photos")
        rows = str(self.store.audit_rows())
        self.assertIn("count=2", rows)
        self.assertNotIn("IMG_1", rows)

    def test_unsupported_on_desktop(self):
        a, _, _ = make(os.path.join(tempfile.mkdtemp(), "a.db"))
        self.assertEqual(a.handle("aaj ki photos").kind, "unsupported")


class Parsing(unittest.TestCase):
    P = ConstrainedParser()
    TODAY = date(2026, 11, 20)

    def v(self, text):
        return validate(self.P.parse(text, self.TODAY), self.TODAY)

    def test_acceptance_phrases(self):
        self.assertEqual(self.v("Yaad rakho mujhe subah kaam karna pasand hai.").intent, "remember_preference")
        i = self.v("Note karo: project report mein budget section add karna hai")
        self.assertEqual((i.intent, i.entities["text"]), ("add_note", "project report mein budget section add karna hai"))
        i = self.v("Project report ke baare mein maine kya note kiya tha?")
        self.assertEqual((i.intent, i.entities["query"]), ("query_notes", "project report"))
        i = self.v("Kal project par 45 minutes kaam karne ka time nikalo.")
        self.assertEqual(i.intent, "schedule_work")
        self.assertEqual(i.entities["title"], "project")
        self.assertEqual(i.entities["duration_minutes"], 45)
        self.assertEqual(i.entities["date"], "2026-11-21")
        self.assertTrue(i.requires_approval)
        self.assertEqual(i.missing_fields, [])

    def test_unsupported_and_unknown(self):
        self.assertEqual(self.v("rahul ko call karo").intent, "call_contact")
        self.assertEqual(self.v("wifi band karo").intent, "change_setting")
        self.assertEqual(self.v("blah").intent, "unknown")

    def test_validation_rejects_untrusted_output(self):
        t = self.TODAY
        self.assertEqual(validate({"intent": "rm -rf"}, t).intent, "unknown")
        self.assertEqual(validate("junk", t).intent, "unknown")
        i = validate({"intent": "schedule_work", "requires_approval": False,
                      "entities": {"title": "x" * 999, "date": "2099-01-01", "duration_minutes": 99999,
                                   "time": "25:99", "window": "midnight"}}, t)
        self.assertEqual(len(i.entities["title"]), 120)
        for bad in ("date", "duration_minutes", "time", "window"):
            self.assertNotIn(bad, i.entities)
        self.assertTrue(i.requires_approval)  # model cannot turn approval off
        self.assertIn("date", i.missing_fields)


class Crypt(unittest.TestCase):
    def test_no_plaintext_on_disk_and_wrong_key_fails(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "a.db")
        s = Store(p, Crypto(KEY))
        s.put("note", {"text": "SECRETBUDGETPHRASE"}, vector_text="SECRETBUDGETPHRASE")
        s.db.commit()
        s.db.close()
        raw = open(p, "rb").read()
        self.assertNotIn(b"SECRETBUDGETPHRASE", raw)
        s2 = Store(p, Crypto(bytes(32)))
        with self.assertRaises(Exception):
            s2.all("note")

    def test_delete_all_leaves_no_old_bytes_on_disk(self):
        p = os.path.join(tempfile.mkdtemp(), "a.db")
        s = Store(p, Crypto(KEY))
        for i in range(30):
            rid = s.put("note", {"text": "n%d" % i}, vector_text="n%d" % i)
            s.audit(rid, "AUDITMARKER_%d" % i, "n/a", "done")
        blob_before = s.db.execute("SELECT data FROM records LIMIT 1").fetchone()[0]
        s.delete_all()
        s.db.close()
        raw = open(p, "rb").read()
        self.assertNotIn(b"AUDITMARKER", raw)
        self.assertNotIn(blob_before[:16], raw)  # ciphertext of deleted rows is gone too

    def test_single_delete_is_overwritten(self):
        p = os.path.join(tempfile.mkdtemp(), "a.db")
        s = Store(p, Crypto(KEY))
        rid = s.put("note", {"text": "x"})
        blob = s.db.execute("SELECT data FROM records").fetchone()[0]
        s.delete(rid)
        s.db.close()
        self.assertNotIn(blob[:16], open(p, "rb").read())

    def test_dev_key_refused_unless_explicit(self):
        os.environ.pop("PA_ALLOW_INSECURE_DEV_KEY", None)
        with self.assertRaises(KeyUnavailable):
            DevFileKeyProvider(os.path.join(tempfile.mkdtemp(), "k")).get_key()

    def test_audit_has_no_content(self):
        a, s, _ = make(os.path.join(tempfile.mkdtemp(), "a.db"))
        a.handle("Note karo: SECRETBODY")
        self.assertNotIn("SECRETBODY", str(s.audit_rows()))


class Backends(unittest.TestCase):
    def test_both_aes_backends_are_interoperable(self):
        a, b = Crypto(KEY, "cryptography"), Crypto(KEY, "pycryptodome")
        self.assertEqual(b.dec(a.enc(b"hello", "x"), "x"), b"hello")
        self.assertEqual(a.dec(b.enc(b"hello", "x"), "x"), b"hello")
        with self.assertRaises(Exception):  # AAD binds blob to its row
            a.dec(b.enc(b"hello", "x"), "y")

    def test_bootstrap_refuses_without_key(self):
        from pa.bootstrap import build_assistant
        os.environ.pop("PA_ALLOW_INSECURE_DEV_KEY", None)
        with self.assertRaises(KeyUnavailable):
            build_assistant(tempfile.mkdtemp())

    def test_bootstrap_works_with_explicit_dev_key(self):
        from pa.bootstrap import build_assistant
        os.environ["PA_ALLOW_INSECURE_DEV_KEY"] = "1"
        try:
            a = build_assistant(tempfile.mkdtemp())
            self.assertIn("Note saved", a.handle("Note karo: hello world").text)
            self.assertEqual(a.handle("Kal project par 45 minutes kaam karne ka time nikalo").kind, "need_info")
        finally:
            os.environ.pop("PA_ALLOW_INSECURE_DEV_KEY", None)


class Planning(unittest.TestCase):
    D = date(2026, 11, 21)

    def test_morning_slot_skips_busy(self):
        busy = [(datetime(2026, 11, 21, 6, 0, tzinfo=TZ), datetime(2026, 11, 21, 9, 0, tzinfo=TZ))]
        r = planner.propose_slot(self.D, 45, "morning", None, busy, NOW)
        self.assertEqual(r["start"], datetime(2026, 11, 21, 9, 0, tzinfo=TZ))
        self.assertEqual(r["end"], datetime(2026, 11, 21, 9, 45, tzinfo=TZ))

    def test_cannot_fit(self):
        busy = [(datetime(2026, 11, 21, 6, 0, tzinfo=TZ), datetime(2026, 11, 21, 12, 0, tzinfo=TZ))]
        self.assertFalse(planner.propose_slot(self.D, 45, "morning", None, busy, NOW)["ok"])

    def test_today_not_in_past_and_fixed_time(self):
        r = planner.propose_slot(date(2026, 11, 20), 30, "morning", None, [], NOW)
        self.assertGreaterEqual(r["start"], NOW)
        self.assertFalse(planner.propose_slot(date(2026, 11, 20), 30, None, "08:00", [], NOW)["ok"])
        self.assertTrue(planner.propose_slot(self.D, 30, None, "10:00", [], NOW)["ok"])

    def test_window_priority(self):
        prefs = [{"tags": {"time_of_day": "evening"}}]
        self.assertEqual(planner.resolve_window({"window": "morning"}, prefs), "morning")
        self.assertEqual(planner.resolve_window({}, prefs), "evening")
        self.assertIsNone(planner.resolve_window({}, []))
        self.assertEqual(planner.resolve_window({"time": "10:00", "window": "morning"}, prefs), "fixed")


class Approval(unittest.TestCase):
    def setUp(self):
        self.store = Store(os.path.join(tempfile.mkdtemp(), "a.db"), Crypto(KEY))
        self.cal = FakeCalendar()
        self.eng = ApprovalEngine(self.store, {"calendar_event": self.cal})
        self.pl = {"title": "t", "start_iso": "2026-11-21T06:00:00+05:30", "end_iso": "2026-11-21T06:45:00+05:30"}

    def test_exact_payload_binding(self):
        a, _ = self.eng.propose("calendar_event", self.pl)
        a.payload["title"] = "changed after preview"
        self.assertEqual(self.eng.approve(a.id, a.hash).status, "invalidated")
        self.assertEqual(self.cal.executed, [])

    def test_wrong_hash_never_executes(self):
        a, _ = self.eng.propose("calendar_event", self.pl)
        self.assertEqual(self.eng.approve(a.id, "deadbeef").status, "invalidated")
        self.assertEqual(self.cal.executed, [])

    def test_duplicate_taps_execute_once(self):
        a, _ = self.eng.propose("calendar_event", self.pl)
        self.assertEqual(self.eng.approve(a.id, a.hash).status, "handed_off")
        self.assertEqual(self.eng.approve(a.id, a.hash).status, "duplicate")
        self.assertEqual(len(self.cal.executed), 1)

    def test_concurrent_approvals_execute_once(self):
        a, _ = self.eng.propose("calendar_event", self.pl)
        ts = [threading.Thread(target=self.eng.approve, args=(a.id, a.hash)) for _ in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len(self.cal.executed), 1)

    def test_reject_and_permission_denied_do_nothing(self):
        a, _ = self.eng.propose("calendar_event", self.pl)
        self.assertTrue(self.eng.reject(a.id))
        self.assertEqual(self.eng.approve(a.id, a.hash).status, "duplicate")
        self.cal.perm = "denied"
        b, _ = self.eng.propose("calendar_event", self.pl)
        self.assertEqual(self.eng.approve(b.id, b.hash).status, "denied")
        self.assertEqual(self.cal.executed, [])

    def test_unsupported_adapter_cannot_be_proposed(self):
        with self.assertRaises(Unsupported):
            ApprovalEngine(self.store, {"calendar_event": FakeCalendar(cap=False)}).propose("calendar_event", self.pl)
        with self.assertRaises(Unsupported):
            self.eng.propose("send_message", self.pl)


class Acceptance(unittest.TestCase):
    def test_full_scenario(self):
        path = os.path.join(tempfile.mkdtemp(), "a.db")
        a, store, cal = make(path)
        # 1 preference, 2 note
        self.assertIn("Preference saved", a.handle("Yaad rakho mujhe subah kaam karna pasand hai.").text)
        self.assertIn("Note saved", a.handle("Note karo: project report mein budget section add karna hai").text)
        # unrelated note must not outrank the right one
        a.handle("Note karo: doodh aur bread kharidna hai")
        # 3 retrieval
        r = a.handle("Project report ke baare mein maine kya note kiya tha?")
        self.assertIn("budget section", r.text)
        self.assertNotIn("doodh", r.text)
        # 4 propose slot using the saved morning preference
        r = a.handle("Kal project par 45 minutes kaam karne ka time nikalo.")
        self.assertEqual(r.kind, "proposal")
        self.assertIn("06:00-06:45", r.text)
        self.assertEqual(cal.executed, [])  # nothing happens before approval
        # 5 approve exact action: honest hand-off wording
        out = a.approve(r.action_id, r.action_hash)
        self.assertIn("tap Save there", out.text)
        self.assertEqual(len(cal.executed), 1)
        # 6 restart: data persists
        store.db.close()
        a2, store2, _ = make(path)
        self.assertEqual(len(a2.list_preferences()), 1)
        self.assertEqual(len(a2.list_tasks()), 1)
        self.assertIn("budget section", a2.handle("project report ke baare mein kya note tha?").text)
        # second scheduling avoids the already planned task
        r2 = a2.handle("Kal project par 45 minutes kaam karne ka time nikalo.")
        self.assertIn("06:45-07:30", r2.text)

    def test_reject_changes_nothing(self):
        a, store, cal = make(os.path.join(tempfile.mkdtemp(), "a.db"))
        a.handle("Yaad rakho mujhe subah kaam karna pasand hai.")
        r = a.handle("Kal project par 45 minutes kaam karne ka time nikalo.")
        a.reject(r.action_id)
        self.assertEqual(cal.executed, [])
        self.assertEqual(a.list_tasks(), [])
        self.assertIn("already done", a.approve(r.action_id, r.action_hash).text)
        self.assertEqual(cal.executed, [])

    def test_asks_for_missing_constraint_without_preference(self):
        a, _, cal = make(os.path.join(tempfile.mkdtemp(), "a.db"))
        r = a.handle("Kal project par 45 minutes kaam karne ka time nikalo.")
        self.assertEqual(r.kind, "need_info")
        r = a.handle("shaam")
        self.assertEqual(r.kind, "proposal")
        self.assertIn("17:00-17:45", r.text)

    def test_unknown_calendar_availability_is_disclosed(self):
        a, _, _ = make(os.path.join(tempfile.mkdtemp(), "a.db"), FakeCalendar(busy=None))
        a.handle("Yaad rakho mujhe subah kaam karna pasand hai.")
        self.assertIn("could not check calendar availability", a.handle("Kal project par 45 minutes kaam karne ka time nikalo.").text)

    def test_unsupported_and_temporary(self):
        a, _, cal = make(os.path.join(tempfile.mkdtemp(), "a.db"))
        self.assertEqual(a.handle("rahul ko call karo").kind, "unsupported")
        self.assertIn("temporary", a.handle("Yaad rakho aaj ke liye shaam ko kaam karna").text)
        self.assertEqual(a.list_preferences(), [])

    def test_user_can_correct_and_delete(self):
        a, store, _ = make(os.path.join(tempfile.mkdtemp(), "a.db"))
        a.handle("Yaad rakho mujhe subah kaam karna pasand hai.")
        pid = a.list_preferences()[0]["id"]
        self.assertTrue(a.update_preference(pid, "mujhe shaam ko kaam karna pasand hai"))
        self.assertEqual(a.list_preferences()[0]["tags"]["time_of_day"], "evening")
        self.assertTrue(a.delete_record(pid))
        a.handle("Note karo: kuch")
        a.delete_all_data()
        self.assertEqual((a.list_preferences(), store.all("note")), ([], []))


class Voice(unittest.TestCase):
    def test_chunker_splits_sentences_and_cleans_markup(self):
        from pa.voice import chunk
        self.assertEqual(chunk(""), [])
        parts = chunk("**Hello** there, this is a longer first sentence. Dr. Rao called at 5 pm. "
                      "See https://example.com now!\n\nNew paragraph here.")
        texts = [t for t, _ in parts]
        self.assertTrue(all("**" not in t and "http" not in t for t in texts))
        self.assertIn("Dr. Rao called at 5 pm.", " ".join(texts))  # no split after 'Dr.'
        self.assertTrue(any(end for _, end in parts))               # paragraph pause kept
        self.assertFalse(parts[-1][1])                              # no pause after the last one
        long = chunk("word, " * 200)
        self.assertTrue(all(len(t) <= 260 for t, _ in long))

    def test_settings_roundtrip_and_untrusted_file(self):
        from pa import voice as V
        path = os.path.join(tempfile.mkdtemp(), "voice.json")
        self.assertEqual(V.load_settings(path).profile_id, "nova")  # missing file -> defaults
        s = V.VoiceSettings()
        s.use_profile("atlas")
        s.speak_mode = "always"
        V.save_settings(path, s)
        t = V.load_settings(path)
        self.assertEqual((t.profile_id, t.pitch, t.speak_mode), ("atlas", 0.84, "always"))
        with open(path, "w") as f:
            f.write('{"profile_id": "x", "pitch": 99, "rate": "fast", "speak_mode": "loud", "evil": 1}')
        t = V.load_settings(path)
        self.assertEqual((t.profile_id, t.speak_mode), ("nova", "voice"))
        self.assertLessEqual(t.pitch, V.PITCH_MAX)
        with open(path, "w") as f:
            f.write("not json")
        self.assertEqual(V.load_settings(path).profile_id, "nova")

    def test_speak_modes(self):
        from pa.voice import should_speak, speakable
        self.assertTrue(should_speak("voice", True))
        self.assertFalse(should_speak("voice", False))
        self.assertTrue(should_speak("always", False))
        self.assertFalse(should_speak("off", True))
        self.assertEqual(speakable("Sorry, I did not understand that. Parser: rule parser"),
                         "Sorry, I did not understand that.")

    def test_spoken_choice_picks_contact(self):
        from pa.assistant import _choice_number
        for text, n in (("2", 2), ("two", 2), ("second one", 2), ("dusra wala", 2), ("number 1", 1),
                        ("one", 1), ("pehla", 1), ("Third.", 3)):
            self.assertEqual(_choice_number(text), n, text)
        for text in ("rahul", "1 2", "call rahul sharma please now", ""):
            self.assertIsNone(_choice_number(text), text)
        phone = FakePhone()
        a, _, _ = make(os.path.join(tempfile.mkdtemp(), "a.db"), contacts=FakeContacts(BOOK), phone=phone)
        self.assertEqual(a.handle("rahul ko call karo").kind, "choose")
        a.handle("second one")
        self.assertEqual(len(phone.calls), 1)

    def test_android_voice_is_inert_on_desktop(self):
        from pa.adapters.voice_android import AndroidVoice
        events = []
        v = AndroidVoice(lambda k, x: events.append(k))
        self.assertFalse(v.available())
        v.speak("hello", None)  # must not raise or touch Java
        self.assertFalse(v.is_speaking())
        v.pause()
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
