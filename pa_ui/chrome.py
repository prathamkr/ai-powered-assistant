"""Builds the main Lazey screen from the saved config.

The app owns the content widgets (chat scroller, proposal card, text box); Chrome owns everything
around them (header, hero, typing bar, menu) and re-arranges them whenever the configuration changes.

    [ menu ]        wave-logo Lazey        [ sun / moon ]   (light / dark mode)
                   (Your Personal AI Assistant)
    ----------------------------------------------------
    hero (orb + "Hey") while the chat is empty, else the chat
    ----------------------------------------------------
    ( [+]  Message Lazey...            [mic] (send) )
"""
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.widget import Widget

from . import config
from .lazey_widgets import Brand, Drawer, Hero
from .widgets import RoundIcon, T, backdrop, style_bare_input, surface


def _unparent(w):
    if w.parent is not None:
        w.parent.remove_widget(w)


class Chrome:
    def __init__(self, app, cfg, store=None):
        """app must provide the handler methods named in config.BUTTONS (show_tasks, send, ...)."""
        self.app, self.cfg, self.store = app, cfg, store
        self.buttons = {}
        self.input_enabled = True
        self.listening = False   # the mic is open: its button turns into a stop button
        self.kb = 0   # on-screen keyboard height in px; the chat shrinks so the input stays above it
        self.root = BoxLayout(orientation="vertical")
        backdrop(self.root)
        self.status = self.chat = self.card = self.entry = self.hero = None
        self._drawer = None

    # -- public --
    def assemble(self, status, chat, card, entry):
        self.status, self.chat, self.card, self.entry = status, chat, card, entry
        style_bare_input(entry)
        self.hero = Hero()
        entry.bind(size=self._center_text)
        self.apply(self.cfg, save=False)
        return self.root

    def apply(self, cfg, save=True):
        """Install a new (already normalized) config: restyle and re-arrange, then persist it."""
        self.cfg = cfg
        T.apply(cfg)
        self.rebuild()
        if save and self.store is not None:
            try:
                self.store.save(cfg)
            except OSError:
                pass  # a read-only disk must not break the live preview

    def set_keyboard(self, px):
        self.kb = px
        self.root.padding = [dp(10), dp(8), dp(10), dp(10) + px]

    def set_input_enabled(self, on):
        self.input_enabled = on
        self.entry.disabled = not on
        for bid in ("send", "mic", "plus"):
            if bid in self.buttons:
                self.buttons[bid].disabled = not on

    def set_listening(self, on):
        self.listening = bool(on)
        self._mic_look()

    def _mic_look(self):
        btn = self.buttons.get("mic")
        if btn is None:
            return
        icon = next((b["icon"] for b in self.cfg["buttons"] if b["id"] == "mic"), "mic")
        btn.icon = "stop" if self.listening else icon
        btn.kind = "accent" if self.listening else "flat"

    def refresh_hero(self):
        """Show the greeting while the chat is empty; the chat takes over with the first message."""
        empty = len(self.app.log.children) == 0
        show = empty and self.cfg["layout"]["show_hero"]
        self.hero.show(show)
        self.chat.opacity = 0 if show else 1
        self.chat.disabled = show

    def fill_entry(self, text):
        self.entry.text = text
        self.entry.focus = True
        Clock.schedule_once(lambda *_: setattr(self.entry, "cursor", (len(text), 0)), 0.05)

    def open_menu(self):
        items = config.buttons_in(self.cfg, "menu")
        self._drawer = Drawer(items, side=self.cfg["layout"]["menu_side"])
        self._drawer.on_choose = lambda it: getattr(self.app, config.BUTTONS[it["id"]][2])()
        self._drawer.open()

    # -- internals --
    def _center_text(self, *_):
        e = self.entry
        pad = max(0, (e.height - e.line_height) / 2)
        if abs(e.padding[1] - pad) > 0.5:
            e.padding = [dp(6), pad, dp(6), pad]

    def _icon_button(self, b):
        handler = config.BUTTONS[b["id"]][2]
        btn = RoundIcon(diameter=max(36, self.cfg["layout"]["btn_h"] - 12), icon=b["icon"],
                        kind="accent" if b["id"] == "send" else "flat")
        btn.bind(on_release=lambda *_: getattr(self.app, handler)())
        btn.disabled = (not self.input_enabled) and b["id"] in ("send", "mic", "plus")
        btn.pos_hint = {"center_y": 0.5}
        self.buttons[b["id"]] = btn
        if b["id"] == "mic":
            self._mic_look()
        return btn

    def toggle_mode(self):
        """Sun/moon button: switch between light and dark mode (saved)."""
        self.apply(config.set_mode(self.cfg, "dark" if self.cfg.get("mode") == "light" else "light"))

    def _header(self, lay):
        menu = RoundIcon(diameter=44, icon="menu", kind="flat")
        menu.bind(on_release=lambda *_: self.open_menu())
        # top corner opposite the menu: sun = light mode is on, moon = dark mode is on (tap to switch)
        mode_btn = RoundIcon(diameter=44, icon="sun" if self.cfg.get("mode") == "light" else "moon", kind="flat")
        mode_btn.bind(on_release=lambda *_: Clock.schedule_once(lambda *_: self.toggle_mode(), 0))
        self.buttons["mode"] = mode_btn
        brand = Brand(align=lay["brand_align"], tagline=lay["show_tagline"])
        header = BoxLayout(size_hint_y=None, height=dp(76 if lay["show_tagline"] else 52))

        def side(w):
            box = BoxLayout(size_hint=(None, 1), width=dp(52))
            col = BoxLayout(orientation="vertical", size_hint=(1, 1))
            col.add_widget(w)
            col.add_widget(Widget())
            box.add_widget(col)
            w.pos_hint = {}
            return box
        # (same width as the menu button, so the title stays truly centred)
        left, right = (menu, mode_btn) if lay["menu_side"] == "left" else (mode_btn, menu)
        for w in (side(left), brand, side(right)):  # the brand centres itself or hugs the left (see Brand)
            header.add_widget(w)
        return header

    def _input_bar(self, lay):
        h = lay["btn_h"]
        bar = BoxLayout(size_hint_y=None, height=dp(h), padding=[dp(6), dp(4)], spacing=dp(4))
        surface(bar, fill="surface", border=0.3, radius=h / 2)
        for b in config.buttons_in(self.cfg, "input_left"):
            bar.add_widget(self._icon_button(b))
        self.entry.size_hint = (1, 1)
        bar.add_widget(self.entry)
        for b in config.buttons_in(self.cfg, "input_right"):
            bar.add_widget(self._icon_button(b))
        return bar

    def rebuild(self):
        lay = self.cfg["layout"]
        for w in (self.chat, self.card, self.entry, self.hero):
            _unparent(w)
        self.root.clear_widgets()
        self.buttons = {}
        self.root.spacing = dp(lay["spacing"])
        self.set_keyboard(self.kb)

        header = self._header(lay)
        bar = self._input_bar(lay)

        # body: the hero floats over the chat; the proposal card sits under both
        stage = FloatLayout()
        self.chat.size_hint = (1, 1)
        self.chat.pos_hint = {"x": 0, "y": 0}
        stage.add_widget(self.chat)
        self.hero.pos_hint = {"center_x": 0.5, "center_y": 0.52}   # greeting sits in the middle of the free space
        stage.add_widget(self.hero)
        body = BoxLayout(orientation="vertical", spacing=dp(lay["spacing"]))
        body.add_widget(stage)
        body.add_widget(self.card)

        self.root.add_widget(header)
        if lay["input_position"] == "top":
            self.root.add_widget(bar)
            self.root.add_widget(body)
        else:
            self.root.add_widget(body)
            self.root.add_widget(bar)
        Clock.schedule_once(lambda *_: (self._center_text(), self.refresh_hero()), 0)
