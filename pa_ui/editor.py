"""The "Theme" screen: pick a theme and background, edit colours, change the layout, move buttons and
swap icons.

Every change is applied to the real screen immediately (live preview) and saved. Nothing here can
lock you out: the Theme entry can never be hidden, and "Reset all" restores the defaults.
"""
from kivy.clock import Clock
from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from . import config, fonts, themes
from .iconset import CHOOSABLE
from .widgets import T, ThemedButton, gradient_texture, style_input, style_label, style_popup, surface

TABS = (("themes", "Themes"), ("colors", "Colours"), ("layout", "Layout"), ("buttons", "Buttons"))


def _flow(cols, **kw):
    g = GridLayout(cols=cols, size_hint_y=None, spacing=dp(6), **kw)
    g.bind(minimum_height=g.setter("height"))
    return g


def _col(**kw):
    b = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8), **kw)
    b.bind(minimum_height=b.setter("height"))
    return b


def text_label(text, role="text", size=14, bold=False, halign="left", height=None):
    face = fonts.HEADING if bold else (fonts.SUB if role == "muted" else fonts.UI)
    lb = Label(text=text, size_hint_y=None, halign=halign, valign="middle", font_name=face, font_size=sp(size))
    lb.bind(width=lambda *_: setattr(lb, "text_size", (lb.width, None)))
    if height:
        lb.height = dp(height)
    else:
        lb.bind(texture_size=lambda *_: setattr(lb, "height", lb.texture_size[1] + dp(6)))
    return style_label(lb, role)


