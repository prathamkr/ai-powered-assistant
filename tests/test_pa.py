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

Assistant.AUTO_SEND_RECHECK = 0  # no waiting in tests

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


class FakeApps(Adapter):  # TEST-ONLY mock
    name = "apps"

    def __init__(self, apps):
        self.apps, self.opened = apps, []

    def capability_check(self):
        return True

    def permission_check(self):
        return "not_required"

    def list_apps(self):
        return self.apps

    def open(self, package):
        self.opened.append(package)
        return Result("handed_off", "app opened")


APPS = [{"label": "WhatsApp", "package": "com.whatsapp"},
        {"label": "WhatsApp Business", "package": "com.whatsapp.w4b"},
        {"label": "YouTube", "package": "com.google.android.youtube"},
        {"label": "YouTube Music", "package": "com.google.android.apps.youtube.music"},
        {"label": "Instagram", "package": "com.instagram.android"},
        {"label": "Camera", "package": "com.android.camera"},
        {"label": "Phone", "package": "com.android.dialer"},
        {"label": "Play Store", "package": "com.android.vending"}]


class OpenApps(unittest.TestCase):
    P, D = ConstrainedParser(), date(2026, 11, 21)

    def app_of(self, text):
        i = validate(self.P.parse(text, self.D), self.D)
        return i.entities.get("app") if i.intent == "open_app" else ("<%s>" % i.intent)

    def test_open_phrases(self):
        for text, app in (("open whatsapp", "whatsapp"), ("Open WhatsApp", "whatsapp"),
                          ("whatsapp kholo", "whatsapp"), ("youtube open karo", "youtube"),
                          ("please open the camera app", "camera"), ("launch play store", "play store"),
                          ("insta chalao", "insta"), ("mera whatsapp khol do", "whatsapp"),
                          ("open phone", "phone"), ("gallery kholo", "gallery")):
            self.assertEqual(self.app_of(text), app, text)

    def test_other_commands_are_not_apps(self):
        self.assertEqual(self.app_of("kal ki photos kholo"), "<find_photos>")
        self.assertEqual(self.app_of("rahul ko call karo"), "<call_contact>")
        self.assertEqual(self.app_of("whatsapp pe message bhejo"), "<send_message>")
        self.assertEqual(self.app_of("Kal project par 45 minutes kaam karne ka time nikalo."), "<schedule_work>")
        self.assertEqual(self.app_of("open 98765"), "<unknown>")

    def test_matching(self):
        from pa.assistant import match_apps
        cases = {"whatsapp": (["WhatsApp"], True), "youtube": (["YouTube"], True),
                 "insta": (["Instagram"], True), "watsapp": (["WhatsApp"], True),
                 "play store": (["Play Store"], True), "you tube": (["YouTube"], True),
                 "whatsapp b": (["WhatsApp Business"], True), "zzzz": ([], True)}
        for q, (labels, sure) in cases.items():
            m, s = match_apps(q, APPS)
            self.assertEqual(([a["label"] for a in m], s), (labels, sure), q)
        m, s = match_apps("tube", APPS)
        self.assertEqual((len(m), s), (2, False))

    def test_open_flow(self):
        apps = FakeApps(APPS)
        a, store, _ = make(os.path.join(tempfile.mkdtemp(), "a.db"), apps=apps)
        r = a.handle("open whatsapp")
        self.assertEqual((r.text, apps.opened), ("Opening WhatsApp.", ["com.whatsapp"]))
        r = a.handle("open tube")
        self.assertEqual(r.kind, "choose")
        r = a.handle("second one")
        self.assertEqual((r.text, apps.opened[-1]), ("Opening YouTube Music.", "com.google.android.apps.youtube.music"))
        r = a.handle("open snapchat")
        self.assertIn("No app called 'snapchat'", r.text)
        self.assertEqual(len(apps.opened), 2)
        self.assertNotIn("whatsapp", str(store.audit_rows()).lower())  # audit has no app names

    def test_unsupported_without_adapter(self):
        a, _, _ = make(os.path.join(tempfile.mkdtemp(), "a.db"))
        self.assertEqual(a.handle("open whatsapp").kind, "unsupported")


class FakeDaily(Adapter):  # TEST-ONLY mock of the Java alarm side
    name = "daily_message"

    def __init__(self, missing=()):
        self.saved, self.missing = {}, list(missing)

    def capability_check(self):
        return True

    def permission_check(self):
        return "not_required"

    def missing_permissions(self, channel):
        return [p for p in self.missing if channel == "sms" or "SMS" not in p]

    def validate(self, p):
        from pa.adapters.daily_android import validate_payload
        return validate_payload(p)

    def preview(self, p):
        from pa.adapters.daily_android import preview_payload
        return preview_payload(p)

    def execute(self, p):
        self.saved[p["sched_id"]] = dict(p)
        return Result("done", "scheduled")

    def cancel(self, sid):
        self.saved.pop(int(sid), None)

    def cancel_all(self):
        self.saved.clear()

    def java_ids(self):
        return set(self.saved)

    def reschedule_all(self):
        return len(self.saved)

    def set_reminder(self, rid, text, at_ms):
        self.saved[rid] = {"reminder": text, "at_ms": at_ms}
        return Result("done", "reminder set")


