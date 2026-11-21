"""The quick-prompts screen (the "+" button): tap a prompt to put it in the typing box, add your own,
or delete the ones you do not want. The list is remembered on the phone."""
import os

from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from . import fonts
from . import prompts as P
from .widgets import RoundIcon, ThemedButton, style_input, style_label, style_popup


class QuickPromptsView:
    def __init__(self, app):
        self.app = app
        self.store = P.PromptStore(os.path.join(app.user_data_dir, "quick_prompts.json"))
        self.items = self.store.load()
        self.pop = None
        self.listbox = None
        self.sv = None

    # ---------- the list ----------
    def open(self):
        if self.pop is not None:
            return
        outer = BoxLayout(orientation="vertical", spacing=dp(8))
        # the top padding leaves a small gap between the title bar and the first prompt
        self.listbox = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8), padding=[0, dp(12), 0, dp(4)])
        self.listbox.bind(minimum_height=self.listbox.setter("height"))
        self.sv = ScrollView(bar_width=dp(4))
        self.sv.add_widget(self.listbox)
        outer.add_widget(self.sv)
        foot = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        add = ThemedButton(text="Add prompt", icon="plus", kind="accent", size_hint_x=0.6, height=dp(46), font_px=13)
        add.bind(on_release=lambda *_: self.ask())
        close = ThemedButton(text="Close", icon="check", size_hint_x=0.4, height=dp(46), font_px=13)
        close.bind(on_release=lambda *_: self.pop.dismiss())
        foot.add_widget(add)
        foot.add_widget(close)
        outer.add_widget(foot)
        self.pop = style_popup(Popup(title="Quick prompts", content=outer, size_hint=(0.95, 0.85)))
        self.pop.bind(on_dismiss=lambda *_: setattr(self, "pop", None))
        self.pop.open()
        self.refresh()

    def refresh(self):
        self.listbox.clear_widgets()
        if not self.items:
            lb = Label(text="No quick prompts yet. Tap Add prompt to make one.", size_hint_y=None, height=dp(60),
                       font_name=fonts.SUB, font_size=sp(14), halign="center", valign="middle")
            lb.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
            self.listbox.add_widget(style_label(lb, "muted"))
        for i, it in enumerate(self.items):
            row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
            b = ThemedButton(text=it["label"], mode="text", wide=True, halign="center", size_hint_x=1, height=dp(48))
            b.bind(on_release=lambda _b, fill=it["fill"]: self.use(fill))
            d = RoundIcon(diameter=40, icon="trash", kind="soft")
            d.pos_hint = {"center_y": 0.5}
            d.bind(on_release=lambda _d, idx=i: self.delete(idx))
            row.add_widget(b)
            row.add_widget(d)
            self.listbox.add_widget(row)

    def use(self, fill):
        if self.pop:
            self.pop.dismiss()
        self.app.chrome.fill_entry(fill)

    def delete(self, index):
        self.items = P.delete(self.items, index)
        self._save()
        self.refresh()

    def add(self, text):
        """Append a prompt and show it. Raises ValueError (message for the user) when it cannot be added."""
        self.items = P.add(self.items, text)
        self._save()
        if self.pop is not None:
            self.refresh()
            Clock.schedule_once(self._show_newest, 0.1)

    def _show_newest(self, *_):
        """Scroll to the newest prompt, but only when the list is longer than the screen. (When it fits,
        the list must stay at the top, right under the title.)"""
        self.sv.scroll_y = 0 if self.listbox.height > self.sv.height else 1

    def _save(self):
        try:
            self.store.save(self.items)
        except OSError:
            pass  # not being able to save must not break the screen

    # ---------- the "new prompt" box ----------
    def ask(self):
        """A small box pinned to the top of the screen, so the keyboard never covers it."""
        entry = style_input(TextInput(hint_text="Type your prompt", multiline=False, write_tab=False,
                                      padding=[dp(12), dp(14)], size_hint_y=None, height=dp(48)))
        err = Label(text="", size_hint_y=None, height=dp(22), font_size=sp(12.5), halign="center", valign="middle")
        err.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        style_label(err, "sys")
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        cancel = ThemedButton(text="Cancel", mode="text", size_hint_x=0.4, height=dp(46), font_px=13)
        ok = ThemedButton(text="Add", icon="plus", kind="accent", size_hint_x=0.6, height=dp(46), font_px=13)
        row.add_widget(cancel)
        row.add_widget(ok)
        box = BoxLayout(orientation="vertical", spacing=dp(8))
        for w in (entry, err, row):
            box.add_widget(w)
        box_pop = style_popup(Popup(title="New quick prompt", content=box, size_hint=(0.92, None), height=dp(226),
                                    pos_hint={"center_x": 0.5, "top": 0.96}))
        cancel.bind(on_release=lambda *_: box_pop.dismiss())

        def submit(*_):
            try:
                self.add(entry.text)
            except ValueError as e:
                err.text = str(e)
                return
            box_pop.dismiss()
        ok.bind(on_release=submit)
        entry.bind(on_text_validate=submit)
        box_pop.open()
        Clock.schedule_once(lambda *_: setattr(entry, "focus", True), 0.25)
        return box_pop, entry, err
