"""The look of Lazey: animated orb + waves, greeting, chat bubbles, brand header, slide-out menu."""
import math

from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.widget import Widget

from . import config, fonts, themes
from .widgets import IconView, T, ThemedButton, _Surface, style_label, surface

SUGGESTIONS = (("Remember ...", "Remember "), ("Note: ...", "Note: "),
               ("Call mummy from sim 1", "Call mummy from sim 1"),
               ("Show photos from yesterday", "Show photos from yesterday"))


class Orb(Widget):
    """A glowing ring with flowing wave ribbons. Animates (~24 fps) only while `active`."""
    active = BooleanProperty(False)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.t = 0.0
        self._ev = None
        self.bind(pos=self.redraw, size=self.redraw, active=self._toggle)
        T.bind(version=self.redraw)

    def _toggle(self, *_):
        if self.active and self._ev is None:
            self._ev = Clock.schedule_interval(self._tick, 1 / 24.0)
        elif not self.active and self._ev is not None:
            self._ev.cancel()
            self._ev = None
        self.redraw()

    def _tick(self, dt):
        self.t += dt
        self.redraw()

    def redraw(self, *_):
        self.canvas.clear()
        if self.width <= 0 or self.height <= 0:
            return
        cx, cy = self.center_x, self.center_y
        r = min(self.height * 0.30, dp(52))
        a1, a2 = T.c("accent"), T.c("accent2")
        light = themes.hex_to_rgba(themes.mix(T.h("accent"), "#ffffff", 0.45))
        t, n = self.t, 72
        amp = self.height * 0.21
        with self.canvas:
            for i in range(8):  # soft glow behind the ring
                f = (8 - i) / 8.0
                rr = r * (1.15 + f * 1.5)
                Color(a1[0], a1[1], a1[2], 0.03)
                Ellipse(pos=(cx - rr, cy - rr), size=(2 * rr, 2 * rr))
            ribbons = ((a1, 0.0, 2.2, 0.9, 0.55), (a2, 0.55, 2.6, 1.15, 0.5), (light, 1.1, 2.0, 0.75, 0.38),
                       (a1, 1.7, 3.0, 1.0, 0.3), (a2, 2.3, 2.4, 0.6, 0.3))
            for col, ph, freq, speed, alpha in ribbons:
                Color(col[0], col[1], col[2], alpha)
                pts = []
                for i in range(n + 1):
                    u = i / n * 2 - 1
                    env = 0.15 + 0.85 * min(1.0, abs(u) * 1.5) ** 1.3
                    pts += [self.x + (u + 1) / 2 * self.width,
                            cy + amp * env * math.sin(u * freq * math.pi + t * speed + ph)]
                Line(points=pts, width=dp(1.1))
            Color(*themes.hex_to_rgba(T.h("bg"), 0.8))   # hides ribbons behind the ring
            Ellipse(pos=(cx - r, cy - r), size=(2 * r, 2 * r))
            for w, alpha in ((dp(9), 0.07), (dp(5), 0.13), (dp(2.4), 0.95)):
                Color(light[0], light[1], light[2], alpha)
                Line(circle=(cx, cy, r), width=w)
            for k, (col, alpha) in enumerate(((a1, 0.95), (light, 0.7), (a2, 0.8))):   # waves inside the ring
                Color(col[0], col[1], col[2], alpha)
                pts = []
                for i in range(41):
                    u = i / 40 * 2 - 1
                    pts += [cx + u * r * 0.82, cy + r * 0.34 * math.cos(u * math.pi / 2) * math.sin(u * 3.2 + t * 1.6 + k * 0.9)]
                Line(points=pts, width=dp(1.3))


class Hero(BoxLayout):
    """Empty-state greeting: orb, "Hey", a one-line question and tap-to-fill example prompts."""

    def __init__(self, on_pick, **kw):
        super().__init__(orientation="vertical", size_hint=(1, None), spacing=dp(6), **kw)
        self.orb = Orb(size_hint_y=None, height=dp(210))
        self.hey = Label(text="Hey", font_name=fonts.HEADING, size_hint_y=None, height=dp(56), font_size=sp(38))
        self.ask = Label(text="What can I help you with today?", font_name=fonts.SUB, size_hint_y=None, height=dp(30),
                         font_size=sp(16))
        self._tint()
        T.bind(version=self._tint)
        grid = GridLayout(cols=2, size_hint_y=None, height=dp(88), spacing=dp(8), padding=[dp(14), dp(8), dp(14), 0])
        for label, fill in SUGGESTIONS:
            b = ThemedButton(text=label, mode="text", kind="ghost", wide=True, halign="center", font_px=12, height=dp(38))
            b.bind(on_release=lambda _b, f=fill: on_pick(f))
            grid.add_widget(b)
        for w in (self.orb, self.hey, self.ask, grid):
            self.add_widget(w)
        self.height = sum(c.height for c in self.children) + dp(6) * 3
        style_label(self.ask, "muted")

    def _tint(self, *_):
        self.hey.color = themes.hex_to_rgba(themes.mix(T.h("text"), T.h("accent"), 0.45))

    def show(self, on):
        self.opacity = 1 if on else 0
        self.disabled = not on
        self.orb.active = bool(on)