DAILY_BOOK = [{"name": "Mummy", "number": "9000000001"}, {"name": "Neha", "number": "9000000011"},
              {"name": "Neha 2", "number": "9000000022"}, {"name": "Rahul Sharma", "number": "+91 98765 43210"},
              {"name": "Rahul Verma", "number": "98111 22233"}]


class DailyMessages(unittest.TestCase):
    P, D = ConstrainedParser(), date(2026, 11, 21)

    def ent(self, text):
        i = validate(self.P.parse(text, self.D), self.D)
        self.assertEqual(i.intent, "schedule_message", text)
        self.assertTrue(i.requires_approval)
        return i.entities

    def test_phrases(self):
        cases = {
            "har subah 8 baje mummy ko good morning message karo":
                {"name": "mummy", "time": "08:00", "text": "good morning", "channel": None},
            "every morning at 8 send good morning to mummy on whatsapp":
                {"name": "mummy", "time": "08:00", "text": "good morning", "channel": "whatsapp"},
            "roz raat 10 baje rahul ko 'good night' sms bhejo":
                {"name": "rahul", "time": "22:00", "text": "good night", "channel": "sms"},
            "daily at 7:30 am whatsapp neha 2 saying Good morning ji":
                {"name": "neha 2", "time": "07:30", "text": "Good morning ji", "channel": "whatsapp"},
            "har shaam 6 baje papa ko sms karo ki main nikal gaya":
                {"name": "papa", "time": "18:00", "text": "main nikal gaya", "channel": "sms"},
            'har subah mummy ko "Good morning, have a nice day!" bhejo':
                {"name": "mummy", "time": "08:00", "text": "Good morning, have a nice day!"},
            "every day at 9:15 pm text rahul 9876 saying Take your medicine":
                {"name": "rahul", "prefix": "9876", "time": "21:15", "text": "Take your medicine", "channel": "sms"},
            "roz dopahar 2 baje 9876543210 ko lunch time sms bhejo":
                {"number": "9876543210", "time": "14:00", "text": "lunch time"},
            "send good night to papa every night at 10": {"name": "papa", "time": "22:00", "text": "good night"},
            "har raat mummy ko good night bhejo": {"time": "21:00", "text": "good night"},
            "every day 8 am whatsapp mummy saying good morning": {"time": "08:00", "text": "good morning"},
        }
        for text, want in cases.items():
            e = self.ent(text)
            self.assertEqual({k: e.get(k) for k in want}, want, text)
        e = self.ent("har monday subah 9 baje rahul ko hi bhejo")
        self.assertEqual((e["days"], e["time"], e["name"], e["text"]), ([2], "09:00", "rahul", "hi"))
        e = self.ent("every weekday at 8 am send good morning to mummy on whatsapp")
        self.assertEqual((e["days"], e["text"]), ([2, 3, 4, 5, 6], "good morning"))
        e = self.ent("weekend pe subah 10 baje neha ko hi whatsapp karo")
        self.assertEqual((e["days"], e["name"]), ([1, 7], "neha"))
        self.assertEqual(self.ent("har mahine 1 tarikh ko rahul ko hi bhejo")["repeat"], "unsupported")

    def test_other_commands_unchanged(self):
        for text, intent in (("kal ki photos dikhao", "find_photos"), ("Note: har subah message bhejna hai", "add_note"),
                             ("open whatsapp", "open_app"), ("rahul ko call karo", "call_contact"),
                             ("Kal project par 45 minutes kaam karne ka time nikalo.", "schedule_work")):
            self.assertEqual(self.P.parse(text, self.D)["intent"], intent, text)

    def mk(self, **kw):
        self.daily = FakeDaily(**kw)
        a, self.store, _ = make(os.path.join(tempfile.mkdtemp(), "a.db"),
                                contacts=FakeContacts(DAILY_BOOK), daily=self.daily)
        return a

    def test_full_flow_asks_channel_then_approval_then_saves(self):
        a = self.mk()
        r = a.handle("har subah 8 baje neha ko good morning bhejo")
        self.assertEqual((r.kind, len(r.options)), ("choose", 2))
        r = a.handle("whatsapp")
        self.assertEqual(r.kind, "proposal")
        self.assertIn("08:00", r.text)
        self.assertIn("Neha (9000000011)", r.text)     # exact name: not 'Neha 2'
        self.assertEqual(self.daily.saved, {})         # nothing scheduled before Approve
        out = a.approve(r.action_id, r.action_hash)
        self.assertIn("scheduled for 08:00", out.text)
        self.assertEqual(len(self.daily.saved), 1)
        recs = a.list_schedules()
        self.assertEqual((recs[0]["name"], recs[0]["channel"], recs[0]["text"]), ("Neha", "whatsapp", "good morning"))
        self.assertIn("already", a.approve(r.action_id, r.action_hash).text)  # second tap does nothing
        self.assertEqual(len(self.daily.saved), 1)
        self.assertTrue(a.delete_schedule(recs[0]["id"]))
        self.assertEqual((self.daily.saved, a.list_schedules()), ({}, []))

    def test_reject_schedules_nothing(self):
        a = self.mk()
        r = a.handle("har subah 8 baje mummy ko 'hi' sms bhejo")
        self.assertEqual(r.kind, "proposal")
        a.reject(r.action_id)
        self.assertEqual((self.daily.saved, a.list_schedules()), ({}, []))

    def test_permissions_asked_first(self):
        a = self.mk(missing=["android.permission.SEND_SMS", "android.permission.POST_NOTIFICATIONS"])
        r = a.handle("har subah 8 baje mummy ko 'hi' sms bhejo")
        self.assertEqual(r.kind, "need_permission")
        self.assertIn("android.permission.SEND_SMS", r.permissions)
        r = a.handle("har subah 8 baje mummy ko 'hi' whatsapp karo")
        self.assertEqual(r.permissions, ["android.permission.POST_NOTIFICATIONS"])

    def test_ambiguous_contact_asks(self):
        a = self.mk()
        r = a.handle("roz raat 10 baje rahul ko 'good night' sms bhejo")
        self.assertEqual((r.kind, len(r.options)), ("choose", 2))
        r = a.handle("2")
        self.assertEqual(r.kind, "proposal")
        self.assertIn("Rahul Verma", r.text)

    def test_missing_parts(self):
        a = self.mk()
        self.assertEqual(a.handle("har subah mummy ko message karo").kind, "need_info")   # no text
        self.assertEqual(a.handle("har mahine subah 9 baje mummy ko 'hi' sms bhejo").kind, "unsupported")
        r = a.handle("har monday subah 9 baje mummy ko 'hi' sms bhejo")
        self.assertIn("Every Monday at 09:00", r.text)
        self.assertIn("No contact", a.handle("har subah 8 baje zzqx ko 'hi' sms bhejo").text)

    def test_resume_and_delete_all(self):
        a = self.mk()
        r = a.handle("har subah 8 baje mummy ko 'hi' sms bhejo")
        a.approve(r.action_id, r.action_hash)
        sid = next(iter(self.daily.saved))
        self.daily.saved.clear()              # e.g. alarms lost after a force-stop
        self.daily.saved[999] = {"x": 1}      # stale Java entry without a record
        self.assertEqual(a.resume_schedules(), 1)
        self.assertEqual(set(self.daily.saved), {sid})
        a.delete_all_data()
        self.assertEqual((self.daily.saved, a.list_schedules()), ({}, []))
        self.assertNotIn("Mummy", str(self.store.audit_rows()))

    def test_battery_exemption_requested_after_approval(self):
        a = self.mk()
        self.daily.battery_exempt = lambda: False
        r = a.handle("har subah 8 baje mummy ko 'hi' sms bhejo")
        out = a.approve(r.action_id, r.action_hash)
        self.assertEqual(out.extra, "battery_exemption")
        self.assertIn("run in the background", out.text)
        self.daily.battery_exempt = lambda: True
        r = a.handle("har raat 10 baje mummy ko 'bye' sms bhejo")
        self.assertIsNone(a.approve(r.action_id, r.action_hash).extra)

    def test_payload_validation(self):
        from pa.adapters.daily_android import validate_payload
        ok = {"sched_id": 5, "channel": "sms", "number": "9000000001", "name": "Mummy", "text": "hi", "time": "08:00"}
        self.assertEqual(validate_payload(ok), [])
        for k, v in (("channel", "email"), ("number", "tel:*#06#"), ("time", "25:00"), ("text", "x" * 501),
                     ("sched_id", 0), ("name", " ")):
            self.assertTrue(validate_payload(dict(ok, **{k: v})), k)


