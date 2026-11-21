"""Lazey: single-screen Kivy UI for the local assistant prototype.

The look (themes, header, greeting orb, bubbles, typing bar, menu, calendar, quick prompts) comes
from the team's `gui-themes-layout` branch (pa_ui/). The features wired in here (chat history,
WhatsApp auto-send, tasks/to-dos/routines/daily messages, reminders, timed routines, offline speech
status, battery exemption) come from main. The assistant core is pa/.
"""
import os
import threading

from kivy.config import Config

Config.set("graphics", "multisamples", "4")  # smooth edges: rings, waves, rounded shapes

from kivy.app import App  # noqa: E402
from kivy.clock import Clock  # noqa: E402
from kivy.core.window import Window  # noqa: E402
from kivy.metrics import dp  # noqa: E402
from kivy.uix.boxlayout import BoxLayout  # noqa: E402
from kivy.uix.label import Label  # noqa: E402
from kivy.uix.popup import Popup  # noqa: E402
from kivy.uix.scrollview import ScrollView  # noqa: E402
from kivy.uix.textinput import TextInput  # noqa: E402

from pa import voice as V  # noqa: E402
from pa.adapters import android_util as au  # noqa: E402
from pa.adapters.daily_android import days_text  # noqa: E402
from pa.adapters.voice_android import AndroidVoice  # noqa: E402
from pa.bootstrap import KeyUnavailable, build_assistant  # noqa: E402
from pa_ui.calendar_view import CalendarView  # noqa: E402
from pa_ui.chrome import Chrome  # noqa: E402
from pa_ui.config import APP_NAME, ConfigStore  # noqa: E402
from pa_ui.lazey_widgets import Bubble  # noqa: E402
from pa_ui.quick_view import QuickPromptsView  # noqa: E402
from pa_ui.widgets import Status, T, ThemedButton, style_input, style_label, style_popup, surface  # noqa: E402


