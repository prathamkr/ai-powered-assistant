"""Kivy building blocks that follow the current theme: one global ThemeState, an icon view, buttons,
gradient helpers and surfaces. Widgets bind to ThemeState.version, so changing the theme restyles
everything live.
"""
import weakref

from kivy.core.window import Window
from kivy.event import EventDispatcher
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle
from kivy.graphics.texture import Texture
from kivy.metrics import dp, sp
from kivy.properties import (BooleanProperty, DictProperty, NumericProperty, OptionProperty, StringProperty)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from . import config, themes
from .iconset import ICONS


class ThemeState(EventDispatcher):
    """Holds the resolved colours + layout numbers. `version` changes whenever anything does."""
    version = NumericProperty(0)
    hexes = DictProperty({})
    radius = NumericProperty(22)
    font_scale = NumericProperty(1.0)
    btn_h = NumericProperty(56)
    spacing = NumericProperty(8)
    label_mode = StringProperty("icon_text")
    stack = StringProperty("side")
    bubbles = StringProperty("bubbles")

    def apply(self, cfg):
        self.hexes = config.current_colors(cfg)
        lay = cfg["layout"]
        self.radius, self.font_scale, self.btn_h, self.spacing = lay["radius"], lay["font_scale"], lay["btn_h"], lay["spacing"]
        self.bubbles = lay["bubbles"]
        Window.clearcolor = self.c("bg")
        self.version += 1

    def c(self, role, alpha=1.0):
        return themes.hex_to_rgba(self.hexes[role], alpha)

    def h(self, role):
        return self.hexes[role]


T = ThemeState()
T.apply(config.default_config())  # sane defaults before the app loads its saved config


# ---------- gradients ----------
_TEX = {}


def gradient_texture(bl, br, tl, tr):
    """2x2 texture (hex colours at the four corners); stretched and linearly filtered it is a smooth gradient."""
    key = (bl, br, tl, tr)
    tex = _TEX.get(key)
    if tex is None:
        if len(_TEX) > 64:
            _TEX.clear()
        data = b""
        for h in (bl, br, tl, tr):  # row 0 = bottom
            r, g, b, _ = themes.hex_to_rgba(h)
            data += bytes((int(r * 255), int(g * 255), int(b * 255), 255))
        tex = Texture.create(size=(2, 2), colorfmt="rgba")
        tex.blit_buffer(data, colorfmt="rgba", bufferfmt="ubyte")
        tex.mag_filter = tex.min_filter = "linear"
        _TEX[key] = tex
    return tex


# ---------- icons ----------
class IconView(Widget):
    name = StringProperty("none")
    rgba = None

    def __init__(self, name="none", rgba=(1, 1, 1, 1), **kw):
        super().__init__(**kw)
        self.name, self.rgba = name, tuple(rgba)
        self.bind(pos=self.redraw, size=self.redraw, name=self.redraw)
        self.redraw()

    def set_color(self, rgba):
        self.rgba = tuple(rgba)
        self.redraw()

    def redraw(self, *_):
        self.canvas.clear()
        prims = ICONS.get(self.name, [])
        s = min(self.width, self.height)
        if not prims or s <= 0:
            return
        x0, y0 = self.center_x - s / 2, self.center_y - s / 2
        lw = max(dp(1.3), s * 0.072)
        with self.canvas:
            Color(*self.rgba)
            for p in prims:
                if p[0] == "l":
                    flat = []
                    for x, y in p[1]:
                        flat += [x0 + x * s, y0 + y * s]
                    Line(points=flat, width=lw, cap="round", joint="round", close=bool(p[2]))
                else:
                    r = p[3] * s
                    Ellipse(pos=(x0 + p[1] * s - r, y0 + p[2] * s - r), size=(2 * r, 2 * r))


