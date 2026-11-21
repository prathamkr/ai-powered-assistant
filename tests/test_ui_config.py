"""Tests for pa_ui (pure parts: themes, icons, config, calendar, fonts). No Kivy or window needed."""
import json
import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pa_ui import calendar_logic as cl  # noqa: E402
from pa_ui import config as C  # noqa: E402
from pa_ui import iconset, themes  # noqa: E402


def ids(cfg, region):
    return [b["id"] for b in C.buttons_in(cfg, region)]


class ThemeTests(unittest.TestCase):
    def test_every_theme_defines_every_role_with_valid_hex(self):
        for tid, (_, cols) in themes.BUILTIN.items():
            self.assertEqual(set(cols), set(themes.ROLES), tid)
            for v in cols.values():
                self.assertTrue(themes.valid_hex(v), (tid, v))

    def test_every_theme_is_readable(self):
        for tid in themes.BUILTIN:
            self.assertEqual(themes.readability_problems(themes.resolve(tid)), [], tid)

    def test_there_are_several_themes_including_a_light_and_a_high_contrast_one(self):
        self.assertGreaterEqual(len(themes.BUILTIN), 6)
        for tid in ("violet", "daylight", "contrast"):
            self.assertIn(tid, themes.BUILTIN)

    def test_contrast_ratio_extremes(self):
        self.assertAlmostEqual(themes.contrast_ratio("#000000", "#ffffff"), 21.0, places=1)
        self.assertAlmostEqual(themes.contrast_ratio("#777777", "#777777"), 1.0, places=3)

    def test_hex_helpers(self):
        self.assertEqual(themes.norm_hex("AABBCC"), "#aabbcc")
        self.assertEqual(themes.rgba_to_hex(themes.hex_to_rgba("#102030")), "#102030")
        for bad in ("#12345", "#gggggg", "", None, 5):
            self.assertFalse(themes.valid_hex(bad))
        with self.assertRaises(ValueError):
            themes.norm_hex("nope")

    def test_best_on_picks_readable_text(self):
        self.assertEqual(themes.best_on("#ffff00"), "#000000")
        self.assertEqual(themes.best_on("#101010"), "#ffffff")

    def test_unknown_theme_falls_back_to_default_and_copies_are_independent(self):
        self.assertEqual(themes.resolve("nope"), themes.resolve(themes.DEFAULT_THEME))
        themes.resolve("violet")["bg"] = "#ffffff"   # editing a returned dict must not change the theme
        self.assertNotEqual(themes.resolve("violet")["bg"], "#ffffff")


class IconTests(unittest.TestCase):
    FONT = os.path.join(os.path.dirname(__file__), "..", "pa_ui", "fonts", "MaterialIconsRound-Regular.otf")

    def test_every_icon_is_one_private_use_glyph_or_empty(self):
        for name, g in iconset.GLYPHS.items():
            if name == "none":
                self.assertEqual(g, "")
            else:
                self.assertEqual(len(g), 1, name)
                self.assertTrue(0xE000 <= ord(g) <= 0xF8FF, (name, hex(ord(g))))

    def test_every_button_icon_has_a_glyph(self):
        for bid, (_, icon, _) in C.BUTTONS.items():
            self.assertTrue(iconset.glyph(icon), bid)

    def test_icons_used_by_the_screens_exist(self):
        for name in ("menu", "wave", "calendar", "trash", "left", "right", "check", "close", "stop", "mic", "send"):
            self.assertTrue(iconset.glyph(name), name)
        self.assertEqual(iconset.glyph("not-an-icon"), "")

    def test_all_glyphs_exist_in_the_bundled_font(self):
        try:
            from fontTools.ttLib import TTFont
        except ImportError:
            self.skipTest("fontTools not installed")
        cmap = TTFont(self.FONT).getBestCmap()
        for name, g in iconset.GLYPHS.items():
            if g:
                self.assertIn(ord(g), cmap, name)


