"""The Theme screen: pick one of the built-in themes. The change applies to the real screen at once
(live preview behind the pop-up) and is saved."""
from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from . import config, fonts, themes
from .widgets import T, ThemedButton, gradient_texture, style_label, style_popup


class ThemeCard(ButtonBehavior, BoxLayout):
    """Mini preview of a theme: gradient background, a button, the accent and two text lines."""

    def __init__(self, name, colors, selected, height=86, **kw):
        super().__init__(orientation="vertical", size_hint_y=None, height=dp(height), padding=dp(6), **kw)
        self.colors, self.selected = colors, selected
        self.caption = Label(text=name, size_hint_y=None, height=dp(22), font_size=sp(12.5), shorten=True,
                             shorten_from="right", halign="center", valign="middle",
                             color=themes.hex_to_rgba(colors["text"]))
        self.caption.bind(size=lambda *_: setattr(self.caption, "text_size", self.caption.size))
        self.add_widget(Widget())
        self.add_widget(self.caption)
        self.bind(pos=self._draw, size=self._draw)
        self._draw()

    def _draw(self, *_):
        c = {k: themes.hex_to_rgba(v) for k, v in self.colors.items()}
        x, y, w, h = self.x, self.y, self.width, self.height
        tex = gradient_texture(self.colors["bg2"], self.colors["bg2"], self.colors["bg"], self.colors["bg"])
        self.canvas.before.clear()
        with self.canvas.before:
            Color(1, 1, 1, 1)
            RoundedRectangle(pos=(x, y), size=(w, h), radius=[dp(12)], texture=tex)
            Color(*c["button"])
            RoundedRectangle(pos=(x + dp(8), y + h - dp(32)), size=(w * 0.36, dp(20)), radius=[dp(10)])
            Color(*c["accent"])
            RoundedRectangle(pos=(x + w * 0.36 + dp(14), y + h - dp(32)), size=(w * 0.2, dp(20)), radius=[dp(10)])
            Color(*c["user"])
            Rectangle(pos=(x + dp(8), y + h - dp(43)), size=(w * 0.5, dp(3)))
            Color(*c["muted"])
            Rectangle(pos=(x + dp(8), y + h - dp(49)), size=(w * 0.32, dp(3)))
            if self.selected:
                Color(*T.c("accent"))
                Line(rounded_rectangle=(x, y, w, h, dp(12)), width=dp(2.5))
            else:
                Color(0.5, 0.5, 0.6, 0.45)
                Line(rounded_rectangle=(x, y, w, h, dp(12)), width=dp(1))


class StyleEditor:
    def __init__(self, chrome):
        self.chrome = chrome
        self.pop = None
        self.grid = None

    @property
    def cfg(self):
        return self.chrome.cfg

    def open(self):
        if self.pop is not None:
            return
        outer = BoxLayout(orientation="vertical", spacing=dp(10))
        hint = Label(text="Tap a theme to use it", size_hint_y=None, height=dp(28), font_name=fonts.SUB,
                     font_size=sp(13), halign="center", valign="middle")
        hint.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        outer.add_widget(style_label(hint, "muted"))
        self.grid = GridLayout(cols=2, size_hint_y=None, spacing=dp(8))
        self.grid.bind(minimum_height=self.grid.setter("height"))
        sv = ScrollView(bar_width=dp(4))
        sv.add_widget(self.grid)
        outer.add_widget(sv)
        done = ThemedButton(text="Done", mode="text", height=dp(46), size_hint_x=1, kind="accent", font_px=14)
        done.bind(on_release=lambda *_: self.pop.dismiss())
        outer.add_widget(done)
        self.pop = style_popup(Popup(title="Theme", content=outer, size_hint=(0.94, 0.8), auto_dismiss=False))
        self.pop.bind(on_dismiss=lambda *_: setattr(self, "pop", None))
        self.pop.open()
        self.refresh()

    def refresh(self):
        self.grid.clear_widgets()
        for tid, (name, colors) in themes.BUILTIN.items():
            card = ThemeCard(name, colors, tid == self.cfg["theme"])
            card.bind(on_release=lambda _c, t=tid: self.pick(t))
            self.grid.add_widget(card)

    def pick(self, theme_id):
        self.chrome.apply(config.set_theme(self.cfg, theme_id))
        self.refresh()