# ---------- round icon button (menu, avatar, mic, send...) ----------
class RoundIcon(ButtonBehavior, Widget):
    """Circular icon button. kind: "flat" (icon only), "soft" (tinted disc) or "accent" (gradient disc)."""
    icon = StringProperty("none")
    kind = OptionProperty("flat", options=["flat", "soft", "accent"])
    dot = StringProperty("")  # "" or a status colour role ("ok", "busy", "error") drawn at the corner

    def __init__(self, diameter=44, **kw):
        kw.setdefault("size_hint", (None, None))
        kw.setdefault("size", (dp(diameter), dp(diameter)))
        super().__init__(**kw)
        self._icon = IconView(size_hint=(None, None))
        self.add_widget(self._icon)
        self.bind(pos=self._draw, size=self._draw, icon=self._draw, kind=self._draw, state=self._draw,
                  disabled=self._draw, dot=self._draw)
        T.bind(version=self._draw)
        self._draw()

    def _draw(self, *_):
        d = min(self.width, self.height)
        cx, cy = self.center_x, self.center_y
        alpha = 0.4 if self.disabled else 1.0
        down = self.state == "down"
        self.canvas.before.clear()
        self.canvas.after.clear()
        if self.kind == "accent":
            fg = themes.best_on(themes.mix(T.h("accent"), T.h("accent2"), 0.5))
            tex = gradient_texture(T.h("accent2"), T.h("accent2"), T.h("accent"), T.h("accent2"))
            with self.canvas.before:
                Color(0.5, 0.5, 0.6, 0.10 * alpha)
                Ellipse(pos=(cx - d / 2 - dp(3), cy - d / 2 - dp(3)), size=(d + dp(6), d + dp(6)))
                Color(1, 1, 1, alpha)
                Ellipse(pos=(cx - d / 2, cy - d / 2), size=(d, d), texture=tex)
        elif self.kind == "soft":
            fg = T.h("accent")
            fg = themes.mix(T.h("text"), T.h("accent"), 0.5)
            with self.canvas.before:
                Color(*themes.hex_to_rgba(themes.mix(T.h("surface"), T.h("accent"), 0.22), alpha))
                Ellipse(pos=(cx - d / 2, cy - d / 2), size=(d, d))
                Color(*themes.hex_to_rgba(themes.mix(T.h("surface"), T.h("accent"), 0.5), 0.8 * alpha))
                Line(circle=(cx, cy, d / 2 - dp(0.5)), width=dp(1))
        else:
            fg = themes.mix(T.h("text"), T.h("accent"), 0.35)
        if down:
            with self.canvas.before:
                Color(1, 1, 1, 0.14)
                Ellipse(pos=(cx - d / 2, cy - d / 2), size=(d, d))
        isz = d * (0.5 if self.kind == "accent" else 0.58)
        self._icon.size = (isz, isz)
        self._icon.pos = (cx - isz / 2, cy - isz / 2)
        self._icon.name = self.icon
        self._icon.set_color(themes.hex_to_rgba(fg, alpha))
        if self.dot:
            col = {"ok": "#22c55e", "busy": "#f59e0b", "error": "#ef4444"}.get(self.dot, "#22c55e")
            r = d * 0.13
            with self.canvas.after:
                Color(*themes.hex_to_rgba(T.h("bg")))
                Ellipse(pos=(cx + d * 0.28 - r - dp(1.5), cy - d * 0.34 - r - dp(1.5)), size=(2 * r + dp(3), 2 * r + dp(3)))
                Color(*themes.hex_to_rgba(col))
                Ellipse(pos=(cx + d * 0.28 - r, cy - d * 0.34 - r), size=(2 * r, 2 * r))