class ConfigTests(unittest.TestCase):
    def test_default_layout_matches_the_design(self):
        cfg = C.default_config()
        self.assertEqual(ids(cfg, "menu"), ["theme", "calendar", "prefs", "voice"])
        self.assertEqual(ids(cfg, "input_left"), ["plus"])
        self.assertEqual(ids(cfg, "input_right"), ["mic", "send"])
        self.assertEqual(C.normalize(cfg), cfg)  # already valid, normalize is a no-op

    def test_menu_has_theme_and_calendar(self):
        menu = ids(C.default_config(), "menu")
        self.assertIn("theme", menu)
        self.assertIn("calendar", menu)

    def test_app_is_called_lazey(self):
        self.assertEqual(C.APP_NAME, "Lazey")
        self.assertNotIn("pacsit", repr(C.default_config()).lower())

    def test_normalize_survives_garbage(self):
        for raw in (None, 5, "x", [], {"theme": 9}, {"theme": []}, {"theme": {}}, {"layout": 3, "buttons": "x"}):
            self.assertEqual(C.normalize(raw), C.default_config())

    def test_set_theme_changes_only_the_theme(self):
        cfg = C.set_theme(C.default_config(), "ocean")
        self.assertEqual(cfg["theme"], "ocean")
        self.assertEqual(cfg["layout"], C.default_config()["layout"])
        self.assertEqual(cfg["buttons"], C.default_config()["buttons"])
        self.assertEqual(C.set_theme(cfg, "not-a-theme")["theme"], themes.DEFAULT_THEME)

    def test_layout_and_buttons_cannot_be_changed_from_a_file(self):
        cfg = C.normalize({"theme": "rose", "layout": {"show_tagline": False, "menu_side": "right"},
                           "buttons": [{"id": "mic", "region": "menu", "icon": "heart", "label": "Talk"}],
                           "background": "wine", "custom": {"accent": "#ff0000"}, "saved_themes": {"x": {}}})
        self.assertEqual(cfg["theme"], "rose")
        self.assertEqual(cfg, C.set_theme(C.default_config(), "rose"))
        self.assertNotIn("custom", cfg)

    def test_store_saves_only_the_theme_and_roundtrips(self):
        with tempfile.TemporaryDirectory() as d:
            store = C.ConfigStore(d)
            self.assertEqual(store.load(), C.default_config())  # no file yet
            cfg = C.set_theme(C.default_config(), "sunset" if "sunset" in themes.BUILTIN else "emerald")
            store.save(cfg)
            self.assertEqual(store.load(), cfg)
            with open(store.path, encoding="utf-8") as fh:
                self.assertEqual(sorted(json.load(fh)), ["theme", "version"])
            self.assertFalse(os.path.exists(store.path + ".tmp"))

    def test_store_handles_corrupt_and_old_files(self):
        with tempfile.TemporaryDirectory() as d:
            store = C.ConfigStore(d)
            with open(store.path, "w") as fh:
                fh.write("{ not json")
            self.assertEqual(store.load(), C.default_config())
            self.assertTrue(os.path.exists(store.path + ".bad"))  # kept for inspection, not deleted
            with open(store.path, "w") as fh:  # a file from an earlier version with all the old options
                json.dump({"theme": "forest", "background": "teal", "custom": {"bg": "#111111"},
                           "layout": {"btn_h": 60}, "buttons": [{"id": "send", "region": "menu"}]}, fh)
            self.assertEqual(store.load(), C.default_config())  # "forest" no longer exists -> default theme
            with open(store.path, "w") as fh:
                json.dump({"theme": "ocean", "background": "teal", "layout": {"btn_h": 60}}, fh)
            self.assertEqual(store.load(), C.set_theme(C.default_config(), "ocean"))


