"""Single-screen Kivy UI for the local assistant prototype."""
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
import os

from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput

from pa import voice as V
from pa.adapters import android_util as au
from pa.adapters.voice_android import AndroidVoice
from pa.bootstrap import KeyUnavailable, build_assistant

BG = (0.07, 0.07, 0.10, 1)


class Msg(Label):
    def __init__(self, text, who="bot", **kw):
        color = {"user": (0.6, 0.8, 1, 1), "bot": (1, 1, 1, 1), "sys": (1, 0.8, 0.4, 1)}[who]
        super().__init__(text=text, color=color, size_hint_y=None, halign="left", valign="top", **kw)
        self.bind(width=lambda *_: setattr(self, "text_size", (self.width, None)),
                  texture_size=lambda *_: setattr(self, "height", self.texture_size[1] + dp(8)))


class AssistantApp(App):
    title = "Local Assistant"

    def build(self):
        Window.clearcolor = BG
        # Keyboard handling: do NOT pan the window ("below_target" pushed the header and the
        # chat history off the top). Instead the bottom padding grows to the keyboard height
        # (see track_keyboard), so only the chat area shrinks and the input sits on top of
        # the keyboard while the header and history stay where they are.
        Window.softinput_mode = ""
        self._kb_base = 0   # visible-frame bottom (px) with the keyboard closed
        self.asst = None
        self.pending = None  # (action_id, hash) of the proposal currently on screen
        self.working = False

        root = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        bar = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        self.status = Label(text="starting...", halign="left", size_hint_x=1, font_size=dp(12))
        self.status.bind(size=lambda *_: setattr(self.status, "text_size", self.status.size))
        b1 = Button(text="Prefs", size_hint_x=None, width=dp(70), on_release=lambda *_: self.show_prefs())
        b2 = Button(text="Tasks", size_hint_x=None, width=dp(70), on_release=lambda *_: self.show_tasks())
        b3 = Button(text="Voice", size_hint_x=None, width=dp(70), on_release=lambda *_: self.show_voice())
        for w in (self.status, b3, b1, b2):
            bar.add_widget(w)

        self.log = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        self.log.bind(minimum_height=self.log.setter("height"))
        self.sv = ScrollView()
        self.sv.add_widget(self.log)

        # proposed-action card (hidden until a proposal exists)
        self.card = BoxLayout(orientation="vertical", size_hint_y=None, height=0, opacity=0, spacing=dp(4))
        self.card_text = Label(text="", halign="left", valign="top", size_hint_y=1)
        self.card_text.bind(size=lambda *_: setattr(self.card_text, "text_size", self.card_text.size))
        btns = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        self.approve_btn = Button(text="Approve", on_release=lambda *_: self.on_approve())
        self.reject_btn = Button(text="Reject", on_release=lambda *_: self.on_reject())
        btns.add_widget(self.approve_btn)
        btns.add_widget(self.reject_btn)
        self.card.add_widget(self.card_text)
        self.card.add_widget(btns)

        row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        self.entry = TextInput(multiline=False, hint_text="Type here...", write_tab=False)
        self.entry.bind(on_text_validate=lambda *_: self.send())
        self.send_btn = Button(text="Send", size_hint_x=None, width=dp(70), on_release=lambda *_: self.send())
        self.mic_btn = Button(text="Mic", size_hint_x=None, width=dp(64), on_release=lambda *_: self.mic_pressed())
        row.add_widget(self.entry)
        row.add_widget(self.mic_btn)
        row.add_widget(self.send_btn)
        self.voice = AndroidVoice(lambda kind, value: Clock.schedule_once(
            lambda *_: self.on_voice_event(kind, value), 0))  # engine callbacks -> UI thread
        self.vset = V.VoiceSettings()
        self._from_voice = False

        for w in (bar, self.sv, self.card, row):
            root.add_widget(w)
        self.root_box, self._kb_now = root, 0
        Clock.schedule_interval(self.track_keyboard, 0.15)
        return root

    def keyboard_px(self):
        """On-screen keyboard height in pixels (0 when closed or not on Android).
        Measured from the window's visible frame: its bottom edge moves up by the keyboard
        height. The largest bottom seen is the keyboard-closed baseline."""
        try:
            from jnius import autoclass  # type: ignore
            from android import mActivity  # type: ignore
        except Exception:
            return 0
        r = autoclass("android.graphics.Rect")()
        mActivity.getWindow().getDecorView().getWindowVisibleDisplayFrame(r)
        self._kb_base = max(self._kb_base, r.bottom)
        kb = self._kb_base - r.bottom
        return kb if kb > dp(80) else 0  # ignore small jitters (nav bar changes)

    def track_keyboard(self, *_):
        try:
            kb = self.keyboard_px()
        except Exception:
            return
        if abs(self._kb_now - kb) > 1:
            self._kb_now = kb
            # bottom padding (not an extra widget, which added layout spacing when closed)
            self.root_box.padding = [dp(8), dp(8), dp(8), dp(8) + kb]
            self.scroll_bottom()  # keep the newest message visible above the input

    # ---------- startup ----------
    def on_start(self):
        self.request_calendar_permission()
        try:
            self.asst = build_assistant(self.user_data_dir)
        except KeyUnavailable as e:
            self.set_input(False)
            self.status.text = "BLOCKED: no encryption key"
            self.say("No key was found for encrypted storage, so the app cannot open your data "
                     "(there is no plaintext fallback). Detail: %s" % e, "sys")
            return
        except Exception as e:  # keep the UI alive and honest
            self.set_input(False)
            self.status.text = "ERROR"
            self.say("Startup failed: %s: %s" % (type(e).__name__, e), "sys")
            return
        self.vset = V.load_settings(self.voice_path())
        self.status.text = "Parser: %s" % self.asst.backend.name
        self.say("Hello! Try: 'Remember ...', 'Note: ...', 'Call mummy from sim 1', "
                 "'Show photos from yesterday'.", "sys")

    def request_calendar_permission(self):
        try:
            from android.permissions import Permission, request_permissions  # type: ignore

            def cb(perms, grants):
                # Android calls this on a non-UI thread; Kivy widgets may only be
                # touched from the main thread (TypeError seen on emulator otherwise).
                if not all(grants):
                    Clock.schedule_once(lambda *_: self.say(
                        "Calendar permission was not given: availability will not be checked "
                        "(the event screen can still open).", "sys"), 0)
            request_permissions([Permission.READ_CALENDAR], cb)
        except Exception:
            pass  # desktop

    # ---------- helpers ----------
    def say(self, text, who="bot"):
        self.log.add_widget(Msg(text, who))
        self.scroll_bottom()

    def scroll_bottom(self):
        # Scroll again after layout has settled: new widgets get their final height a
        # frame or two later, so a single early scroll stops short (seen on phone).
        for delay in (0.05, 0.3):
            Clock.schedule_once(lambda *_: setattr(self.sv, "scroll_y", 0), delay)

    def set_input(self, on):
        self.entry.disabled = not on
        self.send_btn.disabled = not on

    def show_card(self, text):
        self.card_text.text = text
        self.card.height, self.card.opacity = dp(150), 1
        self.approve_btn.disabled = self.reject_btn.disabled = False

    def hide_card(self):
        self.card.height, self.card.opacity = 0, 0
        self.pending = None

    def run_bg(self, fn, done):
        """Run fn off the UI thread; call done(result_or_exception) back on it."""
        def work():
            try:
                res = fn()
            except Exception as e:
                res = e
            Clock.schedule_once(lambda *_: done(res), 0)
        threading.Thread(target=work, daemon=True).start()

    # ---------- chat ----------
    def send(self, from_voice=False):
        text = self.entry.text.strip()
        if not text or self.working or self.asst is None:
            return
        self._from_voice = from_voice
        if self.voice.is_listening():
            self.voice.cancel_listening()
        self.voice.stop_speaking()
        if self.pending:  # a newer message supersedes an unanswered proposal
            self.asst.reject(self.pending[0])
            self.hide_card()
        self.entry.text = ""
        self.say("> " + text, "user")
        self.working = True
        self.set_input(False)
        self.status.text = "thinking..."
        self.run_bg(lambda: self.asst.handle(text), self.on_reply)

    def on_reply(self, res):
        self.working = False
        self.set_input(True)
        self.status.text = "Parser: %s" % self.asst.backend.name
        if isinstance(res, Exception):
            self.say("Error: %s" % type(res).__name__, "sys")
            return
        self.speak_reply(res)
        if res.kind == "proposal":
            self.pending = (res.action_id, res.action_hash)
            self.show_card(res.text)
        elif res.kind == "choose":
            self.say(res.text)
            self.button_list([(lbl, (lambda i=i: self.pick_contact(i))) for i, lbl in enumerate(res.options)])
        elif res.kind == "photos":
            self.say(res.text)
            self.button_list([("Open  " + it["label"], (lambda pid=it["id"]: self.open_photo(pid)))
                              for it in res.items])
        elif res.kind == "need_permission":
            self.say(res.text, "sys")
            self.ask_permissions(res.permissions)
        else:
            self.say(res.text, "sys" if res.kind in ("unsupported", "error") else "bot")

    def button_list(self, entries):
        """Inline buttons in the chat. Each list is single-use: one tap disables all of them."""
        box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        box.bind(minimum_height=box.setter("height"))
        # A new list makes older lists stale (assistant only accepts the latest ids),
        # so grey them out instead of letting a tap fail later.
        for old in getattr(self, "_live_buttons", []):
            old.disabled = True
        btns = []
        self._live_buttons = btns

        def make(label, fn):
            b = Button(text=label, size_hint_y=None, height=dp(44), halign="left")
            b.bind(size=lambda w, *_: setattr(w, "text_size", (w.width - dp(16), None)))

            def on(*_):
                for x in btns:
                    x.disabled = True
                fn()
            b.bind(on_release=on)
            return b
        for label, fn in entries:
            b = make(label, fn)
            btns.append(b)
            box.add_widget(b)
        self.log.add_widget(box)
        self.scroll_bottom()

    def pick_contact(self, i):
        self.say("> %d" % (i + 1), "user")
        self.run_bg(lambda: self.asst.choose_contact(i), self.on_reply)

    def open_photo(self, pid):
        self.run_bg(lambda: self.asst.open_photo(pid), self.on_result)

    def ask_permissions(self, perms):
        try:
            from android.permissions import request_permissions  # type: ignore

            def cb(_perms, grants):
                # any(): on Android 14+ "limited photos" grants only the second permission.
                # The adapter's permission_check() makes the real decision on the next try.
                ok = any(grants)
                Clock.schedule_once(lambda *_: self.say(
                    "Permission granted. Please say your request again." if ok else
                    "Permission was not given, so this cannot be done. Nothing changed.", "sys"), 0)
            request_permissions(list(perms), cb)
        except Exception:
            self.say("Cannot ask for permissions on this device.", "sys")

    def on_approve(self):
        if not self.pending:
            return
        aid, h = self.pending
        self.approve_btn.disabled = self.reject_btn.disabled = True  # block double taps at UI level
        self.hide_card()
        self.run_bg(lambda: self.asst.approve(aid, h), self.on_result)

    def on_reject(self):
        if not self.pending:
            return
        aid = self.pending[0]
        self.hide_card()
        self.say(self.asst.reject(aid).text)

    def on_result(self, res):
        self.say("Error: %s" % type(res).__name__ if isinstance(res, Exception) else res.text)
        if not isinstance(res, Exception):
            self.speak_reply(res)

    # ---------- voice ----------
    def voice_path(self):
        return os.path.join(self.user_data_dir, "voice.json")

    def speak_reply(self, res):
        if not V.should_speak(self.vset.speak_mode, self._from_voice):
            return
        text = V.speakable(res.text)
        if res.kind == "choose" and res.options:
            # read the names, not the numbers: "Option 1, Rahul Sharma."
            names = [o.split(". ", 1)[-1].rsplit(" (", 1)[0] for o in res.options]
            text += " " + " ".join("Option %d, %s." % (i + 1, n) for i, n in enumerate(names))
        if res.kind == "proposal":
            text += " Tap Approve or Reject."
        self.voice.speak(text, self.vset)

    def mic_pressed(self):
        if self.asst is None or self.working:
            return
        if not self.voice.available():
            self.say("Voice input works only on the phone.", "sys")
            return
        if self.voice.is_listening():
            self.voice.stop_listening()  # finish now and use what was heard
            return
        if not self.voice.mic_allowed():
            self.ask_mic_permission()
            return
        self.voice.start_listening(self.vset.prefer_offline)
        self.mic_btn.text = "Stop"
        self.status.text = "Listening... (%s)" % self.voice.recognizer_label()

    def ask_mic_permission(self):
        try:
            from android.permissions import request_permissions  # type: ignore

            def cb(_perms, grants):
                ok = any(grants)
                Clock.schedule_once(lambda *_: self.mic_pressed() if ok else self.say(
                    "Microphone permission was not given, so voice input is off. "
                    "You can still type.", "sys"), 0)
            request_permissions([au.RECORD_AUDIO], cb)
        except Exception:
            self.say("Cannot ask for permissions on this device.", "sys")

    def on_voice_event(self, kind, value):
        if kind == "partial":
            self.entry.text = value
            return
        if kind == "ready":
            self.status.text = "Listening... (%s)" % self.voice.recognizer_label()
            return
        if kind == "processing":
            self.status.text = "Recognizing..."
            return
        if kind == "info":
            self.say(value, "sys")
            return
        # final / nospeech / error / idle: listening is over
        self.mic_btn.text = "Mic"
        if self.asst is not None and not self.working:
            self.status.text = "Parser: %s" % self.asst.backend.name
        if kind == "final":
            self.entry.text = value
            self.send(from_voice=True)
        elif kind == "nospeech":
            self.entry.text = ""
            self.say("I did not hear anything. Tap Mic and try again.", "sys")
        elif kind == "error":
            self.say(value, "sys")

    def show_voice(self):
        box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        box.bind(minimum_height=box.setter("height"))
        self.popup("Voice", box)

        def label(text, h=32):
            lb = Label(text=text, size_hint_y=None, height=dp(h), halign="left", valign="middle")
            lb.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
            box.add_widget(lb)
            return lb

        def save():
            try:
                V.save_settings(self.voice_path(), self.vset)
            except OSError:
                pass

        def refresh():
            box.clear_widgets()
            s = self.vset
            label("Listening: %s, language %s" % (self.voice.recognizer_label() if self.voice.available()
                                                   else "not available here", V.LANGUAGE), 40)
            label("Speak replies:")
            row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(4))
            for mode, name in (("voice", "After voice"), ("always", "Always"), ("off", "Off")):
                row.add_widget(Button(text=("[ %s ]" % name) if s.speak_mode == mode else name,
                                      on_release=lambda _b, m=mode: (setattr(s, "speak_mode", m), save(), refresh())))
            box.add_widget(row)
            label("Voice:")
            for p in V.PROFILES:
                mark = "> " if p.id == s.profile_id else ""
                box.add_widget(Button(text="%s%s: %s" % (mark, p.name, p.tagline), size_hint_y=None, height=dp(44),
                                      on_release=lambda _b, pid=p.id: (s.use_profile(pid), save(), refresh())))
            for attr, title, lo, hi in (("pitch", "Pitch", V.PITCH_MIN, V.PITCH_MAX),
                                        ("rate", "Speed", V.RATE_MIN, V.RATE_MAX)):
                lb = label("%s: %.2f" % (title, getattr(s, attr)))
                sl = Slider(min=lo, max=hi, value=getattr(s, attr), size_hint_y=None, height=dp(40))

                def changed(_w, v, attr=attr, title=title, lb=lb):
                    setattr(s, attr, round(v, 2))
                    lb.text = "%s: %.2f" % (title, v)
                sl.bind(value=changed)
                sl.bind(on_touch_up=lambda w, t: save() if w.collide_point(*t.pos) else None)
                box.add_widget(sl)
            row2 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(4))
            row2.add_widget(Button(text="Test voice", on_release=lambda *_: self.voice.speak(
                "Hello! This is how I will read my replies.", s)))
            row2.add_widget(Button(text="Stop", on_release=lambda *_: self.voice.stop_speaking()))
            box.add_widget(row2)
            off = "on" if s.prefer_offline else "off"
            box.add_widget(Button(text="Prefer offline recognition: %s" % off, size_hint_y=None, height=dp(44),
                                  on_release=lambda *_: (setattr(s, "prefer_offline", not s.prefer_offline),
                                                         save(), refresh())))
            if self.voice.tts_voice != "-":
                label("Last voice used: %s" % self.voice.tts_voice, 40)
        refresh()

    def on_pause(self):
        self.voice.pause()  # release the mic and stop speaking in the background
        self.mic_btn.text = "Mic"
        return True

    def on_resume(self):
        pass

    def on_stop(self):
        self.voice.release()

    # ---------- saved data ----------
    def popup(self, title, body):
        sv = ScrollView()
        sv.add_widget(body)
        outer = BoxLayout(orientation="vertical", spacing=dp(6))
        outer.add_widget(sv)
        close = Button(text="Close", size_hint_y=None, height=dp(44))
        outer.add_widget(close)
        p = Popup(title=title, content=outer, size_hint=(0.95, 0.85))
        close.bind(on_release=lambda *_: p.dismiss())
        p.open()
        return p

    def show_prefs(self):
        if not self.asst:
            return
        box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        box.bind(minimum_height=box.setter("height"))
        pop = self.popup("Saved preferences", box)

        def refresh():
            box.clear_widgets()
            prefs = self.asst.list_preferences()
            if not prefs:
                box.add_widget(Label(text="No saved preferences.", size_hint_y=None, height=dp(40)))
            for p in prefs:
                r = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(4))
                ti = TextInput(text=p["text"], multiline=False)
                r.add_widget(ti)
                r.add_widget(Button(text="Save", size_hint_x=None, width=dp(60),
                                    on_release=lambda _b, i=p["id"], t=ti: (self.asst.update_preference(i, t.text.strip()), refresh())))
                r.add_widget(Button(text="Del", size_hint_x=None, width=dp(50),
                                    on_release=lambda _b, i=p["id"]: (self.asst.delete_record(i), refresh())))
                box.add_widget(r)
            wipe = Button(text="Delete ALL my data", size_hint_y=None, height=dp(44))

            def confirm(b):
                if b.text.startswith("Delete ALL"):
                    b.text = "Tap again to confirm"
                else:
                    self.asst.delete_all_data()
                    self.say("All data deleted.", "sys")
                    pop.dismiss()
            wipe.bind(on_release=confirm)
            box.add_widget(wipe)
        refresh()

    def show_tasks(self):
        if not self.asst:
            return
        box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        box.bind(minimum_height=box.setter("height"))
        self.popup("Tasks (in-app)", box)

        def refresh():
            box.clear_widgets()
            tasks = self.asst.list_tasks()
            if not tasks:
                box.add_widget(Label(text="No tasks.", size_hint_y=None, height=dp(40)))
            for t in tasks:
                r = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(4))
                state = "calendar screen opened" if t.get("calendar") == "handed_off" else t.get("calendar", "")
                lb = Label(text="%s\n%s [%s]" % (t["title"], t["start_iso"][:16].replace("T", " "), state),
                           halign="left")
                lb.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
                r.add_widget(lb)
                r.add_widget(Button(text="Del", size_hint_x=None, width=dp(50),
                                    on_release=lambda _b, i=t["id"]: (self.asst.delete_record(i), refresh())))
                box.add_widget(r)
        refresh()


if __name__ == "__main__":
    AssistantApp().run()