# ---------- rounded text/icon button (dialogs, chips, menu rows) ----------
class ThemedButton(ButtonBehavior, BoxLayout):
    """Rounded button with an optional vector icon and label. Follows the theme live.

    kind: "normal" | "accent" (gradient accent fill) | "selected" (a chip that is on) | "ghost" (no fill).
    mode: "default" (icon + text) or icon_text / icon / text.
    wide: the label fills the button (used for left-aligned rows); otherwise the button is as wide
          as its content (but never narrower than it is tall).
    """
    text = StringProperty("")
    icon = StringProperty("none")
    kind = OptionProperty("normal", options=["normal", "accent", "selected", "ghost"])
    mode = StringProperty("default")
    halign = StringProperty("center")
    wide = BooleanProperty(False)
    fixed_stack = StringProperty("")  # kept for older call sites: "side" is the only layout now
    font_px = NumericProperty(0)      # 0 = derive from theme

    def __init__(self, **kw):
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(48))
        super().__init__(**kw)
        self._icon = IconView(size_hint=(None, None))
        self._label = Label(markup=False, size_hint_x=None if not self.wide else 1)
        self.add_widget(self._icon)
        self.add_widget(self._label)
        with self.canvas.before:
            self._bg_color = Color(0, 0, 0, 1)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(12)])
        self.bind(pos=self._geom, size=self._geom, text=self._style, icon=self._style, kind=self._style,
                  mode=self._style, state=self._style, disabled=self._style, halign=self._style,
                  font_px=self._style)
        self._label.bind(texture_size=self._label_size)
        if self.wide:
            self._label.bind(width=lambda *_: setattr(self._label, "text_size", (self._label.width, None)))
        self.bind(minimum_width=self._fit)
        T.bind(version=self._style)
        self._style()

    def _geom(self, *_):
        self._bg.pos, self._bg.size = self.pos, self.size

    def _label_size(self, _w, size):
        if not self.wide:
            self._label.width = size[0]
            self._label.height = size[1]

    def _fit(self, *_):
        if self.size_hint_x is None and not self.wide:
            self.width = max(self.height, self.minimum_width)

    def _style(self, *_):
        mode = "icon_text" if self.mode == "default" else self.mode
        show_icon = mode in ("icon_text", "icon") and self.icon != "none"
        show_text = mode in ("icon_text", "text") and bool(self.text)
        if mode == "icon" and self.icon == "none" and self.text:   # never an empty button
            show_text = True
        if mode == "text" and not self.text and self.icon != "none":
            show_icon = True
        h = self.height
        self.orientation = "horizontal"
        self.padding = [dp(12), dp(4)]
        self.spacing = dp(8)

        if self.kind in ("accent", "selected"):
            bg = themes.mix(T.h("accent"), T.h("accent2"), 0.35)
            fg = themes.best_on(bg)
        elif self.kind == "ghost":
            bg, fg = T.h("surface"), T.h("text")
        else:
            bg, fg = T.h("button"), T.h("button_text")
        if self.state == "down":
            bg = themes.mix(bg, T.h("accent"), 0.5)
            fg = themes.best_on(bg) if self.kind in ("normal", "ghost") else fg
        alpha = 0.4 if self.disabled else (0.75 if self.kind == "ghost" and self.state != "down" else 1.0)
        self._bg_color.rgba = themes.hex_to_rgba(bg, alpha)
        self._bg.radius = [min(dp(T.radius), h / 2)]
        rgba_fg = themes.hex_to_rgba(fg, 0.4 if self.disabled else 1.0)

        self._label.font_size = sp((self.font_px or 14) * T.font_scale)
        self._label.color = rgba_fg
        self._label.text = self.text if show_text else ""
        self._label.halign = self.halign
        self._label.valign = "middle"
        self._label.size_hint_y = None if not self.wide else 1
        if not show_text:
            self._label.size_hint_x, self._label.width = None, 0
        elif not self.wide:
            self._label.size_hint_x = None
        self._icon.name = self.icon if show_icon else "none"
        self._icon.set_color(rgba_fg)
        isz = max(dp(14), min((h - dp(8)) * 0.6, dp(30)))
        self._icon.size = (isz, isz) if show_icon else (0, 0)
        self._icon.size_hint = (None, None)
        self._icon.pos_hint = {"center_y": 0.5}
        self._label.pos_hint = {"center_y": 0.5}
        self._fit()


# ---------- surfaces (rounded fills drawn behind a widget) ----------
class _Surface:
    """Draws a rounded, softly bordered surface behind `widget`; follows pos/size/theme.
    Bound through bound *methods* so Kivy holds them weakly; the widget owns the only strong reference."""

    def __init__(self, widget, fill="surface", border=0.35, radius=None, tint=0.0, alpha=1.0):
        self._ref = weakref.ref(widget)
        self.fill, self.border, self.radius, self.tint, self.alpha = fill, border, radius, tint, alpha
        widget.bind(pos=self.draw, size=self.draw)
        T.bind(version=self.draw)
        self.draw()

    def draw(self, *_):
        w = self._ref()
        if w is None:
            return
        r = dp(T.radius) if self.radius is None else dp(self.radius)
        r = min(r, w.height / 2, w.width / 2)
        base = T.h(self.fill)
        fill = themes.mix(base, T.h("accent"), self.tint) if self.tint else base
        w.canvas.before.clear()
        with w.canvas.before:
            Color(*themes.hex_to_rgba(fill, self.alpha))
            RoundedRectangle(pos=w.pos, size=w.size, radius=[r])
            if self.border:
                Color(*themes.hex_to_rgba(themes.mix(base, T.h("accent"), self.border), 0.9))
                Line(rounded_rectangle=(w.x, w.y, w.width, w.height, r), width=dp(1))


