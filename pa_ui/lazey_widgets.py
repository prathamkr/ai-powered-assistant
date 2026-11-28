"""The look of Lazey: animated orb + waves, greeting, chat bubbles, brand header, slide-out menu."""
import datetime
import math
import random
import time

from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.widget import Widget

from . import config, fonts, themes
from .iconset import glyph
from .widgets import IconView, T, ThemedButton, _Surface, style_label, surface

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

    shown = True

    def show(self, on):
        # Hidden = invisible AND out of the way of touches. (It used to be disabled instead, and a
        # disabled Kivy widget swallows every touch on it: the hidden greeting sat over the chat and
        # ate taps on chat buttons, e.g. the first tap while the keyboard was open.)
        self.shown = bool(on)
        self.opacity = 1 if on else 0
        self.orb.active = bool(on)

    def on_touch_down(self, touch):
        return super().on_touch_down(touch) if self.shown else False

    def on_touch_move(self, touch):
        return super().on_touch_move(touch) if self.shown else False

    def on_touch_up(self, touch):
        return super().on_touch_up(touch) if self.shown else False


def clock_text(ts):
    """'7:31 PM' for a unix time."""
    t = time.localtime(ts)
    return "%d:%02d %s" % (t.tm_hour % 12 or 12, t.tm_min, "AM" if t.tm_hour < 12 else "PM")


def day_text(ts, now=None):
    """'Today', 'Yesterday' or '26 Nov 2026' for the day chip between messages."""
    d = datetime.date.fromtimestamp(ts)
    today = datetime.date.fromtimestamp(now if now is not None else time.time())
    if d == today:
        return "Today"
    if d == today - datetime.timedelta(days=1):
        return "Yesterday"
    return "%d %s %d" % (d.day, d.strftime("%b"), d.year)


class Avatar(Widget):
    """Lazey's small round avatar (accent disc + wave icon) next to its messages."""

    def __init__(self, diameter=28, **kw):
        super().__init__(size_hint=(None, None), size=(dp(diameter), dp(diameter)), **kw)
        self.icon = IconView("wave", size_hint=(None, None))
        self.add_widget(self.icon)
        self.bind(pos=self._draw, size=self._draw)
        T.bind(version=self._draw)
        self._draw()

    def _draw(self, *_):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*themes.hex_to_rgba(themes.mix(T.h("surface"), T.h("user_bubble"), 0.55)))
            Ellipse(pos=self.pos, size=self.size)
        pad = self.width * 0.2
        self.icon.size = (self.width - 2 * pad, self.height - 2 * pad)
        self.icon.pos = (self.x + pad, self.y + pad)
        self.icon.set_color(themes.hex_to_rgba("#ffffff"))


class Bubble(BoxLayout):
    """One chat message, like a messaging app. who: "user" (right, filled with the accent colour,
    time + double tick), "bot" (left, with Lazey's avatar, time) or "sys" (centred note)."""

    def __init__(self, text, who="bot", ts=None, **kw):
        super().__init__(size_hint_y=None, spacing=dp(6), **kw)
        self.who = who
        self.ts = ts if ts is not None else time.time()
        self.px, self.py = dp(12), dp(8)
        self.label = Label(text=text, size_hint=(None, None), halign="left" if who != "sys" else "center",
                           valign="top")
        self.meta = Label(text="", markup=True, size_hint=(None, None), halign="right", valign="bottom")
        self.box = Widget(size_hint=(None, None))   # the bubble itself: text on top, time underneath
        self.box.add_widget(self.label)
        if who != "sys":
            self.box.add_widget(self.meta)
        self.avatar = Avatar() if who == "bot" else None
        self.bind(width=self._wrap)
        self.label.bind(texture_size=self._fit)
        self.meta.bind(texture_size=self._fit)
        self.box.bind(pos=self._place)
        T.bind(version=self._style)
        if who == "user":
            self.add_widget(Widget())
            self.add_widget(self.box)
        elif who == "bot":
            holder = BoxLayout(orientation="vertical", size_hint=(None, 1), width=self.avatar.width)
            holder.add_widget(Widget())
            holder.add_widget(self.avatar)        # the avatar sits at the bottom, by the bubble's corner
            self.add_widget(holder)
            self.add_widget(self.box)
            self.add_widget(Widget())
        else:
            self.add_widget(Widget())
            self.add_widget(self.box)
            self.add_widget(Widget())
        self.box._surf = None
        self._style()
        self._wrap()

    def _natural_width(self):
        """Width of the longest line if it were not wrapped (a short message gets a short bubble: with a
        fixed wrap width Kivy renders every text as wide as that width)."""
        try:
            self.label.texture_update()
            return max(self.label._label.get_extents(line)[0] for line in (self.label.text or " ").split("\n"))
        except Exception:
            return None

    def _wrap(self, *_):
        if self.who == "sys":
            limit = self.width * 0.92
        else:
            limit = self.width * 0.78 - (self.avatar.width + dp(6) if self.avatar else 0)
        limit = max(dp(60), limit - 2 * self.px)
        nat = self._natural_width()
        w = min(limit, nat + dp(2)) if nat else limit
        if self.label.text_size[0] != w:
            self.label.text_size = (w, None)

    def _fit(self, *_):
        tw, th = self.label.texture_size
        mw, mh = self.meta.texture_size if self.who != "sys" else (0, 0)
        self.label.size = (tw, th)
        self.meta.size = (mw, mh)
        # the time goes on the last text line when it fits there, else on its own line (like chat apps)
        limit = (self.width * 0.78 - (self.avatar.width + dp(6) if self.avatar else 0)) - 2 * self.px
        inline = self.who != "sys" and th <= self.label.font_size * 1.6 and tw + mw + dp(10) <= limit
        w = (tw + mw + dp(10) if inline else max(tw, mw)) + 2 * self.px
        h = th + (0 if inline or self.who == "sys" else mh + dp(2)) + 2 * self.py
        self.box.size = (w, h)
        self.height = h + dp(6)
        self._inline = inline
        self._place()

    def _place(self, *_):
        bx, by = self.box.pos
        self.label.pos = (bx + self.px, by + self.box.height - self.py - self.label.height)
        self.meta.pos = (bx + self.box.width - self.px - self.meta.width, by + self.py - dp(2))

    def _style(self, *_):
        self.label.font_size = sp(15 * T.font_scale)
        self.meta.font_size = sp(10.5 * T.font_scale)
        if self.who == "user":
            fg = T.c("user_bubble_text")
            self.label.color = fg
            tick = "[font=%s]%s[/font]" % (fonts.ICON, glyph("done_all"))
            self.meta.text = "%s %s" % (clock_text(self.ts), tick)
            self.meta.color = (fg[0], fg[1], fg[2], 0.75)
        else:
            self.label.color = T.c("sys" if self.who == "sys" else "bot")
            self.meta.text = clock_text(self.ts)
            self.meta.color = T.c("muted")
        self.box.canvas.before.clear()
        if self.who == "sys":   # notes and errors: a soft pill tinted with the theme's own note colour
            self.box._surf = _Surface(self.box, fill="surface", border=0.45, radius=16, tint=0.14, tint_role="sys")
        elif self.who == "user":
            self.box._surf = _Surface(self.box, fill="user_bubble", border=0, radius=18, corners=(1, 1, 0.22, 1))
        else:
            self.box._surf = _Surface(self.box, fill="surface", border=0, radius=18, corners=(1, 1, 1, 0.22))
        self._wrap()   # the font size may have changed: measure the text again