class FakeAlarms(Adapter):  # TEST-ONLY mock
    name = "alarms"

    def __init__(self):
        self.alarms, self.timers, self.shown = [], [], 0

    def capability_check(self):
        return True

    def set_alarm(self, h, m, label=None, days=None):
        self.alarms.append((h, m, label, days))
        return Result("handed_off")

    def set_timer(self, secs, label=None):
        self.timers.append(secs)
        return Result("handed_off")

    def show_alarms(self):
        self.shown += 1
        return Result("handed_off")


class Alarms(unittest.TestCase):
    def mk(self):
        self.al = FakeAlarms()
        a, _, _ = make(os.path.join(tempfile.mkdtemp(), "a.db"), alarms=self.al)
        return a

    def test_alarm_phrases(self):
        a = self.mk()
        for text, want, reply in (
                ("set an alarm of 5 am", (5, 0, None, None), "Alarm set for 5:00 AM in your Clock app."),
                ("subah 5 baje ka alarm lagao", (5, 0, None, None), None),
                ("wake me up at 6:30", (6, 30, None, None), None),
                ("alarm 5:45 pm", (17, 45, None, None), "Alarm set for 5:45 PM in your Clock app."),
                ("raat 11 baje alarm laga do", (23, 0, None, None), None),
                ("set an alarm at 6 am for gym", (6, 0, "gym", None), None),
                ("har din 6 baje ka alarm", (6, 0, None, [1, 2, 3, 4, 5, 6, 7]),
                 "Alarm set for 6:00 AM every day in your Clock app.")):
            r = a.handle(text)
            self.assertEqual(self.al.alarms[-1], want, text)
            if reply:
                self.assertEqual(r.text, reply)

    def test_asks_time_then_sets(self):
        a = self.mk()
        r = a.handle("set an alarm")
        self.assertEqual(r.kind, "need_info")
        a.handle("5 am")
        self.assertEqual(self.al.alarms, [(5, 0, None, None)])

    def test_pending_question_does_not_swallow_a_new_command(self):
        a = self.mk()
        self.assertEqual(a.handle("set a timer").kind, "need_info")
        r = a.handle("kal pa test par 30 minutes kaam karne ka time nikalo")   # a new command, not "30 minutes"
        self.assertEqual(self.al.timers, [])
        self.assertNotIn("Timer set", r.text)
        a.handle("set a timer")
        a.handle("10 minutes")                                                # a bare answer still works
        self.assertEqual(self.al.timers, [600])

    def test_timer_and_show(self):
        a = self.mk()
        self.assertEqual(a.handle("10 minute ka timer lagao").text, "Timer set for 10 minutes.")
        a.handle("timer 1 hour 30 minutes")
        self.assertEqual(self.al.timers, [600, 5400])
        a.handle("show my alarms")
        self.assertEqual(self.al.shown, 1)

    def test_other_commands_unchanged(self):
        P, d = ConstrainedParser(), date(2026, 11, 21)
        for text, intent in (("har subah 8 baje mummy ko good morning message karo", "schedule_message"),
                             ("open clock", "open_app"), ("rahul ko call karo", "call_contact"),
                             ("Kal project par 45 minutes kaam karne ka time nikalo.", "schedule_work")):
            self.assertEqual(P.parse(text, d)["intent"], intent, text)