def surface(widget, **kw):
    widget._surface = _Surface(widget, **kw)
    return widget


class _Backdrop:
    """Vertical gradient (bg -> bg2) with two soft accent glows, behind the whole screen."""

    def __init__(self, widget):
        self._ref = weakref.ref(widget)
        widget.bind(pos=self.draw, size=self.draw)
        T.bind(version=self.draw)
        self.draw()

    def draw(self, *_):
        w = self._ref()
        if w is None:
            return
        tex = gradient_texture(T.h("bg2"), T.h("bg2"), T.h("bg"), T.h("bg"))
        glow = themes.hex_to_rgba(T.h("accent"))
        glow2 = themes.hex_to_rgba(T.h("accent2"))
        w.canvas.before.clear()
        with w.canvas.before:
            Color(1, 1, 1, 1)
            Rectangle(pos=w.pos, size=w.size, texture=tex)
            steps = 16
            for i in range(steps):  # stacked translucent discs = soft radial glow, no shader needed
                f = 1.0 - i / float(steps)
                Color(glow[0], glow[1], glow[2], 0.017)
                rr = w.width * 0.75 * f
                Ellipse(pos=(w.right - rr * 0.55, w.y - rr * 0.45), size=(rr, rr))
                Color(glow2[0], glow2[1], glow2[2], 0.015)
                rr = w.width * 0.6 * f
                Ellipse(pos=(w.x - rr * 0.45, w.top - rr * 0.55), size=(rr, rr))


def backdrop(widget):
    widget._backdrop = _Backdrop(widget)
    return widget


# ---------- model for the little status dot ----------
class Status(EventDispatcher):
    """`text` is what the old status label showed; `level` drives the avatar's dot colour."""
    text = StringProperty("starting...")
    level = StringProperty("busy")

    def on_text(self, _i, value):
        v = value.lower()
        if v.startswith(("error", "blocked")):
            self.level = "error"
        elif v.startswith(("thinking", "starting")):
            self.level = "busy"
        else:
            self.level = "ok"


# ---------- styling helpers for stock widgets ----------
class _Styler:
    """Re-applies a style whenever the theme changes (weakly bound; the widget keeps the only strong ref)."""

    def __init__(self, widget, fn):
        self._ref, self._fn = weakref.ref(widget), fn

    def update(self, *_):
        w = self._ref()
        if w is not None:
            self._fn(w)


def _attach(widget, fn):
    s = _Styler(widget, fn)
    widget._styler = s
    T.bind(version=s.update)
    s.update()
    return widget


def style_label(lbl, role="text"):
    return _attach(lbl, lambda w: setattr(w, "color", T.c(role)))


def _input_style(ti):
    ti.background_normal = ti.background_active = ""
    ti.background_color = T.c("input_bg")
    ti.foreground_color = T.c("input_text")
    ti.hint_text_color = T.c("muted", 0.7)
    ti.cursor_color = T.c("accent")
    ti.selection_color = T.c("accent", 0.4)
    ti.font_size = sp(15 * T.font_scale)


def style_input(ti):
    return _attach(ti, _input_style)


def _bare_input_style(ti):
    """Text box that sits inside a pill: no fill of its own."""
    ti.background_normal = ti.background_active = ti.background_disabled_normal = ""
    ti.background_color = (0, 0, 0, 0)
    ti.foreground_color = T.c("input_text")
    ti.disabled_foreground_color = T.c("input_text", 0.5)
    ti.hint_text_color = T.c("muted", 0.8)
    ti.cursor_color = T.c("accent")
    ti.selection_color = T.c("accent", 0.4)
    ti.font_size = sp(16 * T.font_scale)


def style_bare_input(ti):
    return _attach(ti, _bare_input_style)


def _popup_style(pop):
    pop.background = ""
    pop.background_color = T.c("panel")
    pop.title_color = T.c("text")
    pop.separator_color = T.c("accent")
    pop.title_size = sp(16)


def style_popup(pop):
    return _attach(pop, _popup_style)