class DayChip(BoxLayout):
    """'Today' / 'Yesterday' / a date, centred between messages of different days."""

    def __init__(self, ts, **kw):
        super().__init__(size_hint_y=None, height=dp(34), padding=(0, dp(6)), **kw)
        self.label = Label(text=day_text(ts), font_size=sp(12), size_hint=(None, 1))
        self.label.bind(texture_size=lambda *_: setattr(self.label, "width", self.label.texture_size[0] + dp(24)))
        surface(self.label, fill="surface", border=0, radius=11)
        self.add_widget(Widget())
        self.add_widget(self.label)
        self.add_widget(Widget())
        T.bind(version=self._tint)
        self._tint()

    def _tint(self, *_):
        self.label.color = T.c("muted")


class Typing(BoxLayout):
    """Lazey's avatar + a small bubble with three bouncing dots while a reply is being worked out."""

    def __init__(self, **kw):
        super().__init__(size_hint_y=None, height=dp(42), spacing=dp(6), **kw)
        holder = BoxLayout(orientation="vertical", size_hint=(None, 1), width=dp(28))
        holder.add_widget(Widget())
        holder.add_widget(Avatar())
        self.add_widget(holder)
        self.dots = Widget(size_hint=(None, None), size=(dp(58), dp(34)))
        self.dots._surf = _Surface(self.dots, fill="surface", border=0, radius=18, corners=(1, 1, 1, 0.22))
        self.add_widget(self.dots)
        self.add_widget(Widget())
        self.t = 0.0
        self._ev = Clock.schedule_interval(self._tick, 1 / 20.0)

    def _tick(self, dt):
        self.t += dt
        d = self.dots
        d.canvas.after.clear()
        col = T.c("muted")
        with d.canvas.after:
            for i in range(3):
                ph = (self.t * 2.2 - i * 0.28) % 1.0
                lift = math.sin(ph * math.pi) * dp(4) if ph < 1.0 else 0
                Color(col[0], col[1], col[2], 0.45 + 0.55 * math.sin(ph * math.pi))
                r = dp(3.5)
                Ellipse(pos=(d.x + dp(15) + i * dp(12) - r, d.center_y - r + lift), size=(2 * r, 2 * r))

    def stop(self):
        if self._ev is not None:
            self._ev.cancel()
            self._ev = None


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
        self.pill = self.dot = None
        if tagline:
            # a chat header's status line: green dot + "online" (Lazey works offline, on the phone, so it
            # is always there to answer)
            holder = BoxLayout(size_hint_y=None, height=dp(20), spacing=dp(6))
            self.dot = Widget(size_hint=(None, None), size=(dp(8), dp(8)))
            self.dot.pos_hint = {"center_y": 0.5}
            self.dot.bind(pos=self._draw_dot, size=self._draw_dot)
            self.pill = Label(text="online", font_name=fonts.SUB, font_size=sp(13), size_hint=(None, 1))
            self.pill.bind(texture_size=lambda *_: setattr(self.pill, "width", self.pill.texture_size[0]))
            if align == "center":
                holder.add_widget(Widget())
            holder.add_widget(self.dot)
            holder.add_widget(self.pill)
            holder.add_widget(Widget())
            self.add_widget(holder)
        T.bind(version=self._tint)
        self._tint()

    def _draw_dot(self, *_):
        if self.dot is None:
            return
        self.dot.canvas.clear()
        with self.dot.canvas:
            Color(*T.c("online"))
            Ellipse(pos=self.dot.pos, size=self.dot.size)

    def _tint(self, *_):
        self.title.color = T.c("text")
        self.logo.set_color(themes.hex_to_rgba(themes.mix(T.h("accent"), "#ffffff", 0.25)))
        if self.pill is not None:
            self.pill.color = T.c("muted")
        self._draw_dot()


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