class ThemeCard(ButtonBehavior, BoxLayout):
    """Mini preview of a theme or backdrop: gradient background, a button, the accent and two text lines."""

    def __init__(self, name, colors, selected, height=86, **kw):
        super().__init__(orientation="vertical", size_hint_y=None, height=dp(height), padding=dp(6), **kw)
        self.colors, self.selected = colors, selected
        self.caption = Label(text=name, size_hint_y=None, height=dp(22), font_size=sp(12.5), shorten=True,
                             shorten_from="right", color=themes.hex_to_rgba(colors["text"]))
        self.caption.bind(width=lambda *_: setattr(self.caption, "text_size", (self.caption.width, None)))
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
        self.tab = "themes"
        self.pop = None
        self.body = None
        self.tab_btns = {}
        self._busy = False
        self._pending = None
        self._reset_armed = False

    # ---------- open / chrome of the dialog ----------
    def open(self):
        if self.pop is not None:
            return
        outer = BoxLayout(orientation="vertical", spacing=dp(8))
        tabs = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(4))
        for tid, name in TABS:
            b = ThemedButton(text=name, mode="text", height=dp(42), size_hint_x=1, font_px=13)
            b.bind(on_release=lambda _b, t=tid: self.show(t))
            self.tab_btns[tid] = b
            tabs.add_widget(b)
        self.scroll = ScrollView(bar_width=dp(4), scroll_type=["bars", "content"])
        self.body = _col(padding=[0, 0, dp(6), 0])
        self.scroll.add_widget(self.body)
        foot = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        self.reset_btn = ThemedButton(text="Reset all", mode="text", height=dp(46), size_hint_x=0.4, font_px=14)
        self.reset_btn.bind(on_release=lambda *_: self.reset_all())
        done = ThemedButton(text="Done", mode="text", height=dp(46), size_hint_x=0.6, kind="accent", font_px=14)
        done.bind(on_release=lambda *_: self.pop.dismiss())
        foot.add_widget(self.reset_btn)
        foot.add_widget(done)
        for w in (tabs, self.scroll, foot):
            outer.add_widget(w)
        self.pop = style_popup(Popup(title="Theme", content=outer, size_hint=(0.96, 0.9), auto_dismiss=False))
        self.pop.bind(on_dismiss=lambda *_: setattr(self, "pop", None))
        self.pop.open()
        self.show(self.tab)

    @property
    def cfg(self):
        return self.chrome.cfg

    def commit(self, new_cfg, refresh=True):
        """Apply a new config to the live screen and save it."""
        self.chrome.apply(new_cfg)
        if refresh:
            self.show(self.tab)

    def show(self, tab):
        self.tab = tab
        self._reset_armed = False
        self.reset_btn.text = "Reset all"
        for tid, b in self.tab_btns.items():
            b.kind = "selected" if tid == tab else "normal"
        self.body.clear_widgets()
        self._busy = True
        try:
            getattr(self, "_tab_" + tab)()
        finally:
            self._busy = False

    def reset_all(self):
        if not self._reset_armed:
            self._reset_armed = True
            self.reset_btn.text = "Tap again to confirm"
            return
        self._reset_armed = False
        self.commit(config.default_config())

    # ---------- small widgets ----------
    def chips(self, options, current, on_pick, cols=2, h=40):
        """options: list of (value, label). Highlights `current`."""
        g = _flow(cols)
        for value, label in options:
            b = ThemedButton(text=label, mode="text", height=dp(h), size_hint_x=1, font_px=13,
                             kind="selected" if value == current else "normal")
            b.bind(on_release=lambda _b, v=value: on_pick(v))
            g.add_widget(b)
        rows = (len(options) + cols - 1) // cols
        g.height = rows * dp(h) + (rows - 1) * dp(6)
        return g

    def slider(self, title, key, lo, hi, step, fmt):
        value = self.cfg["layout"][key]
        head = text_label("%s: %s" % (title, fmt(value)), size=13)
        s = Slider(min=lo, max=hi, value=value, step=step, size_hint_y=None, height=dp(34), cursor_size=(dp(24), dp(24)),
                   value_track=True, value_track_color=T.c("accent"))
        s.bind(value=lambda _s, v: self._on_slider(key, v, head, title, fmt))
        self.body.add_widget(head)
        self.body.add_widget(s)

    def _on_slider(self, key, v, head, title, fmt):
        head.text = "%s: %s" % (title, fmt(v))
        if self._busy:
            return
        if self._pending is not None:
            self._pending.cancel()
        # wait for the finger to pause so the screen is not rebuilt on every pixel of the drag
        self._pending = Clock.schedule_once(
            lambda *_: self.commit(config.set_layout(self.cfg, **{key: v}), refresh=False), 0.12)

    # ---------- tab: themes ----------
    def _tab_themes(self):
        cfg = self.cfg
        saved = cfg["saved_themes"]
        modified = bool(cfg["custom"])
        cur = themes.theme_name(cfg["theme"], saved)
        self.body.add_widget(text_label("Theme: %s%s" % (cur, " (with your colour changes)" if modified else ""),
                                        bold=True, size=14))
        grid = _flow(2)
        n = 0
        for tid in themes.theme_ids(saved):
            colors = themes.base_colors(tid, saved)
            card = ThemeCard(themes.theme_name(tid, saved), colors, tid == cfg["theme"] and not modified)
            card.bind(on_release=lambda _c, t=tid: self.commit(config.set_theme(self.cfg, t)))
            grid.add_widget(card)
            n += 1
        grid.height = ((n + 1) // 2) * dp(86) + (((n + 1) // 2) - 1) * dp(6)
        self.body.add_widget(grid)

        # backdrops: nine dark backgrounds that work under any dark theme
        base = themes.base_colors(cfg["theme"], saved)
        self.body.add_widget(text_label("Background colour", bold=True, size=14))
        if themes.backdrop_applies(base):
            opts = [(themes.BACKGROUND_DEFAULT, "Theme default")] + [(k, v[0]) for k, v in themes.BACKGROUNDS.items()]
            bg_grid = _flow(3)
            for bid, name in opts:
                colors = dict(base)
                if bid in themes.BACKGROUNDS:
                    colors.update(themes.BACKGROUNDS[bid][1])
                card = ThemeCard(name, colors, bid == cfg["background"], height=74)
                card.bind(on_release=lambda _c, b=bid: self.commit(config.set_background(self.cfg, b)))
                bg_grid.add_widget(card)
            rows = (len(opts) + 2) // 3
            bg_grid.height = rows * dp(74) + (rows - 1) * dp(6)
            self.body.add_widget(bg_grid)
        else:
            self.body.add_widget(text_label("This theme keeps its own background so it stays readable.", "muted", 12))

        self.body.add_widget(text_label("Save the current colours as your own theme", bold=True, size=14))
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        name = style_input(TextInput(hint_text="Theme name", multiline=False, write_tab=False, size_hint_x=0.62,
                                     padding=[dp(10), dp(13)]))
        save = ThemedButton(text="Save", mode="text", height=dp(46), size_hint_x=0.38, kind="accent")
        status = text_label("", role="sys", size=12)

        def do_save(*_):
            try:
                new = config.save_current_theme(self.cfg, name.text)
            except ValueError as e:
                status.text = str(e)
                return
            self.commit(new)
        save.bind(on_release=do_save)
        name.bind(on_text_validate=do_save)
        row.add_widget(name)
        row.add_widget(save)
        self.body.add_widget(row)
        self.body.add_widget(status)
        for sname in saved:
            r = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
            r.add_widget(text_label("Saved: " + sname, size=13, height=40))
            d = ThemedButton(text="Delete", icon="trash", mode="icon", height=dp(40), size_hint_x=None, width=dp(48))
            d.bind(on_release=lambda _b, n=sname: self.commit(config.delete_saved_theme(self.cfg, n)))
            r.add_widget(d)
            self.body.add_widget(r)

    # ---------- tab: colours ----------
    def _tab_colors(self):
        colors = config.current_colors(self.cfg)
        problems = themes.readability_problems(colors)
        if problems:
            names = ", ".join("%s on %s" % (themes.ROLES[f][0].lower(), themes.ROLES[b][0].lower())
                              for f, b, _r, _n in problems[:3])
            self.body.add_widget(text_label("Hard to read: %s. Try a lighter or darker colour." % names,
                                            role="sys", size=13))
        else:
            self.body.add_widget(text_label("Every text colour has good contrast on its background.", size=13))
        for role, (label, hint) in themes.ROLES.items():
            self.body.add_widget(self._color_row(role, label, hint, colors[role]))
        b = ThemedButton(text="Undo colour changes", mode="text", height=dp(44), size_hint_x=1, font_px=14)
        b.disabled = not self.cfg["custom"]
        b.bind(on_release=lambda *_: self.commit(config.clear_colors(self.cfg)))
        self.body.add_widget(b)

    def _color_row(self, role, label, hint, hexv):
        row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(6))
        sw = Widget(size_hint=(None, 1), width=dp(40))

        def paint(*_):
            sw.canvas.clear()
            with sw.canvas:
                Color(*themes.hex_to_rgba(hexv))
                RoundedRectangle(pos=(sw.x, sw.center_y - dp(18)), size=(dp(40), dp(36)), radius=[dp(10)])
                Color(0.5, 0.5, 0.6, 0.8)
                Line(rounded_rectangle=(sw.x, sw.center_y - dp(18), dp(40), dp(36), dp(10)), width=dp(1))
        sw.bind(pos=paint, size=paint)
        paint()
        names = BoxLayout(orientation="vertical")
        names.add_widget(text_label(label, bold=True, size=13, height=20))
        names.add_widget(text_label(hint, "muted", size=11, height=18))
        ti = style_input(TextInput(text=hexv, multiline=False, write_tab=False, size_hint=(None, None), width=dp(92),
                                   height=dp(40), padding=[dp(8), dp(10)], input_filter=lambda s, u: s if s in
                                   "#0123456789abcdefABCDEF" else ""))
        ti.pos_hint = {"center_y": 0.5}

        def commit_hex(*_):
            if self._busy:
                return
            try:
                new = themes.norm_hex(ti.text)
            except ValueError:
                ti.text = hexv  # not a colour: put the old one back
                return
            if new != hexv:
                self.commit(config.set_color(self.cfg, role, new))
        ti.bind(on_text_validate=commit_hex, focus=lambda _t, f: (not f) and commit_hex())
        wheel = ThemedButton(text="Pick", icon="palette", mode="icon", height=dp(40), size_hint=(None, None), width=dp(44))
        wheel.pos_hint = {"center_y": 0.5}
        wheel.bind(on_release=lambda *_: self.pick_color(role, label, hexv))
        for w in (sw, names, ti, wheel):
            row.add_widget(w)
        return row

    def pick_color(self, role, label, hexv):
        try:
            from kivy.uix.colorpicker import ColorPicker
        except Exception:  # the hex box still works without the wheel
            return
        cp = ColorPicker(color=themes.hex_to_rgba(hexv))
        outer = BoxLayout(orientation="vertical", spacing=dp(6))
        outer.add_widget(cp)
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        cancel = ThemedButton(text="Cancel", mode="text", height=dp(46), size_hint_x=0.4)
        ok = ThemedButton(text="Use this colour", mode="text", height=dp(46), size_hint_x=0.6, kind="accent")
        row.add_widget(cancel)
        row.add_widget(ok)
        outer.add_widget(row)
        p = style_popup(Popup(title=label, content=outer, size_hint=(0.96, 0.9), auto_dismiss=False))
        cancel.bind(on_release=lambda *_: p.dismiss())

        def use(*_):
            p.dismiss()
            self.commit(config.set_color(self.cfg, role, themes.rgba_to_hex(cp.color)))
        ok.bind(on_release=use)
        p.open()

    # ---------- tab: layout ----------
    def _tab_layout(self):
        lay = self.cfg["layout"]
        L = lambda **kw: self.commit(config.set_layout(self.cfg, **kw))  # noqa: E731
        self.body.add_widget(text_label("Quick layouts", bold=True))
        self.body.add_widget(self.chips([(k, v[0]) for k, v in config.PRESETS.items()], None,
                                        lambda k: self.commit(config.apply_preset(self.cfg, k)), cols=2))
        self.body.add_widget(text_label("Title", bold=True))
        self.body.add_widget(self.chips([("center", "Centred"), ("left", "Left")], lay["brand_align"],
                                        lambda v: L(brand_align=v), cols=2))
        self.body.add_widget(text_label("Tagline under the title", bold=True))
        self.body.add_widget(self.chips([(True, "Show"), (False, "Hide")], lay["show_tagline"],
                                        lambda v: L(show_tagline=v), cols=2))
        self.body.add_widget(text_label("Menu button", bold=True))
        self.body.add_widget(self.chips([("left", "Left corner"), ("right", "Right corner")], lay["menu_side"],
                                        lambda v: L(menu_side=v), cols=2))
        self.body.add_widget(text_label("Typing bar", bold=True))
        self.body.add_widget(self.chips([("bottom", "At the bottom"), ("top", "Under the title")], lay["input_position"],
                                        lambda v: L(input_position=v), cols=2))
        self.body.add_widget(text_label("Greeting with the glowing orb", bold=True))
        self.body.add_widget(self.chips([(True, "Show"), (False, "Hide")], lay["show_hero"],
                                        lambda v: L(show_hero=v), cols=2))
        self.body.add_widget(text_label("Messages", bold=True))
        self.body.add_widget(self.chips([("bubbles", "Bubbles"), ("plain", "Plain text")], lay["bubbles"],
                                        lambda v: L(bubbles=v), cols=2))
        self.slider("Typing bar height", "btn_h", *config.NUM_LIMITS["btn_h"], 2, lambda v: "%d" % v)
        self.slider("Corner roundness", "radius", *config.NUM_LIMITS["radius"], 1, lambda v: "%d" % v)
        self.slider("Text size", "font_scale", *config.NUM_LIMITS["font_scale"], 0.05, lambda v: "%d%%" % round(v * 100))
        self.slider("Spacing", "spacing", *config.NUM_LIMITS["spacing"], 1, lambda v: "%d" % v)

    # ---------- tab: buttons ----------
    def _tab_buttons(self):
        self.body.add_widget(text_label(
            "Each button can live in the Menu (the corner button), in the typing bar before or after the text box, "
            "or be hidden. Change its icon and name, or move it earlier or later. The Theme entry can't be hidden, "
            "so you can always get back here.", "muted", 12))
        for b in self.cfg["buttons"]:
            self.body.add_widget(self._button_card(b))
        r = ThemedButton(text="Reset buttons", mode="text", height=dp(44), size_hint_x=1, font_px=14)
        r.bind(on_release=lambda *_: self.commit(config.reset_buttons(self.cfg)))
        self.body.add_widget(r)

    def _button_card(self, b):
        bid = b["id"]
        card = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(104), spacing=dp(4), padding=dp(6))
        surface(card, fill="surface", border=0.15, radius=16)
        top = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        ic = ThemedButton(text="", icon=b["icon"], mode="icon", height=dp(44), size_hint=(None, None), width=dp(48))
        ic.bind(on_release=lambda *_: self.pick_icon(bid))
        name = style_input(TextInput(text=b["label"], multiline=False, write_tab=False, size_hint=(1, None), height=dp(44),
                                     padding=[dp(10), dp(13)]))

        def commit_name(*_):
            if self._busy:
                return
            new = name.text.strip()[:config.LABEL_MAX] or config.BUTTONS[bid][0]
            if new != b["label"]:
                self.commit(config.set_button(self.cfg, bid, label=new))
        name.bind(on_text_validate=commit_name, focus=lambda _t, f: (not f) and commit_name())
        region = ThemedButton(text=config.REGION_NAMES[b["region"]], mode="text", height=dp(44), size_hint=(None, None),
                              width=dp(104), font_px=12)
        region.bind(on_release=lambda *_: self.commit(config.cycle_region(self.cfg, bid)))
        for w in (ic, name, region):
            top.add_widget(w)
        bottom = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
        left = ThemedButton(text="Earlier", icon="left", height=dp(38), size_hint_x=1, font_px=12)
        right = ThemedButton(text="Later", icon="right", height=dp(38), size_hint_x=1, font_px=12)
        left.bind(on_release=lambda *_: self.commit(config.move_button(self.cfg, bid, -1)))
        right.bind(on_release=lambda *_: self.commit(config.move_button(self.cfg, bid, +1)))
        if b["region"] == "hidden":
            left.disabled = right.disabled = True
        for w in (left, right):
            bottom.add_widget(w)
        card.add_widget(top)
        card.add_widget(bottom)
        return card

    def pick_icon(self, bid):
        grid = GridLayout(cols=4, size_hint_y=None, spacing=dp(8), padding=dp(4))
        grid.bind(minimum_height=grid.setter("height"))
        sv = ScrollView()
        sv.add_widget(grid)
        outer = BoxLayout(orientation="vertical", spacing=dp(6))
        outer.add_widget(sv)
        close = ThemedButton(text="Cancel", mode="text", height=dp(46), size_hint_x=1)
        outer.add_widget(close)
        p = style_popup(Popup(title="Choose an icon", content=outer, size_hint=(0.92, 0.7), auto_dismiss=False))
        cur = next(x for x in self.cfg["buttons"] if x["id"] == bid)["icon"]

        def choose(name):
            p.dismiss()
            self.commit(config.set_button(self.cfg, bid, icon=name))
        for name in CHOOSABLE:
            b = ThemedButton(text="", icon=name, mode="icon", height=dp(60), size_hint_x=1,
                             kind="selected" if name == cur else "normal")
            if name == "none":
                b.text, b.mode = "none", "text"
            b.bind(on_release=lambda _b, n=name: choose(n))
            grid.add_widget(b)
        close.bind(on_release=lambda *_: p.dismiss())
        p.open()
