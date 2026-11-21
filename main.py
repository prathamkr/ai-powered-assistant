"""Lazey: single-screen Kivy UI for the local assistant prototype."""
import os
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput

from pa import voice as V
from pa.adapters import android_util as au
from pa.adapters.voice_android import AndroidVoice
from pa.bootstrap import KeyUnavailable, build_assistant
from pa_ui.calendar_view import CalendarView
from pa_ui.chrome import Chrome
from pa_ui.config import APP_NAME, ConfigStore
from pa_ui.editor import StyleEditor
from pa_ui.lazey_widgets import SUGGESTIONS, Bubble
from pa_ui.widgets import Status, T, ThemedButton, style_input, style_label, style_popup, surface


class AssistantApp(App):
    title = APP_NAME

    def build(self):
        # Theme + button layout come from the saved GUI config (see pa_ui/ and the Style button).
        store = ConfigStore(self.user_data_dir)
        self.chrome = Chrome(self, store.load(), store)
        T.apply(self.chrome.cfg)  # sets Window.clearcolor too
        # Keyboard handling: do NOT pan the window ("below_target" pushed the header and the
        # chat history off the top). Instead the bottom padding grows to the keyboard height
        # (see track_keyboard), so only the chat area shrinks and the input sits on top of
        # the keyboard while the header and history stay where they are.
        Window.softinput_mode = ""
        self._kb_base = 0   # visible-frame bottom (px) with the keyboard closed
        self.asst = None
        self.pending = None  # (action_id, hash) of the proposal currently on screen
        self.working = False

        self.status = Status()  # .text is shown from the avatar button; .level colours its dot

        self.log = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        self.log.bind(minimum_height=self.log.setter("height"))
        self.sv = ScrollView()
        self.sv.add_widget(self.log)

        # proposed-action card (hidden until a proposal exists)
        self.card = BoxLayout(orientation="vertical", size_hint_y=None, height=0, opacity=0, spacing=dp(4),
                              padding=dp(12))
        surface(self.card, fill="surface", border=0.5, radius=22)
        self.card_text = Label(text="", halign="left", valign="top", size_hint_y=1)
        self.card_text.bind(size=lambda *_: setattr(self.card_text, "text_size", self.card_text.size))
        style_label(self.card_text)
        btns = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        self.approve_btn = ThemedButton(text="Approve", icon="check", kind="accent", size_hint_x=1, height=dp(44),
                                        on_release=lambda *_: self.on_approve())
        self.reject_btn = ThemedButton(text="Reject", icon="close", size_hint_x=1, height=dp(44),
                                       on_release=lambda *_: self.on_reject())
        btns.add_widget(self.approve_btn)
        btns.add_widget(self.reject_btn)
        self.card.add_widget(self.card_text)
        self.card.add_widget(btns)

        self.voice = AndroidVoice(lambda kind, value: Clock.schedule_once(
            lambda *_: self.on_voice_event(kind, value), 0))  # engine callbacks -> UI thread
        self.vset = V.VoiceSettings()
        self._from_voice = False

        self.entry = TextInput(multiline=False, hint_text="Message %s..." % APP_NAME, write_tab=False)
        self.entry.bind(on_text_validate=lambda *_: self.send())

        # Chrome puts the header, greeting and typing bar around these widgets, per the saved layout.
        root = self.chrome.assemble(self.status, self.sv, self.card, self.entry)
        self.root_box, self._kb_now = root, 0
        self.style_editor = StyleEditor(self.chrome)
        self.calendar_view = CalendarView(self)
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
            self.chrome.set_keyboard(kb)
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
        self.chrome.refresh_hero()  # the greeting (with example prompts) replaces the old hello message

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
        self.log.add_widget(Bubble(text, who))
        self.chrome.refresh_hero()
        self.scroll_bottom()

    def scroll_bottom(self):
        # Scroll again after layout has settled: new widgets get their final height a
        # frame or two later, so a single early scroll stops short (seen on phone).
        for delay in (0.05, 0.3):
            Clock.schedule_once(lambda *_: setattr(self.sv, "scroll_y", 0), delay)

    def set_input(self, on):
        self.chrome.set_input_enabled(on)

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
        self.say(text, "user")
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
            b = ThemedButton(text=label, mode="text", wide=True, halign="left", fixed_stack="side",
                             size_hint_x=1, height=dp(44))

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
        self.say("Option %d" % (i + 1), "user")
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

    # ---------- header / input buttons that are not chat features ----------
    def show_style(self):
        self.style_editor.open()

    # ---------- voice (engine: pa/voice.py + pa/adapters/voice_android.py) ----------
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

    def on_mic(self):
        """The mic button: start listening, or finish now and use what was heard."""
        if self.asst is None or self.working:
            return
        if not self.voice.available():
            self.say("Voice input works only on the phone.", "sys")
            return
        if self.voice.is_listening():
            self.voice.stop_listening()
            return
        if not self.voice.mic_allowed():
            self.ask_mic_permission()
            return
        self.voice.start_listening(self.vset.prefer_offline)
        self.chrome.set_listening(True)
        self.status.text = "Listening... (%s)" % self.voice.recognizer_label()

    def ask_mic_permission(self):
        try:
            from android.permissions import request_permissions  # type: ignore

            def cb(_perms, grants):
                ok = any(grants)
                Clock.schedule_once(lambda *_: self.on_mic() if ok else self.say(
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
        self.chrome.set_listening(False)
        if self.asst is not None and not self.working:
            self.status.text = "Parser: %s" % self.asst.backend.name
        if kind == "final":
            self.entry.text = value
            self.send(from_voice=True)
        elif kind == "nospeech":
            self.entry.text = ""
            self.say("I did not hear anything. Tap the mic and try again.", "sys")
        elif kind == "error":
            self.say(value, "sys")

    def on_voice(self):
        """Menu > Voice: when to speak replies, which voice, pitch and speed, test, offline preference."""
        box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        box.bind(minimum_height=box.setter("height"))
        self.popup("Voice", box)
        s = self.vset

        def label(text, h=30, role="text"):
            lb = Label(text=text, size_hint_y=None, height=dp(h), halign="left", valign="middle")
            lb.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
            box.add_widget(style_label(lb, role))
            return lb

        def save():
            try:
                V.save_settings(self.voice_path(), s)
            except OSError:
                pass

        def chips(options, current, pick):
            row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
            for value, name in options:
                b = ThemedButton(text=name, mode="text", size_hint_x=1, height=dp(42), font_px=13,
                                 kind="selected" if value == current else "normal")
                b.bind(on_release=lambda _b, v=value: (pick(v), save(), refresh()))
                row.add_widget(b)
            box.add_widget(row)

        def refresh():
            box.clear_widgets()
            label("Listening: %s, language %s" % (self.voice.recognizer_label() if self.voice.available()
                                                   else "not available here", V.LANGUAGE), 40, "muted")
            label("Speak replies")
            chips((("voice", "After voice"), ("always", "Always"), ("off", "Off")), s.speak_mode,
                  lambda m: setattr(s, "speak_mode", m))
            label("Voice")
            for p in V.PROFILES:
                b = ThemedButton(text="%s  -  %s" % (p.name, p.tagline), icon="speaker", wide=True, halign="left",
                                 size_hint_x=1, height=dp(46), font_px=13,
                                 kind="selected" if p.id == s.profile_id else "normal")
                b.bind(on_release=lambda _b, pid=p.id: (s.use_profile(pid), save(), refresh()))
                box.add_widget(b)
            for attr, title, lo, hi in (("pitch", "Pitch", V.PITCH_MIN, V.PITCH_MAX),
                                        ("rate", "Speed", V.RATE_MIN, V.RATE_MAX)):
                lb = label("%s: %.2f" % (title, getattr(s, attr)))
                sl = Slider(min=lo, max=hi, value=getattr(s, attr), size_hint_y=None, height=dp(36),
                            value_track=True, value_track_color=T.c("accent"))

                def changed(_w, v, attr=attr, title=title, lb=lb):
                    setattr(s, attr, round(v, 2))
                    lb.text = "%s: %.2f" % (title, v)
                sl.bind(value=changed)
                sl.bind(on_touch_up=lambda w, t: save() if w.collide_point(*t.pos) else None)
                box.add_widget(sl)
            row2 = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
            test = ThemedButton(text="Test voice", icon="speaker", size_hint_x=1, height=dp(46), font_px=13)
            test.bind(on_release=lambda *_: self.voice.speak("Hello! This is how I will read my replies.", s))
            stop = ThemedButton(text="Stop", icon="close", size_hint_x=1, height=dp(46), font_px=13)
            stop.bind(on_release=lambda *_: self.voice.stop_speaking())
            row2.add_widget(test)
            row2.add_widget(stop)
            box.add_widget(row2)
            label("Recognition")
            chips(((True, "Prefer offline"), (False, "Online allowed")), s.prefer_offline,
                  lambda v: setattr(s, "prefer_offline", v))
            if self.voice.tts_voice != "-":
                label("Last voice used: %s" % self.voice.tts_voice, 36, "muted")
        refresh()

    def on_pause(self):
        self.voice.pause()  # release the mic and stop speaking in the background
        self.chrome.set_listening(False)
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
        close = ThemedButton(text="Close", icon="check", size_hint_x=1, height=dp(44))
        outer.add_widget(close)
        p = style_popup(Popup(title=title, content=outer, size_hint=(0.95, 0.85)))
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
                box.add_widget(style_label(Label(text="No saved preferences.", size_hint_y=None, height=dp(40))))
            for p in prefs:
                r = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(4))
                ti = style_input(TextInput(text=p["text"], multiline=False, padding=[dp(8), dp(12)]))
                r.add_widget(ti)
                r.add_widget(ThemedButton(text="Save", icon="check", mode="icon", height=dp(44), size_hint_x=None, width=dp(52),
                                          on_release=lambda _b, i=p["id"], t=ti: (self.asst.update_preference(i, t.text.strip()), refresh())))
                r.add_widget(ThemedButton(text="Del", icon="trash", mode="icon", height=dp(44), size_hint_x=None, width=dp(52),
                                          on_release=lambda _b, i=p["id"]: (self.asst.delete_record(i), refresh())))
                box.add_widget(r)
            wipe = ThemedButton(text="Delete ALL my data", icon="trash", mode="icon_text", fixed_stack="side",
                                size_hint_x=1, height=dp(44))

            def confirm(b):
                if b.text.startswith("Delete ALL"):
                    b.text = "Tap again to confirm"
                else:
                    self.asst.delete_all_data()
                    self.say("All data deleted.", "sys")
                    pop.dismiss()
            wipe.bind(on_release=confirm)  # (the label text is what `confirm` checks)
            box.add_widget(wipe)
        refresh()

    def show_calendar(self):
        """Month view + agenda of the in-app tasks (replaces the old Tasks list; tasks can be deleted there)."""
        if not self.asst:
            self.say("The assistant is not ready, so there are no tasks to show.", "sys")
            return
        self.calendar_view.open()

    def show_status(self):
        """Tap the avatar: what the assistant is doing right now (the old status line)."""
        self.popup("Status", style_label(Label(text=self.status.text, size_hint_y=None, height=dp(60), halign="left",
                                               text_size=(dp(240), None))))

    def show_quick(self):
        """The + button: example prompts that fill the typing box."""
        box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        box.bind(minimum_height=box.setter("height"))
        pop = self.popup("Quick prompts", box)
        for label, fill in SUGGESTIONS:
            b = ThemedButton(text=label, mode="text", wide=True, halign="left", size_hint_x=1, height=dp(46))
            b.bind(on_release=lambda _b, f=fill: (pop.dismiss(), self.chrome.fill_entry(f)))
            box.add_widget(b)


if __name__ == "__main__":
    AssistantApp().run()