class FontTests(unittest.TestCase):
    """The typefaces ship inside the app (buildozer must include ttf/otf + licence files)."""
    DIR = os.path.join(os.path.dirname(__file__), "..", "pa_ui", "fonts")

    def test_font_files_are_real_font_files(self):
        for name in ("Poppins-SemiBold.ttf", "Poppins-Medium.ttf", "Poppins-Regular.ttf", "Inter-Regular.ttf"):
            with open(os.path.join(self.DIR, name), "rb") as fh:
                self.assertEqual(fh.read(4), b"\x00\x01\x00\x00", name)
        with open(os.path.join(self.DIR, "MaterialIconsRound-Regular.otf"), "rb") as fh:
            self.assertEqual(fh.read(4), b"OTTO")  # OpenType (CFF) icon font

    def test_licences_travel_with_the_fonts(self):
        for name in ("OFL-Poppins.txt", "OFL-Inter.txt"):
            with open(os.path.join(self.DIR, name), encoding="utf-8") as fh:
                self.assertIn("SIL OPEN FONT LICENSE", fh.read().upper(), name)
        with open(os.path.join(self.DIR, "LICENSE-MaterialIcons-Apache2.txt"), encoding="utf-8") as fh:
            self.assertIn("APACHE LICENSE", fh.read().upper())

    def test_build_config_packages_fonts_and_uses_the_new_name(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "buildozer.spec"), encoding="utf-8") as fh:
            spec = fh.read()
        self.assertRegex(spec, r"source\.include_exts = .*\bttf\b")
        self.assertRegex(spec, r"source\.include_exts = .*\botf\b")
        self.assertIn("title = Lazey", spec)
        self.assertIn("package.name = lazey", spec)


class CalendarTests(unittest.TestCase):
    def test_parse_day_and_time(self):
        self.assertEqual(cl.parse_day("2026-11-20T09:00:00+05:30"), date(2026, 11, 20))
        self.assertEqual(cl.parse_day("2026-11-20"), date(2026, 11, 20))
        for bad in (None, "", "soon", 5):
            self.assertIsNone(cl.parse_day(bad))
        self.assertEqual(cl.parse_time("2026-11-20T09:05:00+05:30"), "09:05")
        self.assertEqual(cl.parse_time("nonsense"), "")

    def test_month_grid_is_sunday_first_and_complete(self):
        weeks = cl.month_weeks(2026, 11)  # 1 Nov 2026 is a Sunday
        self.assertEqual(weeks[0][0], 1)
        self.assertEqual(sorted(d for w in weeks for d in w if d), list(range(1, 31)))
        self.assertTrue(all(len(w) == 7 for w in weeks))
        self.assertEqual(cl.month_weeks(2026, 2)[0], [1, 2, 3, 4, 5, 6, 7])  # 1 Feb 2026 is a Sunday too

    def test_shift_month_wraps_years(self):
        self.assertEqual(cl.shift_month(2026, 12, 1), (2027, 1))
        self.assertEqual(cl.shift_month(2026, 1, -1), (2025, 12))
        self.assertEqual(cl.shift_month(2026, 5, 0), (2026, 5))
        self.assertEqual(cl.shift_month(2026, 5, 14), (2027, 7))

    def test_tasks_grouped_by_day_sorted_and_bad_dates_skipped(self):
        tasks = [{"id": 1, "start_iso": "2026-11-20T18:00:00"}, {"id": 2, "start_iso": "2026-11-20T09:00:00"},
                 {"id": 3, "start_iso": "2026-11-21T08:00:00"}, {"id": 4, "start_iso": "garbage"}, {"id": 5}]
        by = cl.tasks_by_day(tasks)
        self.assertEqual([t["id"] for t in by[date(2026, 11, 20)]], [2, 1])
        self.assertEqual(sorted(by), [date(2026, 11, 20), date(2026, 11, 21)])
        self.assertEqual(cl.tasks_by_day(None), {})

    def test_titles(self):
        self.assertEqual(cl.month_title(2026, 11), "November 2026")
        self.assertEqual(cl.day_title(date(2026, 11, 21), today=date(2026, 11, 21)), "Today, 21 November")
        self.assertEqual(cl.day_title(date(2026, 11, 22), today=date(2026, 11, 21)), "Sunday, 22 November")


if __name__ == "__main__":
    unittest.main()
