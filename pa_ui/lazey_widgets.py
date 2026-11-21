"""The look of Lazey: animated orb + waves, greeting, chat bubbles, brand header, slide-out menu."""
import math
import random

from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.widget import Widget

from . import config, fonts, themes
from .widgets import IconView, T, ThemedButton, _Surface, style_label, surface

SUGGESTIONS = (("Remember ...", "Remember "), ("Note: ...", "Note: "),
               ("Call mummy from sim 1", "Call mummy from sim 1"),
               ("Show photos from yesterday", "Show photos from yesterday"))


def _ease_out_cubic(t):
    return 1 - (1 - t) ** 3


def _ease_out_back(t, k=1.9):
    """Rises past 1 and settles back (a little overshoot), for the ring popping back in."""
    t -= 1
    return 1 + (k + 1) * t ** 3 + k * t ** 2


POP_BURST = 0.20      # seconds: ring swells and vanishes
POP_GONE_UNTIL = 0.50  # seconds: ring stays away
POP_TOTAL = 1.05      # seconds: ring is back, animation over
SPARKS = 14


class Orb(Widget):
    """A glowing ring with flowing wave ribbons. Animates (~24 fps) only while `active`.
    Tap the ring and it pops (shockwave + sparks), disappears for a moment and pops back in."""
    active = BooleanProperty(False)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.t = 0.0
        self._ev = None
        self._hz = 0
        self.pop = None        # seconds since the tap, or None when idle
        self._sparks = []
        self.bind(pos=self.redraw, size=self.redraw, active=self._toggle)
        T.bind(version=self.redraw)

    def _schedule(self, hz):
        if self._ev is not None and self._hz == hz:
            return
        if self._ev is not None:
            self._ev.cancel()
        self._hz = hz
        self._ev = Clock.schedule_interval(self._tick, 1.0 / hz)

    def _toggle(self, *_):
        if self.active:
            self._schedule(60 if self.pop is not None else 24)
        elif self._ev is not None:
            self._ev.cancel()
            self._ev, self._hz = None, 0
        self.redraw()

    def _radius(self):
        return min(self.height * 0.30, dp(52))

    def on_touch_down(self, touch):
        if self.active and self.pop is None:
            r = self._radius() * 1.5   # a generous target around the ring
            if (touch.x - self.center_x) ** 2 + (touch.y - self.center_y) ** 2 <= r * r:
                self.pop = 0.0
                self._sparks = [(random.uniform(0, 2 * math.pi), random.uniform(0.85, 1.6), random.uniform(0.7, 1.3))
                                for _ in range(SPARKS)]
                self._schedule(60)   # smooth while it plays
                return True
        return super().on_touch_down(touch)

    def _tick(self, dt):
        self.t += dt
        if self.pop is not None:
            self.pop += dt
            if self.pop >= POP_TOTAL:
                self.pop, self._sparks = None, []
                self._schedule(24)
        self.redraw()

    def _ring(self):
        """(scale, opacity) of the ring right now."""
        p = self.pop
        if p is None:
            return 1.0, 1.0
        if p < POP_BURST:
            u = p / POP_BURST
            return 1.0 + 0.35 * _ease_out_cubic(u), 1.0 - u
        if p < POP_GONE_UNTIL:
            return 0.0, 0.0
        u = (p - POP_GONE_UNTIL) / (POP_TOTAL - POP_GONE_UNTIL)
        return max(0.0, _ease_out_back(min(1.0, u))), min(1.0, u * 3)

    def redraw(self, *_):
        self.canvas.clear()
        if self.width <= 0 or self.height <= 0:
            return
        cx, cy = self.center_x, self.center_y
        r0 = self._radius()
        scale, vis = self._ring()
        r = r0 * scale
        a1, a2 = T.c("accent"), T.c("accent2")
        light = themes.hex_to_rgba(themes.mix(T.h("accent"), "#ffffff", 0.45))
        t, n = self.t, 72
        amp = self.height * 0.21
        with self.canvas:
            for i in range(8):  # soft glow behind the ring
                f = (8 - i) / 8.0
                rr = r0 * (1.15 + f * 1.5) * (0.6 + 0.4 * scale)
                Color(a1[0], a1[1], a1[2], 0.03 * (0.3 + 0.7 * vis))
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
            if self.pop is not None:
                self._draw_burst(cx, cy, r0, a1, light)
            if r > dp(1) and vis > 0.02:
                Color(*themes.hex_to_rgba(T.h("bg"), 0.8 * vis))   # hides ribbons behind the ring
                Ellipse(pos=(cx - r, cy - r), size=(2 * r, 2 * r))
                for w, alpha in ((dp(9), 0.07), (dp(5), 0.13), (dp(2.4), 0.95)):
                    Color(light[0], light[1], light[2], alpha * vis)
                    Line(circle=(cx, cy, r), width=w)
                for k, (col, alpha) in enumerate(((a1, 0.95), (light, 0.7), (a2, 0.8))):   # waves inside the ring
                    Color(col[0], col[1], col[2], alpha * vis)
                    pts = []
                    for i in range(41):
                        u = i / 40 * 2 - 1
                        pts += [cx + u * r * 0.82,
                                cy + r * 0.34 * math.cos(u * math.pi / 2) * math.sin(u * 3.2 + t * 1.6 + k * 0.9)]
                    Line(points=pts, width=dp(1.3))

    def _draw_burst(self, cx, cy, r0, accent, light):
        """Shockwave ring + sparks flying outwards, drawn while the ring pops."""
        p = self.pop
        if p < 0.6:
            u = p / 0.6
            Color(light[0], light[1], light[2], 0.85 * (1 - u))
            Line(circle=(cx, cy, r0 * (1.0 + 1.7 * _ease_out_cubic(u))), width=max(dp(0.8), dp(3.2) * (1 - u)))
        if p < 0.55:
            u = p / 0.55
            for i, (ang, speed, size) in enumerate(self._sparks):
                dist = r0 * (1.0 + 2.3 * speed * _ease_out_cubic(u))
                rad = dp(3.6) * size * (1 - 0.6 * u)
                col = light if i % 2 == 0 else accent
                Color(col[0], col[1], col[2], 1 - u)
                Ellipse(pos=(cx + math.cos(ang) * dist - rad, cy + math.sin(ang) * dist - rad), size=(2 * rad, 2 * rad))