class FakeDevice(Adapter):  # TEST-ONLY mock of the phone status reader
    name = "device_info"

    def __init__(self, battery=80, charging=False, next_alarm_ms=None):
        self.battery, self.charging, self.next_alarm_ms = battery, charging, next_alarm_ms

    def capability_check(self):
        return True

    def get(self, cat):
        return {"battery": {"level": self.battery, "charging": self.charging, "temp_c": 31.5},
                "storage": {"total": 128e9, "free": 6e9, "used_pct": 95},
                "memory": {"total": 6e9, "free": 2e9, "low": False},
                "device": {"maker": "vivo", "model": "I2219", "android": "16", "api": 36, "patch": "2026-10-01"},
                "screen": {"brightness_pct": 40, "auto": True, "dark": True},
                "network": {"online": False, "type": None},
                "alarm": {"next_ms": self.next_alarm_ms}}[cat]


class Everyday(unittest.TestCase):
    """Phone status, to-dos/reminders, the day's plan, routines, compound commands, context."""

    def mk(self, **kw):
        self.daily, self.apps, self.al = FakeDaily(), FakeApps(APPS), FakeAlarms()
        self.phone, self.dev = FakePhone(), kw.pop("device", FakeDevice())
        a, self.store, self.cal = make(os.path.join(tempfile.mkdtemp(), "a.db"), cal=FakeCalendar(),
                                       contacts=FakeContacts(BOOK), phone=self.phone, daily=self.daily,
                                       apps=self.apps, alarms=self.al, device=self.dev)
        return a

    def test_phone_status(self):
        a = self.mk(device=FakeDevice(battery=15))
        self.assertEqual(a.handle("battery kitni hai").text,
                         "Battery: 15%, not charging, 31.5°C. Battery is low: charge the phone soon.")
        self.assertIn("almost full", a.handle("storage kitna bacha hai").text)
        self.assertIn("Android 16", a.handle("phone details batao").text)
        self.assertIn("works fully offline", a.handle("is internet working?").text)
        self.assertIn("dark mode on", a.handle("brightness kitni hai").text)
        self.assertEqual(a.handle("agla alarm kab hai").text, "No alarm is set.")
        self.assertTrue(a.handle("what time is it").text.startswith("It is "))

    def test_reminder_sets_one_time_alarm(self):
        a = self.mk()   # NOW = 2026-11-20 10:00 +05:30
        r = a.handle("mujhe kal 5 baje yaad dilana ki bill bharna hai")
        self.assertEqual(r.text, "Reminder set for tomorrow 5:00 PM: bill bharna hai")
        (rid, saved), = self.daily.saved.items()
        self.assertEqual(saved["reminder"], "bill bharna hai")
        at = datetime.fromtimestamp(saved["at_ms"] / 1000, NOW.tzinfo)
        self.assertEqual((at.date(), at.hour), ((NOW + timedelta(days=1)).date(), 17))
        a.handle("remind me at 6 am to drink water")      # 6 am already passed today -> tomorrow
        self.assertIn("drink water (tomorrow 6:00 AM)", a.handle("show my todos").text)
        self.assertEqual(a.resume_schedules(), 2)          # reminders are not treated as stale
        self.assertEqual(len(self.daily.saved), 2)

    def test_todos_list_done_and_priority(self):
        a = self.mk()
        a.handle("todo: buy milk")
        a.handle("add todo pay electricity bill tomorrow high priority")
        a.handle("doodh lana todo list mein daalo")
        txt = a.handle("show my todos").text
        self.assertTrue(txt.startswith("Your to-dos:\n1. pay electricity bill (high, tomorrow)"), txt)
        self.assertEqual(a.handle("todo 1 done").text, "Done: pay electricity bill")
        self.assertEqual(a.handle("mark buy milk done").text, "Done: buy milk")
        self.assertEqual([t["text"] for t in a.list_todos()], ["doodh lana"])
        self.assertIn("No open to-do", a.handle("mark zzz done").text)

    def test_plan_day_suggests_free_slot(self):
        a = self.mk(device=FakeDevice(battery=25))
        a.handle("add todo pay electricity bill today high priority")
        a.handle("remind me at 6 pm to drink water")
        self.cal._busy = [(NOW.replace(hour=10, minute=0), NOW.replace(hour=11, minute=30))]
        txt = a.handle("aaj ka plan kya hai").text
        self.assertIn("10:00-11:30 busy (calendar)", txt)
        self.assertIn("18:00 drink water", txt)
        self.assertIn("battery is 25%", txt)
        self.assertIn("Suggestion: do 'pay electricity bill' at 09:00-09:30", txt)  # free before the 10:00 meeting
        a.handle("Yaad rakho mujhe shaam ko kaam karna pasand hai")
        self.assertIn("at 17:00-17:30 (first free 30 minutes, your preferred evening)", a.handle("plan my day").text)

    def test_routine_create_run_and_by_name(self):
        a = self.mk()
        r = a.handle("routine good morning: set an alarm for 7 am; battery kitni hai then open whatsapp")
        self.assertIn("Saved routine 'good morning' (3 steps)", r.text)
        r = a.handle("good morning")                       # just the name runs it
        self.assertTrue(r.text.startswith("Routine 'good morning' done:"), r.text)
        self.assertEqual(self.al.alarms[-1][:2], (7, 0))
        self.assertEqual(self.apps.opened, ["com.whatsapp"])
        a.handle("run good morning routine")
        self.assertEqual(len(self.al.alarms), 2)
        self.assertIn("do not understand", a.handle("routine bad: blah blah; open whatsapp").text)
        self.assertIn("Deleted routine", a.handle("delete routine good morning").text)
        self.assertIn("No routine called", a.handle("run good morning routine").text)

    def test_compound_commands(self):
        a = self.mk()
        r = a.handle("set an alarm for 6 am and battery kitni hai then open youtube and open whatsapp")
        self.assertEqual(self.al.alarms, [(6, 0, None, None)])
        self.assertEqual(self.apps.opened, ["com.google.android.youtube"])  # 2nd app would cut the 1st off
        self.assertIn("Not run because another app is already open: open whatsapp", r.text)
        a.handle("Note: buy eggs and milk")                # free text is never split
        self.assertEqual(self.store.all("note")[0]["text"], "buy eggs and milk")

    def test_weekly_message_payload_and_plan(self):
        a = self.mk()
        r = a.handle("every weekday at 8 pm send good night to mummy by sms")
        self.assertIn("Every weekday (Mon-Fri) at 20:00", r.text)
        a.approve(r.action_id, r.action_hash)
        (saved,) = self.daily.saved.values()
        self.assertEqual(saved["days"], [2, 3, 4, 5, 6])
        from pa.adapters.daily_android import days_mask, days_text
        self.assertEqual((days_mask([2, 6]), days_mask(None), days_mask(list(range(1, 8)))), (0b100010, 0, 0))
        self.assertEqual((days_text([1, 7]), days_text([2, 6])), ("weekend day", "Monday, Friday"))
        self.assertIn("20:00 daily SMS to Mummy", a.handle("aaj ka plan").text)   # NOW is a Friday
        a.handle("har sunday shaam 6 baje mummy ko 'hi' sms bhejo")
        self.assertNotIn("18:00", a.handle("aaj ka plan").text)                   # not on Friday

    def test_timed_routine(self):
        a = self.mk()
        self.daily.set_routine_trigger = lambda sid, name, time, days=None: (
            self.daily.saved.__setitem__(sid, {"routine": name, "time": time, "days": days}) or Result("done"))
        self.assertIn("No routine called", a.handle("good morning routine har din 7 baje").text)
        a.handle("routine good morning: battery kitni hai; open whatsapp")
        r = a.handle("good morning routine weekdays subah 7 baje chalao")
        self.assertIn("Every weekday (Mon-Fri) at 07:00", r.text)
        (sid, saved), = self.daily.saved.items()
        self.assertEqual(saved, {"routine": "good morning", "time": "07:00", "days": [2, 3, 4, 5, 6]})
        a.handle("schedule good morning routine every day at 6 am")     # replaces the old time
        self.assertEqual([v["time"] for v in self.daily.saved.values()], ["06:00"])
        self.assertEqual(a.resume_schedules(), 1)                         # trigger kept on app start
        self.assertIn("no longer run", a.handle("stop good morning routine").text)
        self.assertEqual(self.daily.saved, {})
        a.handle("schedule good morning routine every day at 6 am")
        a.handle("delete routine good morning")                           # deleting also stops the timer
        self.assertEqual(self.daily.saved, {})

    def test_timed_features_ask_for_background(self):
        a = self.mk()
        self.daily.battery_exempt = lambda: False
        r = a.handle("remind me at 6 pm to drink water")
        self.assertEqual(r.extra, "battery_exemption")
        self.assertIn("allow Lazey to run in the background", r.text)
        self.daily.battery_exempt = lambda: True
        self.assertIsNone(a.handle("remind me at 7 pm to call papa").extra)

    def test_did_you_mean(self):
        a = self.mk()
        self.assertEqual(a.handle("mujhe alarm chahiye kal").kind, "need_info")  # understood: asks the time
        r = a.handle("mujhe doodh lena bhoolna nahi hai")
        self.assertTrue(r.text.startswith("Sorry, I did not understand that. Try:\n- remind me at 6 pm"), r.text)
        self.assertIn("- ", a.handle("xyz qwerty").text)

    def test_usko_means_last_contact_but_asks_first(self):
        a = self.mk()
        self.assertEqual(a.handle("usko call karo").kind, "need_info")      # nobody yet
        a.handle("mummy ko call karo")
        r = a.handle("usko phir se call karo")
        self.assertEqual((r.kind, r.text), ("choose", "Call Mummy (9000000001) again? Say 1 or yes."))
        self.assertEqual(len(self.phone.calls), 1)                          # not called yet
        a.handle("haan")
        self.assertEqual([c["number"] for c in self.phone.calls], ["9000000001", "9000000001"])
        a.handle("usko call karo")
        self.assertEqual(a.handle("nahi").text, "Okay, nothing was done.")
        self.assertEqual(len(self.phone.calls), 2)

    def test_proposal_alone_does_not_become_last_contact(self):
        # phone test: an SMS card that was never approved made "usko call karo" dial that number
        msg = FakeMessages()
        a, _, _ = make(os.path.join(tempfile.mkdtemp(), "a.db"), contacts=FakeContacts(BOOK),
                       phone=FakePhone(), messages=msg)
        r = a.handle("send hi to 9000000077 by sms")
        self.assertEqual(r.kind, "proposal")
        r = a.handle("usko call karo")
        self.assertEqual(r.kind, "need_info")                                # asks who, calls no one


