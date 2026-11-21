"""Calendar screen: a month grid (dots on days that have tasks) and the agenda of the selected day.

Tasks come from the assistant (`app.asst.list_tasks()`); deleting one calls `app.asst.delete_record`.
"Open phone calendar" hands over to the device's calendar app (Android only).
"""
from datetime import date, datetime, time

from kivy.graphics import Color, Ellipse, Line
from kivy.metrics import dp, sp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from . import calendar_logic as cl
from . import fonts, themes
from .widgets import RoundIcon, T, ThemedButton, gradient_texture, style_label, style_popup, surface


class DayCell(ButtonBehavior, Label):
    def __init__(self, day, has_tasks, selected, today, **kw):
        super().__init__(text=str(day.day) if day else "", font_size=sp(15), **kw)
        self.day, self.has_tasks, self.selected, self.is_today = day, has_tasks, selected, today
        self.bind(pos=self._draw, size=self._draw)
        T.bind(version=self._draw)
        self._draw()

    def _draw(self, *_):
        self.canvas.before.clear()
        if self.day is None:
            return
        d = min(self.width, self.height) - dp(6)
        cx, cy = self.center_x, self.center_y + dp(1)
        with self.canvas.before:
            if self.selected:
                tex = gradient_texture(T.h("accent2"), T.h("accent2"), T.h("accent"), T.h("accent2"))
                Color(1, 1, 1, 1)
                Ellipse(pos=(cx - d / 2, cy - d / 2), size=(d, d), texture=tex)
                self.color = themes.hex_to_rgba(themes.best_on(themes.mix(T.h("accent"), T.h("accent2"), 0.5)))
            else:
                self.color = T.c("text")
                if self.is_today:
                    Color(*T.c("accent"))
                    Line(circle=(cx, cy, d / 2), width=dp(1.4))
            if self.has_tasks:
                r = dp(2.4)
                Color(*(self.color if self.selected else T.c("accent")))
                Ellipse(pos=(cx - r, self.y + dp(4) - r), size=(2 * r, 2 * r))


class CalendarView:
    def __init__(self, app):
        self.app = app
        today = date.today()
        self.year, self.month, self.sel = today.year, today.month, today
        self.pop = None

    # ---------- data ----------
    def _tasks(self):
        try:
            return cl.tasks_by_day(self.app.asst.list_tasks() if self.app.asst else [])
        except Exception:
            return {}

    # ---------- ui ----------
    def open(self):
        if self.pop is not None:
            return
        self.outer = BoxLayout(orientation="vertical", spacing=dp(6))
        self.pop = style_popup(Popup(title="Calendar", content=self.outer, size_hint=(0.96, 0.92), auto_dismiss=False))
        self.pop.bind(on_dismiss=lambda *_: setattr(self, "pop", None))
        self.pop.open()
        self.render()

    def shift(self, delta):
        self.year, self.month = cl.shift_month(self.year, self.month, delta)
        self.render()

    def select(self, d):
        self.sel = d
        self.render()

    def render(self):
        tasks = self._tasks()
        o = self.outer
        o.clear_widgets()
        head = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        prev = RoundIcon(diameter=40, icon="left", kind="soft")
        nxt = RoundIcon(diameter=40, icon="right", kind="soft")
        prev.bind(on_release=lambda *_: self.shift(-1))
        nxt.bind(on_release=lambda *_: self.shift(1))
        title = Label(text=cl.month_title(self.year, self.month), font_name=fonts.HEADING, font_size=sp(18))
        style_label(title)
        for w in (prev, title, nxt):
            head.add_widget(w)
        o.add_widget(head)

        wk = GridLayout(cols=7, size_hint_y=None, height=dp(22))
        for ch in cl.WEEKDAYS:
            wk.add_widget(style_label(Label(text=ch, font_size=sp(12)), "muted"))
        o.add_widget(wk)

        weeks = cl.month_weeks(self.year, self.month)
        grid = GridLayout(cols=7, size_hint_y=None, height=dp(40) * len(weeks))
        today = date.today()
        for week in weeks:
            for n in week:
                if n == 0:
                    grid.add_widget(Widget())
                    continue
                d = date(self.year, self.month, n)
                cell = DayCell(d, d in tasks, d == self.sel, d == today)
                cell.bind(on_release=lambda _c, dd=d: self.select(dd))
                grid.add_widget(cell)
        o.add_widget(grid)

        o.add_widget(style_label(Label(text=cl.day_title(self.sel), font_name=fonts.HEADING, size_hint_y=None,
                                       height=dp(30), halign="left", font_size=sp(15)), "accent"))
        o.children[0].bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        agenda = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        agenda.bind(minimum_height=agenda.setter("height"))
        items = tasks.get(self.sel, [])
        if not items:
            agenda.add_widget(style_label(Label(text="Nothing planned for this day.", font_name=fonts.SUB, size_hint_y=None,
                                                height=dp(36), font_size=sp(14)), "muted"))
        for t in items:
            agenda.add_widget(self._row(t))
        sv = ScrollView()
        sv.add_widget(agenda)
        o.add_widget(sv)

        foot = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        phone = ThemedButton(text="Open phone calendar", icon="calendar", size_hint_x=1, height=dp(46), font_px=13)
        phone.bind(on_release=lambda *_: self.open_phone())
        done = ThemedButton(text="Done", mode="text", kind="accent", size_hint_x=0.5, height=dp(46))
        done.bind(on_release=lambda *_: self.pop.dismiss())
        foot.add_widget(phone)
        foot.add_widget(done)
        o.add_widget(foot)
        self.note = None

    def _row(self, t):
        row = BoxLayout(size_hint_y=None, height=dp(58), spacing=dp(6), padding=[dp(12), dp(4), dp(6), dp(4)])
        surface(row, fill="surface", border=0.2, radius=16)
        state = "calendar screen opened" if t.get("calendar") == "handed_off" else str(t.get("calendar", ""))
        when = cl.parse_time(t.get("start_iso"))
        col = BoxLayout(orientation="vertical")
        a = style_label(Label(text=str(t.get("title", "")), halign="left", font_name=fonts.HEADING, font_size=sp(14),
                              shorten=True, shorten_from="right"))
        b = style_label(Label(text=(when + "  " if when else "") + state, halign="left", font_name=fonts.SUB,
                              font_size=sp(12)), "muted")
        for lb in (a, b):
            lb.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
            col.add_widget(lb)
        row.add_widget(col)
        d = RoundIcon(diameter=40, icon="trash", kind="flat")
        d.pos_hint = {"center_y": 0.5}
        d.bind(on_release=lambda *_: self._delete(t))
        row.add_widget(d)
        return row

    def _delete(self, t):
        try:
            self.app.asst.delete_record(t["id"])
        finally:
            self.render()

    def open_phone(self):
        """Android: open the calendar app on the selected day. Elsewhere: say why nothing happened."""
        try:
            from android import mActivity  # type: ignore
            from jnius import autoclass  # type: ignore
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            millis = int(datetime.combine(self.sel, time(9, 0)).timestamp() * 1000)
            intent = Intent(Intent.ACTION_VIEW, Uri.parse("content://com.android.calendar/time/%d" % millis))
            mActivity.startActivity(intent)
        except Exception:
            self.app.say("The phone calendar can only be opened on an Android device.", "sys")
            if self.pop:
                self.pop.dismiss()