class Hero(BoxLayout):
    """Empty-state greeting: the orb, "Hey" and a one-line question."""

    def __init__(self, **kw):
        super().__init__(orientation="vertical", size_hint=(1, None), spacing=dp(6), **kw)
        self.orb = Orb(size_hint_y=None, height=dp(210))
        self.hey = Label(text="Hey", font_name=fonts.HEADING, size_hint_y=None, height=dp(56), font_size=sp(38))
        self.ask = Label(text="What can I help you with today?", font_name=fonts.SUB, size_hint_y=None, height=dp(30),
                         font_size=sp(16))
        self._tint()
        T.bind(version=self._tint)
        for w in (self.orb, self.hey, self.ask):
            self.add_widget(w)
        self.height = sum(c.height for c in self.children) + dp(6) * 2
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
        if T.bubbles == "plain":
            self.label._surf = None
            return
        if self.who == "sys":   # notes and errors: a soft pill tinted with the theme's own note colour
            self.label._surf = _Surface(self.label, fill="surface", border=0.45, radius=16, tint=0.14, tint_role="sys")
            return
        self.label._surf = _Surface(self.label, fill="surface", border=0.55 if self.who == "user" else 0.12,
                                    tint=0.22 if self.who == "user" else 0.0)


class Brand(BoxLayout):
    """Wave logo + "Lazey" with the tagline pill underneath."""

    def __init__(self, align="center", tagline=True, **kw):
        super().__init__(orientation="vertical", spacing=dp(4), **kw)
        row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
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