class ChatHistory(unittest.TestCase):
    def test_saved_encrypted_ordered_trimmed_cleared(self):
        path = os.path.join(tempfile.mkdtemp(), "a.db")
        a, store, _ = make(path)
        for i in range(5):
            a.log_chat("user", "> secret line %d" % i)
            a.log_chat("bot", "reply %d" % i)
        a.log_chat("evil", "ignored")
        h = a.chat_history()
        self.assertEqual([x["text"] for x in h][:2], ["> secret line 0", "reply 0"])
        self.assertEqual((len(h), h[-1]["text"]), (10, "reply 4"))
        self.assertEqual(len(a.chat_history(limit=3)), 3)
        with open(path, "rb") as f:
            self.assertNotIn(b"secret line", f.read())          # encrypted on disk
        a.CHAT_KEEP = 4
        self.assertEqual([x["text"] for x in a.chat_history()], ["> secret line 3", "reply 3",
                                                                "> secret line 4", "reply 4"])
        a.clear_chat()
        self.assertEqual(a.chat_history(), [])
        a.log_chat("user", "> again")
        a.delete_all_data()
        self.assertEqual(a.chat_history(), [])


class FakeMessages(Adapter):  # TEST-ONLY mock
    name = "sms_message"

    def __init__(self, sms_perm=True):
        self.sms_perm, self.sent, self.whatsapp = sms_perm, [], []

    def capability_check(self):
        return True

    def permission_check(self):
        return "granted" if self.sms_perm else "denied"

    def required_permissions(self):
        return ["android.permission.SEND_SMS"]

    def validate(self, p):
        from pa.adapters.messages import validate_sms
        return validate_sms(p)

    def preview(self, p):
        from pa.adapters.messages import preview_sms
        return preview_sms(p)

    def execute(self, p):
        self.sent.append(dict(p))
        return Result("done", "sms handed to the phone")

    def open_whatsapp(self, number, text):
        self.whatsapp.append((number, text))
        return Result("handed_off", "whatsapp chat opened")

    auto, armed, result = False, None, None
    wa_calls, not_on_whatsapp = None, ()

    def whatsapp_call(self, number, video=False):
        if self.wa_calls is None:
            self.wa_calls = []
        if number in self.not_on_whatsapp:
            return Result("failed", "not_on_whatsapp")
        self.wa_calls.append((number, video))
        return Result("done", "whatsapp call started")

    def auto_send_ready(self):
        return self.auto

    def arm_auto_send(self, text):
        self.armed = text

    def take_auto_send_result(self):
        r, self.result = self.result, None
        return r