class Bubble(BoxLayout):
    """One chat message. who: "user" (right, tinted), "bot" (left, card) or "sys" (centered note)."""

    def __init__(self, text, who="bot", **kw):
        super().__init__(size_hint_y=None, **kw)
        self.who = who
        self.px, self.py = dp(14), dp(10)
        self.label = Label(text=text, size_hint=(None, None), halign="left" if who != "sys" else "center",
                           valign="top", padding=(self.px, self.py))
        self.bind(width=self._wrap)
        self.label.bind(texture_size=self._fit)
        T.bind(version=self._style)
        if who == "user":
            self.add_widget(Widget())
            self.add_widget(self.label)
        elif who == "bot":
            self.add_widget(self.label)
            self.add_widget(Widget())
        else:
            self.add_widget(Widget())
            self.add_widget(self.label)
            self.add_widget(Widget())
        self.label._surf = None
        self._style()
        self._wrap()

    def _wrap(self, *_):
        frac = 0.92 if self.who == "sys" else 0.84
        self.label.text_size = (max(dp(60), self.width * frac - 2 * self.px), None)

    def _fit(self, *_):
        w, h = self.label.texture_size
        self.label.size = (w + 2 * self.px, h + 2 * self.py)
        self.height = self.label.height + dp(6)

    def _style(self, *_):
        role = {"user": "user", "bot": "bot", "sys": "sys"}[self.who]
        self.label.color = T.c(role)
        self.label.font_size = sp(15 * T.font_scale)
        self.label.canvas.before.clear()
        if T.bubbles == "plain" or self.who == "sys":
            self.label._surf = None
            return
        self.label._surf = _Surface(self.label, fill="surface", border=0.55 if self.who == "user" else 0.12,
                                    tint=0.22 if self.who == "user" else 0.0)


class Brand(BoxLayout):
    """Wave logo + "Lazey" with the tagline pill underneath."""

    def __init__(self, align="center", tagline=True, **kw):
        super().__init__(orientation="vertical", spacing=dp(4), **kw)
        row = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(8))
        self.logo = IconView("wave", size_hint=(None, None), size=(dp(34), dp(34)))
        self.logo.pos_hint = {"center_y": 0.5}
        self.title = Label(text=config.APP_NAME, font_name=fonts.HEADING, font_size=sp(24), size_hint_x=None,
                           valign="middle")
        self.title.bind(texture_size=lambda *_: setattr(self.title, "width", self.title.texture_size[0]))
        left, right = Widget(), Widget()
        if align == "center":
            row.add_widget(left)
        row.add_widget(self.logo)
        row.add_widget(self.title)
        row.add_widget(right)
        self.add_widget(row)
        self.pill = None
        if tagline:
            holder = BoxLayout(size_hint_y=None, height=dp(26))
            self.pill = Label(text=config.TAGLINE, font_name=fonts.SUB, font_size=sp(12), size_hint=(None, 1),
                              padding=(dp(14), 0))
            self.pill.bind(texture_size=lambda *_: setattr(self.pill, "width", self.pill.texture_size[0] + dp(28)))
            surface(self.pill, fill="surface", border=0.25, radius=13, tint=0.1)
            if align == "center":
                holder.add_widget(Widget())
            holder.add_widget(self.pill)
            holder.add_widget(Widget())
            self.add_widget(holder)
        T.bind(version=self._tint)
        self._tint()

    def _tint(self, *_):
        self.title.color = T.c("text")
        self.logo.set_color(themes.hex_to_rgba(themes.mix(T.h("accent"), "#ffffff", 0.25)))
        if self.pill is not None:
            self.pill.color = T.c("muted")


class Drawer(ModalView):
    """Slide-out style menu: a floating card listing the buttons placed in the "menu" region."""

    def __init__(self, items, side="left", **kw):
        super().__init__(size_hint=(0.82, 0.94), pos_hint={("x" if side == "left" else "right"): 0.025 if side == "left" else 0.975,
                                                           "center_y": 0.5},
                         background="", background_color=(0, 0, 0, 0), overlay_color=(0, 0, 0, 0.6), **kw)
        panel = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(6))
        surface(panel, fill="panel", border=0.3, radius=28)
        head = Brand(align="left", tagline=True, size_hint_y=None, height=dp(70))
        panel.add_widget(head)
        panel.add_widget(Widget(size_hint_y=None, height=dp(14)))
        self._items = []
        for it in items:
            b = ThemedButton(text=it["label"], icon=it["icon"], kind="ghost", wide=True, halign="left", font_px=16,
                             height=dp(56))
            b.bind(on_release=lambda _b, i=it: self._choose(i))
            panel.add_widget(b)
        panel.add_widget(Widget())
        self.add_widget(panel)
        self.on_choose = None

    def _choose(self, item):
        self.dismiss()
        if self.on_choose:
            Clock.schedule_once(lambda *_: self.on_choose(item), 0.05)