class AssistantApp(App):
    title = APP_NAME

    def build(self):
        # Theme + button layout come from the saved GUI config (see pa_ui/).
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

        self.status = Status()  # what the assistant is doing; not shown on screen

        self.log = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        self.log.bind(minimum_height=self.log.setter("height"))
        self.sv = ScrollView()
        self.sv.add_widget(self.log)

        # proposed-action card (hidden until a proposal exists)
        self.card = BoxLayout(orientation="vertical", size_hint_y=None, height=0, opacity=0, spacing=dp(4),
                              padding=dp(12))
        surface(self.card, fill="surface", border=0.5, radius=22)
        self.card_text = Label(text="", halign="center", valign="middle", size_hint_y=1)
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
        self._offline_status = None   # on-device speech pack status (Voice popup)
        self._voice_refresh = None

        self.entry = TextInput(multiline=False, hint_text="Message %s..." % APP_NAME, write_tab=False)
        self.entry.bind(on_text_validate=lambda *_: self.send())

        # Chrome puts the header, greeting and typing bar around these widgets, per the saved layout.
        root = self.chrome.assemble(self.status, self.sv, self.card, self.entry)
        self.root_box, self._kb_now = root, 0
        self.calendar_view = CalendarView(self)
        self.quick_view = QuickPromptsView(self)
        # The keyboard check costs 2-14 ms of JNI on the UI thread (measured on the phone): run every
        # 0.15 s it dropped a frame each time and made the chat scroll stutter. So it runs only while
        # the keyboard can be open or is closing: typing box focused, keyboard still up, or a moment
        # after the focus changed.
        self._kb_jni = None
        self._kb_watch_until = Clock.get_time() + 2.0
        self.entry.bind(focus=lambda *_: setattr(self, "_kb_watch_until", Clock.get_time() + 2.0))
        Clock.schedule_interval(self.track_keyboard, 0.15)
        return root

    def keyboard_px(self):
        """On-screen keyboard height in pixels (0 when closed or not on Android).
        Measured from the window's visible frame: its bottom edge moves up by the keyboard
        height. The largest bottom seen is the keyboard-closed baseline."""
        if self._kb_jni is None:   # look the Java objects up once, not on every check
            try:
                from jnius import autoclass  # type: ignore
                from android import mActivity  # type: ignore
                self._kb_jni = (mActivity.getWindow().getDecorView(), autoclass("android.graphics.Rect")())
            except Exception:
                self._kb_jni = False   # desktop
        if not self._kb_jni:
            return 0
        view, r = self._kb_jni
        view.getWindowVisibleDisplayFrame(r)
        self._kb_base = max(self._kb_base, r.bottom)
        kb = self._kb_base - r.bottom
        return kb if kb > dp(80) else 0  # ignore small jitters (nav bar changes)

    def track_keyboard(self, *_):
        if not (self.entry.focus or self._kb_now or Clock.get_time() < self._kb_watch_until):
            return   # keyboard closed and typing box not in use: nothing to check
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
        if self.voice.available():
            self.voice.check_offline()  # learn which offline speech pack is installed before the first Mic tap
        # Daily messages / reminders / timed routines: alarms are lost after a force-stop; set them again.
        self.run_bg(self.asst.resume_schedules, lambda res: res if not isinstance(res, Exception)
                    else self.say("Could not restart daily messages: %s" % type(res).__name__, "sys"))
        self.status.text = "Parser: %s" % self.asst.backend.name
        # Chat history: earlier messages come back like in a normal chat app (stored encrypted).
        try:
            history = self.asst.chat_history()
        except Exception:
            history = []
        for h in history:
            text = h["text"][2:] if h["who"] == "user" and h["text"].startswith("> ") else h["text"]
            self.log.add_widget(Bubble(text, h["who"]))
        self.chrome.refresh_hero()  # the greeting shows only while the chat is empty
        self.scroll_bottom()
        # timed routines: a tapped "Routine: X" notification is picked up here and in on_resume
        Clock.schedule_once(lambda *_: self.run_tapped_routine(), 1.0)
        Clock.schedule_once(lambda *_: self.check_auto_send(), 1.5)

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
    def say(self, text, who="bot", save=True):
        self.log.add_widget(Bubble(text, who))
        self.chrome.refresh_hero()
        self.scroll_bottom()
        if save and self.asst is not None:
            try:
                self.asst.log_chat(who, text)
            except Exception:
                pass  # never lose the UI because the history could not be written

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
    def run_tapped_routine(self):
        """Tapped 'Routine: X' notification -> run routine X once."""
        if self.asst is None:
            return
        name = getattr(self.asst.daily, "take_routine_tap", lambda: None)()
        if name:
            self.say("(Started from the routine notification)", "sys")
            self.send_text("%s routine" % name)

    def send_text(self, text):
        """Run a command as if typed (e.g. the Run button of a routine)."""
        self.entry.text = text
        self.send()

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
            try:
                self.asst.log_chat("bot", res.text)  # the card is not a chat line; keep it in history
            except Exception:
                pass
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
        if getattr(res, "extra", None) in ("auto_send_setup", "auto_send_settings"):
            self.auto_send_buttons(res.extra)
        elif getattr(res, "extra", None) == "battery_exemption":
            Clock.schedule_once(lambda *_: self.asst.daily.request_battery_exemption(), 1.5)

    def auto_send_buttons(self, extra):
        """The auto-send switch as a clear, filled button (a plain chat chip looked like text on the
        phone: 'use the button below' with no button visible). These buttons only open Settings, so
        they stay usable: tap them as often as needed (single-use, greyed buttons looked broken)."""
        if extra == "auto_send_setup":
            self.button_list([("Turn on auto-send", self.auto_send_setup)], accent=True, icon="send", keep=True)
        elif extra == "auto_send_settings":
            self.button_list([("Auto-send settings", self.auto_send_open_settings)],
                             accent=True, icon="sliders", keep=True)

    def auto_send_open_settings(self):
        self.say("Opening Settings at '%s auto-send' (under 'Downloaded services'): tap it to switch "
                 "it off or on." % APP_NAME, "sys", save=False)
        if not self.asst.messages.open_accessibility_settings():
            self.say("Could not open Settings. Open Settings > Accessibility > %s auto-send yourself."
                     % APP_NAME, "sys", save=False)

    def button_list(self, entries, accent=False, icon=None, keep=False):
        """Inline buttons in the chat. A normal list is single-use: one tap disables all of them.
        keep=True: buttons that only open a screen (Settings); they stay usable and do not grey out
        other lists."""
        box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        box.bind(minimum_height=box.setter("height"))
        btns = []
        if not keep:
            # A new list makes older lists stale (assistant only accepts the latest ids),
            # so grey them out instead of letting a tap fail later.
            for old in getattr(self, "_live_buttons", []):
                old.disabled = True
            self._live_buttons = btns

        def make(label, fn):
            if accent:
                b = ThemedButton(text=label, icon=icon or "check", mode="icon_text", kind="accent",
                                 fixed_stack="side", size_hint_x=1, height=dp(50))
            else:
                b = ThemedButton(text=label, mode="text", wide=True, halign="left", fixed_stack="side",
                                 size_hint_x=1, height=dp(44))

            def on(*_):
                if not keep:
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
        self.chrome.refresh_hero()
        self.scroll_bottom()

    def pick_contact(self, i):
        self.say("Option %d" % (i + 1), "user")
        self.run_bg(lambda: self.asst.choose_contact(i), self.on_reply)

    def open_photo(self, pid):
        self.run_bg(lambda: self.asst.open_photo(pid), self.on_result)

    def ask_permissions(self, perms):
        try:
            from android.permissions import request_permissions  # type: ignore

            def cb(perms_back, grants):
                # Say exactly what happened (phone test: one of three was refused, but the app
                # said "Permission granted"). Photos are special: Android 14+ "limited photos"
                # grants only the second permission, which is enough.
                names = [str(p).rsplit(".", 1)[-1].replace("_", " ").lower() for p in perms_back]
                missing = [n for n, g in zip(names, grants) if not g]
                photos_ok = any(g for n, g in zip(names, grants) if "media" in n or "external storage" in n)
                if not missing or photos_ok:
                    msg = "Permission granted. Please say your request again."
                elif len(missing) < len(names):
                    msg = "Still missing: %s. Without it this cannot be done; nothing changed." % ", ".join(missing)
                else:
                    msg = "Permission was not given, so this cannot be done. Nothing changed."
                Clock.schedule_once(lambda *_: self.say(msg, "sys"), 0)
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
            if getattr(res, "extra", None) == "battery_exemption":
                # let the user read the message first, then show Android's own dialog
                Clock.schedule_once(lambda *_: self.asst.daily.request_battery_exemption(), 1.5)

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
        if kind == "offline_status":
            self._offline_status = value
            if self._voice_refresh:
                self._voice_refresh()
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
        """Menu > Voice: when to speak replies, which voice, offline-only listening and the
        offline speech pack (the speech must work without internet)."""
        box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        box.bind(minimum_height=box.setter("height"))
        self.popup("Voice", box)
        s = self.vset

        def label(text, h=30, role="text"):
            lb = Label(text=text, size_hint_y=None, height=dp(h), halign="center", valign="middle")
            lb.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
            box.add_widget(style_label(lb, role))
            return lb

        def button(text, fn, icon="none", kind="normal"):
            b = ThemedButton(text=text, icon=icon, wide=True, size_hint_x=1, height=dp(44), font_px=13, kind=kind)
            b.bind(on_release=lambda *_: fn())
            box.add_widget(b)

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
            label("Listening without internet")
            chips(((True, "Offline only"), (False, "Allow online")), s.prefer_offline,
                  lambda v: setattr(s, "prefer_offline", v))
            st = self._offline_status
            if st is None:
                label("Offline speech: checking...", 36, "muted")
            elif not st.get("available"):
                label("Offline speech: this phone has no on-device recognizer.", 40, "muted")
            elif st.get("ready"):
                label("Offline speech installed (%s): the mic works without internet." % st["ready"], 40, "muted")
                if st.get("better"):
                    button("Get Indian English (better Hinglish)", lambda: self.voice.download_offline(st["better"]),
                           icon="plus")
            else:
                label("Offline speech: %s" % ("downloading..." if st.get("downloading") else "not installed"),
                      36, "muted")
                if st.get("download"):
                    button("Download offline speech (%s)" % st["download"],
                           lambda: self.voice.download_offline(st["download"]), icon="plus", kind="accent")
                button("Check again", lambda: self.voice.check_offline(), icon="search")
            if self.voice.tts_voice != "-":
                label("Last voice used: %s" % self.voice.tts_voice, 36, "muted")
        self._voice_refresh = refresh
        refresh()
        if self.voice.available():
            self.voice.check_offline()  # result comes back as the 'offline_status' event

    def on_pause(self):
        self.voice.pause()  # release the mic and stop speaking in the background
        self.chrome.set_listening(False)
        return True

    def on_resume(self):
        # back from WhatsApp after an auto-send: say whether Send was pressed
        if self.asst is not None:
            r = self.asst.auto_send_report()
            if r is not None:
                self.say(r.text, "sys" if r.kind == "error" else "bot")
                self.speak_reply(r)
            Clock.schedule_once(lambda *_: self.run_tapped_routine(), 0.5)
            # back from Settings after turning auto-send on: remember it
            if getattr(self.asst.messages, "auto_send_ready", lambda: False)() and not self.vset.auto_send_wanted:
                Clock.schedule_once(lambda *_: self.check_auto_send(), 0.5)

    def check_auto_send(self, looks=0):
        """Remember that WhatsApp auto-send was on; if an app update switched it off, say so."""
        if self.asst is None:
            return
        ready = getattr(self.asst.messages, "auto_send_ready", lambda: False)()
        if not ready and self.vset.auto_send_wanted and looks < 8:
            # The service can be off for several seconds while it is still coming back: after an
            # update it was bound only after >5 s, and after the Accessibility settings screen it came
            # back ~10 s later (measured on the phone). Look again for ~16 s before warning.
            Clock.schedule_once(lambda *_: self.check_auto_send(looks + 1), 2)
            return
        if ready and not self.vset.auto_send_wanted:
            self.vset.auto_send_wanted = True
        elif not ready and self.vset.auto_send_wanted:
            if getattr(self, "_auto_send_warned", False):
                return  # once per app session, and not stored in the chat history
            self._auto_send_warned = True
            self.say("WhatsApp auto-send is off (Android switches it off when the app is updated or "
                     "force-stopped), so WhatsApp messages will wait for you to press Send. Turn it on again:",
                     "sys", save=False)
            self.auto_send_buttons("auto_send_setup")
            return
        else:
            return
        try:
            V.save_settings(self.voice_path(), self.vset)
        except OSError:
            pass

    def show_auto_send(self):
        """Menu > WhatsApp auto-send: always there, shows ON/OFF and the switch."""
        if not self.asst:
            return
        res = self.asst.auto_send_status()
        self.say(res.text, "bot", save=False)
        self.auto_send_buttons(res.extra)

    def auto_send_setup(self):
        self.say("To let me press Send in WhatsApp: in the screen that opens, tap '%s auto-send' (under "
                 "'Downloaded services') and switch it on.\nIf it is greyed out "
                 "('Restricted setting'): open Settings > Apps > %s, tap the 3 dots at the top right, choose "
                 "'Allow restricted settings', then try again.\nIt only acts for 20 seconds after I open a chat, "
                 "and only on the exact message I typed." % (APP_NAME, APP_NAME), "sys", save=False)
        Clock.schedule_once(lambda *_: self.asst.messages.open_accessibility_settings(), 2.0)

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

    def _row_label(self, text, h=56):
        lb = Label(text=text, halign="left", valign="middle")
        lb.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        return style_label(lb)

    def _heading(self, box, text):
        lb = Label(text=text, size_hint_y=None, height=dp(34), halign="center", valign="middle")
        lb.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        box.add_widget(style_label(lb, "muted"))

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
                r.add_widget(ThemedButton(text="Save", icon="check", mode="icon", height=dp(44), size_hint_x=None,
                                          width=dp(52), on_release=lambda _b, i=p["id"], t=ti: (
                                              self.asst.update_preference(i, t.text.strip()), refresh())))
                r.add_widget(ThemedButton(text="Del", icon="trash", mode="icon", height=dp(44), size_hint_x=None,
                                          width=dp(52), on_release=lambda _b, i=p["id"]: (
                                              self.asst.delete_record(i), refresh())))
                box.add_widget(r)
            clear = ThemedButton(text="Clear chat history", icon="close", mode="icon_text", fixed_stack="side",
                                 size_hint_x=1, height=dp(44))

            def clear_chat(b):
                if b.text == "Clear chat history":
                    b.text = "Tap again to clear the chat"
                else:
                    self.asst.clear_chat()
                    self.log.clear_widgets()
                    self.chrome.refresh_hero()
                    pop.dismiss()
            clear.bind(on_release=clear_chat)
            box.add_widget(clear)
            wipe = ThemedButton(text="Delete ALL my data", icon="trash", mode="icon_text", fixed_stack="side",
                                size_hint_x=1, height=dp(44))

            def confirm(b):
                if b.text.startswith("Delete ALL"):
                    b.text = "Tap again to confirm"
                else:
                    self.asst.delete_all_data()
                    self.log.clear_widgets()  # chat history is part of "all data"
                    self.say("All data deleted.", "sys", save=False)
                    pop.dismiss()
            wipe.bind(on_release=confirm)  # (the label text is what `confirm` checks)
            box.add_widget(wipe)
        refresh()

    def show_calendar(self):
        """Month view + agenda of the in-app tasks (tasks can be deleted there)."""
        if not self.asst:
            self.say("The assistant is not ready, so there are no tasks to show.", "sys")
            return
        self.calendar_view.open()

    def show_quick(self):
        """The + button: quick prompts (tap to fill the typing box; add your own; delete)."""
        self.quick_view.open()

    def show_tasks(self):
        """Menu > Tasks: to-dos & reminders, routines (with Run), daily messages."""
        if not self.asst:
            return
        box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        box.bind(minimum_height=box.setter("height"))
        pop = self.popup("Tasks", box)

        def row(text, buttons, h=56):
            r = BoxLayout(size_hint_y=None, height=dp(h), spacing=dp(4))
            r.add_widget(self._row_label(text))
            for name, icon, fn in buttons:
                r.add_widget(ThemedButton(text=name, icon=icon, mode="icon", height=dp(44), size_hint_x=None,
                                          width=dp(52), on_release=lambda _b, f=fn: f()))
            box.add_widget(r)

        def refresh():
            box.clear_widgets()
            today = self.asst.clock().date()
            todos = self.asst.list_todos()
            self._heading(box, "To-dos & reminders" if todos else "No to-dos. Say 'todo: buy milk' or "
                                                                   "'remind me at 6 pm to ...'")
            for t in todos:
                row(self.asst._todo_label(t, today),
                    [("Done", "check", lambda i=t["id"]: (self.say(self.asst.mark_todo_done(i).text, "sys"),
                                                          refresh())),
                     ("Del", "trash", lambda i=t["id"]: (self.asst.delete_todo(i), refresh()))])
            routines = self.asst.list_routines()
            self._heading(box, "Routines" if routines else "No routines. Say 'routine good morning: ...'")
            for rt in routines:
                trig = rt.get("trigger")
                when = ("\nevery %s at %s" % (days_text(trig.get("days")), trig["time"])) if trig else ""
                n = len(rt["steps"])
                row("%s (%d step%s)%s" % (rt["name"], n, "" if n == 1 else "s", when),
                    [("Run", "right", lambda nm=rt["name"]: (pop.dismiss(), self.send_text(nm))),
                     ("Del", "trash", lambda i=rt["id"]: (self.asst.delete_routine(i), refresh()))])
            scheds = self.asst.list_schedules()
            self._heading(box, "Daily messages" if scheds else "No daily messages.")
            if (scheds or todos or any(r.get("trigger") for r in routines)) and not self.asst.daily_battery_ok():
                b = ThemedButton(text="Phone may stop timed items: allow background", icon="bell", mode="icon_text",
                                 fixed_stack="side", size_hint_x=1, height=dp(44))
                b.bind(on_release=lambda *_: self.asst.daily.request_battery_exemption())
                box.add_widget(b)
            for s in scheds:
                how = "SMS" if s.get("channel") == "sms" else "WhatsApp"
                row("every %s %s  %s to %s\n\"%s\"" % (days_text(s.get("days")), s.get("time", "?"), how,
                                                     s.get("name", "?"), s.get("text", "")[:60]),
                    [("Del", "trash", lambda i=s["id"]: (self.asst.delete_schedule(i), refresh()))], h=64)
        refresh()


if __name__ == "__main__":
    AssistantApp().run()