class SendNow(unittest.TestCase):
    P, D = ConstrainedParser(), date(2026, 11, 21)

    def mk(self, **kw):
        self.msg = FakeMessages(**kw)
        a, self.store, _ = make(os.path.join(tempfile.mkdtemp(), "a.db"), contacts=FakeContacts(DAILY_BOOK),
                                phone=FakePhone(), messages=self.msg)
        return a

    def test_phrases(self):
        cases = {
            "Open WhatsApp and send Neha a message hi": {"name": "neha", "text": "hi", "channel": "whatsapp"},
            "Send Neha a message from Airtel hi": {"name": "neha", "text": "hi", "channel": "sms", "sim": "airtel"},
            "neha ko hi message karo": {"name": "neha", "text": "hi", "channel": None},
            "neha 2 ko whatsapp pe good night bhejo": {"name": "neha 2", "text": "good night", "channel": "whatsapp"},
            "send good morning to mummy on whatsapp": {"name": "mummy", "text": "good morning"},
            "message rahul saying I will call you later": {"name": "rahul", "text": "I will call you later"},
            "send a message to papa saying reached home": {"name": "papa", "text": "reached home"},
            "rahul ko sms karo ki main aa raha hun": {"name": "rahul", "text": "main aa raha hun", "channel": "sms"},
            "send hi to 9876543210 by sms": {"number": "9876543210", "text": "hi", "channel": "sms"},
            'mummy ko "Khana kha liya?" sim 2 se sms bhejo': {"name": "mummy", "text": "Khana kha liya?", "sim": "2"},
        }
        for text, want in cases.items():
            i = validate(self.P.parse(text, self.D), self.D)
            self.assertEqual(i.intent, "send_message", text)
            self.assertEqual({k: i.entities.get(k) for k in want}, want, text)
        for text, intent in (("open whatsapp", "open_app"), ("whatsapp kholo", "open_app"),
                             ("rahul ko call karo", "call_contact"), ("kal ki photos dikhao", "find_photos"),
                             ("har subah 8 baje mummy ko 'hi' bhejo", "schedule_message")):
            self.assertEqual(self.P.parse(text, self.D)["intent"], intent, text)

    def test_auto_send_switch_command(self):
        # "auto send on karo" offers the switch when it is off, and says ON when it is on
        for text in ("auto send on karo", "turn on auto-send", "autosend chalu karo", "is auto send on?",
                     "enable whatsapp auto send"):
            self.assertEqual(self.P.parse(text, self.D)["intent"], "auto_send", text)
        a = self.mk()
        self.msg.auto = False
        r = a.handle("auto send on karo")
        self.assertIn("OFF", r.text)
        self.assertEqual(r.extra, "auto_send_setup")
        self.msg.auto = True
        r = a.handle("auto send on karo")
        self.assertIn("ON", r.text)
        self.assertEqual(r.extra, "auto_send_settings")
        self.assertEqual(self.msg.whatsapp, [])  # nothing was opened or sent

    def test_auto_send_waits_after_settings_screen(self):
        # vivo: the Settings screen switches the service off; it comes back ~10 s later by itself.
        # Right after that screen the app keeps looking instead of answering OFF at once.
        a = self.mk()
        a.AUTO_SEND_RECHECK, a.AUTO_SEND_SETTLE = 0.01, 0.5
        calls = {"n": 0}

        def comes_back():
            calls["n"] += 1
            return calls["n"] >= 5
        self.msg.auto_send_ready = comes_back
        import time as _t
        self.msg.settings_opened_at = _t.time()
        self.assertIn("ON", a.handle("is auto send on?").text)
        calls["n"] = -1000   # stays off: answers OFF after the wait
        self.assertIn("OFF", a.handle("is auto send on?").text)
        self.msg.settings_opened_at = 0   # long ago: only a quick second look, no long wait
        calls["n"] = -3                   # (would come back on the 8th look)
        self.assertIn("OFF", a.handle("is auto send on?").text)

    def test_whatsapp_opens_chat_without_sending(self):
        a = self.mk()
        r = a.handle("Open WhatsApp and send Neha a message hi")
        self.assertIn("press Send", r.text)
        self.assertEqual(self.msg.whatsapp, [("9000000011", "hi")])   # exact 'Neha', not 'Neha 2'
        self.assertEqual(self.msg.sent, [])

    def test_sms_needs_approval_and_uses_sim(self):
        a = self.mk()
        r = a.handle("Send Neha a message from Airtel hi")
        self.assertEqual(r.kind, "proposal")
        self.assertIn("SIM 2 (Airtel)", r.text)
        self.assertEqual(self.msg.sent, [])                     # nothing before Approve
        out = a.approve(r.action_id, r.action_hash)
        self.assertIn("SMS handed to the phone", out.text)
        self.assertEqual((self.msg.sent[0]["number"], self.msg.sent[0]["sim_slot"]), ("9000000011", 2))
        a.approve(r.action_id, r.action_hash)                   # second tap: nothing more
        self.assertEqual(len(self.msg.sent), 1)

    def test_reject_sends_nothing(self):
        a = self.mk()
        r = a.handle("rahul verma ko sms karo ki hi")
        a.reject(r.action_id)
        self.assertEqual(self.msg.sent, [])

    def test_asks_channel_and_contact(self):
        a = self.mk()
        r = a.handle("rahul ko hi message karo")
        self.assertEqual(r.kind, "choose")
        r = a.handle("whatsapp")
        self.assertEqual((r.kind, len(r.options)), ("choose", 2))  # two Rahuls
        r = a.handle("second one")
        self.assertEqual(self.msg.whatsapp, [("98111 22233", "hi")])

    def test_permission_and_wrong_sim(self):
        a = self.mk(sms_perm=False)
        r = a.handle("rahul verma ko sms karo ki hi")
        self.assertEqual((r.kind, r.permissions), ("need_permission", ["android.permission.SEND_SMS"]))
        a = self.mk()
        r = a.handle("Send Neha a message from bsnl hi")
        self.assertIn("No message was sent", r.text)
        self.assertEqual(self.msg.sent, [])

    def test_speech_style_name_then_text(self):
        # what the offline recognizer wrote on the phone: "message <name> on whatsapp hi"
        book = DAILY_BOOK + [{"name": "Aman", "number": "9000000044"}]
        msg = FakeMessages()
        a, _, _ = make(os.path.join(tempfile.mkdtemp(), "a.db"), contacts=FakeContacts(book),
                       phone=FakePhone(), messages=msg)
        a.handle("message aman on whatsapp hi")
        a.handle("message neha 2 on what's app good night")
        a.handle("Message Rahul Verma on WhatsApp see you at 5")
        self.assertEqual(msg.whatsapp, [("9000000044", "hi"), ("9000000022", "good night"),
                                        ("98111 22233", "see you at 5")])

    def test_auto_send(self):
        a = self.mk()
        r = a.handle("send a message hi to mummy on whatsapp")
        self.assertEqual(r.extra, "auto_send_setup")             # off: user presses Send, offer setup
        self.assertIsNone(self.msg.armed)
        self.assertIsNone(a.auto_send_report())                   # nothing was awaited
        self.msg.auto = True
        r = a.handle("send a message good night to mummy on whatsapp")
        self.assertEqual((r.extra, self.msg.armed), ("await_auto_send", "good night"))  # armed with exact text
        self.msg.result = "waiting"
        self.assertIsNone(a.auto_send_report())                   # still within the window
        self.msg.result = "sent"
        self.assertEqual(a.auto_send_report().text, "WhatsApp message sent to Mummy.")
        a.handle("send a message hi to neha on whatsapp")
        self.msg.result = "timeout"
        self.assertIn("Not sent", a.auto_send_report().text)

    def test_whatsapp_calls(self):
        a = self.mk()
        for text, want in (("call neha on whatsapp", ("9000000011", False)),
                           ("neha 2 ko whatsapp pe call karo", ("9000000022", False)),
                           ("whatsapp video call neha", ("9000000011", True))):
            r = a.handle(text)
            self.assertEqual(self.msg.wa_calls[-1], want, text)
            self.assertTrue(r.text.startswith("Starting a WhatsApp"), r.text)
        r = a.handle("call rahul on whatsapp")                 # two Rahuls -> asks
        self.assertEqual(r.kind, "choose")
        a.handle("2")
        self.assertEqual(self.msg.wa_calls[-1], ("98111 22233", False))
        r = a.handle("usko whatsapp call karo")                # context -> asks first
        self.assertTrue(r.text.startswith("WhatsApp-call Rahul Verma"), r.text)
        self.assertEqual(len(self.msg.wa_calls), 4)
        self.msg.not_on_whatsapp = ("9000000001",)
        r = a.handle("call mummy on whatsapp")                 # not on WhatsApp -> opens the chat instead
        self.assertIn("Opened the chat", r.text)
        self.assertEqual(self.msg.whatsapp[-1], ("9000000001", ""))
        self.assertIn("No contact found", a.handle("call zzqx on whatsapp").text)

    def test_one_line_english_orders(self):
        book = DAILY_BOOK + [{"name": "Aman", "number": "9000000044"}]
        for text in ("send a message hi to aman on whatsapp", "Send a message hi to Aman on WhatsApp.",
                     "send message hi to aman on whatsapp", "send a whatsapp message hi to aman",
                     "send a hi message to aman on whatsapp", "send a message saying hi to aman on whatsapp",
                     "on whatsapp send a message hi to aman", "send aman a message hi on whatsapp",
                     "whatsapp aman hi", "send a message to aman hi on whatsapp",
                     "send a message to aman on whatsapp saying hi", "send hi to aman on whatsapp",
                     "message aman on whatsapp hi"):
            msg = FakeMessages()
            a, _, _ = make(os.path.join(tempfile.mkdtemp(), "a.db"), contacts=FakeContacts(book),
                           phone=FakePhone(), messages=msg)
            r = a.handle(text)
            self.assertEqual(msg.whatsapp, [("9000000044", "hi")], "%s -> %s" % (text, r.text))
        i = validate(self.P.parse("send a message hi how are you to aman on whatsapp", self.D), self.D)
        self.assertEqual((i.entities["name"], i.entities["text"]), ("aman", "hi how are you"))
        self.assertEqual(self.P.parse("I want to go to market", self.D)["intent"], "unknown")

    def test_asks_one_thing_at_a_time_and_remembers(self):
        a = self.mk()
        r = a.handle("whatsapp pe message bhejo")
        self.assertEqual((r.kind, r.text), ("need_info", "Who should get the message?"))
        r = a.handle("mummy")
        self.assertIn("What should the message to mummy say?", r.text)
        a.handle("hii")
        self.assertEqual(self.msg.whatsapp, [("9000000001", "hii")])
        r = a.handle("message to neha on whatsapp")      # text missing
        self.assertEqual(r.kind, "need_info")
        r = a.handle("open calculator")                   # a new command: the question is dropped
        self.assertNotEqual(r.kind, "proposal")
        self.assertEqual(len(self.msg.whatsapp), 1)

    def test_whatsapp_number_format(self):
        from pa.adapters.messages import wa_number
        self.assertEqual(wa_number("98765 43210"), "919876543210")
        self.assertEqual(wa_number("+91 98765 43210"), "919876543210")
        self.assertEqual(wa_number("09876543210"), "919876543210")


if __name__ == "__main__":
    unittest.main(verbosity=1)
