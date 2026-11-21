"""Tests for pa_ui (pure parts: themes, icons, config, calendar). No Kivy or window needed."""
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


def btn(cfg, bid):
    return next(b for b in cfg["buttons"] if b["id"] == bid)


def ids(cfg, region):
    return [b["id"] for b in C.buttons_in(cfg, region)]


class ThemeTests(unittest.TestCase):
    def test_every_theme_defines_every_role_with_valid_hex(self):
        for tid, (_, cols) in themes.BUILTIN.items():
            self.assertEqual(set(cols), set(themes.ROLES), tid)
            for v in cols.values():
                self.assertTrue(themes.valid_hex(v), (tid, v))

    def test_every_theme_on_every_background_is_readable(self):
        for tid in themes.BUILTIN:
            for bg in [themes.BACKGROUND_DEFAULT] + list(themes.BACKGROUNDS):
                colors = themes.resolve(tid, {}, {}, bg)
                self.assertEqual(themes.readability_problems(colors), [], (tid, bg))

    def test_there_are_at_least_five_background_options(self):
        self.assertGreaterEqual(len(themes.BACKGROUNDS), 5)
        for _, cols in themes.BACKGROUNDS.values():
            self.assertEqual(set(cols), set(themes.BG_ROLES))
            for v in cols.values():
                self.assertTrue(themes.valid_hex(v))

    def test_backgrounds_change_only_background_roles_on_dark_themes(self):
        plain = themes.resolve("violet", {}, {}, "theme")
        wine = themes.resolve("violet", {}, {}, "wine")
        for role in themes.ROLES:
            if role in themes.BG_ROLES:
                self.assertNotEqual(plain[role], wine[role], role)
            else:
                self.assertEqual(plain[role], wine[role], role)

    def test_backgrounds_are_ignored_where_they_would_hurt_readability(self):
        for tid in ("daylight", "contrast"):
            self.assertEqual(themes.resolve(tid, {}, {}, "wine"), themes.resolve(tid, {}, {}, "theme"), tid)
            self.assertFalse(themes.backdrop_applies(themes.base_colors(tid, {})))
        self.assertTrue(themes.backdrop_applies(themes.base_colors("violet", {})))

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

    def test_resolve_applies_overrides_last_and_ignores_garbage(self):
        c = themes.resolve("ocean", {"accent": "#ff0000", "bogus": "#00ff00", "bg": "red", "bg2": "#123456"}, {}, "wine")
        self.assertEqual(c["accent"], "#ff0000")
        self.assertEqual(c["bg"], themes.BACKGROUNDS["wine"][1]["bg"])  # bad override ignored, backdrop kept
        self.assertEqual(c["bg2"], "#123456")                            # good override beats the backdrop
        self.assertNotIn("bogus", c)

    def test_unknown_theme_falls_back_to_default(self):
        self.assertEqual(themes.resolve("nope", {}, {}), themes.base_colors(themes.DEFAULT_THEME, {}))


class IconTests(unittest.TestCase):
    def test_all_icons_stay_inside_the_unit_square(self):
        for name, prims in iconset.ICONS.items():
            for p in prims:
                pts = p[1] if p[0] == "l" else [(p[1], p[2])]
                for x, y in pts:
                    self.assertTrue(0 <= x <= 1 and 0 <= y <= 1, (name, x, y))

    def test_every_default_button_icon_exists_and_is_choosable(self):
        for bid, (_, icon, _) in C.BUTTONS.items():
            self.assertIn(icon, iconset.CHOOSABLE, bid)

    def test_none_is_choosable_and_editor_icons_are_not(self):
        self.assertIn("none", iconset.CHOOSABLE)
        self.assertNotIn("left", iconset.CHOOSABLE)

    def test_icons_used_by_the_screens_exist(self):
        for name in ("menu", "smile", "wave", "calendar", "trash", "left", "right", "check", "close"):
            self.assertIn(name, iconset.ICONS)


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

    def test_app_is_called_pacsit(self):
        self.assertEqual(C.APP_NAME, "Pacsit")

    def test_normalize_survives_garbage(self):
        for raw in (None, 5, "x", [], {"buttons": "x", "layout": 3, "custom": 7, "theme": 9, "background": []},
                    {"buttons": [{"id": []}, {"id": {}}, 7, None], "saved_themes": {"a": 1, 5: {}}, "theme": [],
                     "layout": {"menu_side": [], "bubbles": {}, "brand_align": None}}):
            cfg = C.normalize(raw)
            self.assertEqual(sorted(b["id"] for b in cfg["buttons"]), sorted(C.BUTTONS))

    def test_normalize_repairs_bad_values(self):
        cfg = C.normalize({"theme": "zzz", "background": "mud", "custom": {"accent": "blue", "bg": "#ABCDEF", "x": "#000"},
                           "layout": {"btn_h": 999, "radius": -4, "font_scale": "big", "menu_side": "up",
                                      "show_hero": 1, "bubbles": "weird"},
                           "buttons": [{"id": "mic", "region": "moon", "icon": "bogus", "label": "  "},
                                       {"id": "mic"}, {"id": "ghost"}]})
        self.assertEqual(cfg["theme"], themes.DEFAULT_THEME)
        self.assertEqual(cfg["background"], themes.BACKGROUND_DEFAULT)
        self.assertEqual(cfg["custom"], {"bg": "#abcdef"})
        self.assertEqual(cfg["layout"]["btn_h"], C.NUM_LIMITS["btn_h"][1])
        self.assertEqual(cfg["layout"]["radius"], C.NUM_LIMITS["radius"][0])
        self.assertEqual(cfg["layout"]["font_scale"], 1.0)
        self.assertEqual(cfg["layout"]["menu_side"], "left")
        self.assertTrue(cfg["layout"]["show_hero"])      # not a real bool -> default
        self.assertEqual(cfg["layout"]["bubbles"], "bubbles")
        mic = [b for b in cfg["buttons"] if b["id"] == "mic"]
        self.assertEqual(len(mic), 1)
        self.assertEqual((mic[0]["region"], mic[0]["icon"], mic[0]["label"]), ("input_right", "mic", "Mic"))

    def test_theme_entry_can_never_be_hidden(self):
        cfg = C.normalize({"buttons": [{"id": "theme", "region": "hidden"}]})
        self.assertEqual(btn(cfg, "theme")["region"], "menu")
        cfg = C.default_config()
        for _ in range(9):
            cfg = C.cycle_region(cfg, "theme")
            self.assertNotEqual(btn(cfg, "theme")["region"], "hidden")

    def test_cycle_region_visits_every_region_for_normal_buttons(self):
        cfg, seen = C.default_config(), set()
        for _ in range(4):
            cfg = C.cycle_region(cfg, "voice")
            seen.add(btn(cfg, "voice")["region"])
        self.assertEqual(seen, set(C.REGIONS))

    def test_move_button_within_region_only(self):
        cfg = C.move_button(C.default_config(), "prefs", -1)
        self.assertEqual(ids(cfg, "menu"), ["theme", "prefs", "calendar", "voice"])
        cfg = C.move_button(cfg, "theme", -1)  # already first: unchanged
        self.assertEqual(ids(cfg, "menu")[0], "theme")
        cfg = C.move_button(cfg, "send", 1)    # already last in its region: unchanged
        self.assertEqual(ids(cfg, "input_right"), ["mic", "send"])
        cfg = C.move_button(cfg, "mic", 1)
        self.assertEqual(ids(cfg, "input_right"), ["send", "mic"])

    def test_set_icon_label_and_validation(self):
        cfg = C.set_button(C.default_config(), "mic", icon="heart", label="Talk")
        self.assertEqual((btn(cfg, "mic")["icon"], btn(cfg, "mic")["label"]), ("heart", "Talk"))
        cfg = C.set_button(cfg, "mic", icon="not-an-icon", label="x" * 99)
        self.assertEqual(btn(cfg, "mic")["icon"], "mic")  # invalid icon -> default, not a crash
        self.assertEqual(len(btn(cfg, "mic")["label"]), C.LABEL_MAX)

    def test_presets_apply_and_keep_user_icons(self):
        cfg = C.set_button(C.default_config(), "mic", icon="heart")
        for pid in C.PRESETS:
            out = C.apply_preset(cfg, pid)
            self.assertEqual(out, C.normalize(out), pid)
            self.assertEqual(btn(out, "mic")["icon"], "heart", pid)
        self.assertEqual(C.apply_preset(cfg, "lefty")["layout"]["menu_side"], "right")
        self.assertEqual(C.apply_preset(cfg, "top")["layout"]["input_position"], "top")
        self.assertFalse(C.apply_preset(cfg, "minimal")["layout"]["show_hero"])

    def test_theme_switch_clears_overrides_and_background(self):
        cfg = C.set_background(C.set_color(C.default_config(), "accent", "#ff00ff"), "teal")
        self.assertEqual((cfg["background"], cfg["custom"]), ("teal", {"accent": "#ff00ff"}))
        cfg = C.set_theme(cfg, "ocean")
        self.assertEqual((cfg["theme"], cfg["background"], cfg["custom"]), ("ocean", "theme", {}))

    def test_picking_a_background_drops_overrides_on_background_roles_only(self):
        cfg = C.set_color(C.set_color(C.default_config(), "bg", "#111111"), "accent", "#ff00ff")
        cfg = C.set_background(cfg, "forest")
        self.assertEqual(cfg["custom"], {"accent": "#ff00ff"})
        self.assertEqual(C.current_colors(cfg)["bg"], themes.BACKGROUNDS["forest"][1]["bg"])

    def test_save_current_theme_keeps_the_look(self):
        cfg = C.set_background(C.set_color(C.default_config(), "accent", "#ff00ff"), "wine")
        look = C.current_colors(cfg)
        cfg = C.save_current_theme(cfg, "Mine")
        self.assertEqual(cfg["theme"], "user:Mine")
        self.assertEqual(C.current_colors(cfg), look)
        cfg = C.set_theme(cfg, "ocean")
        self.assertIn("Mine", cfg["saved_themes"])
        cfg = C.delete_saved_theme(C.set_theme(cfg, "user:Mine"), "Mine")
        self.assertEqual(cfg["theme"], themes.DEFAULT_THEME)
        with self.assertRaises(ValueError):
            C.save_current_theme(cfg, "   ")

    def test_saved_theme_limit(self):
        cfg = C.default_config()
        for i in range(themes.MAX_SAVED):
            cfg = C.save_current_theme(cfg, "t%d" % i)
        with self.assertRaises(ValueError):
            C.save_current_theme(cfg, "one too many")

    def test_store_roundtrip_atomic_and_corrupt_file(self):
        with tempfile.TemporaryDirectory() as d:
            store = C.ConfigStore(d)
            self.assertEqual(store.load(), C.default_config())  # no file yet
            cfg = C.apply_preset(C.set_background(C.set_theme(C.default_config(), "rose"), "ember"), "lefty")
            store.save(cfg)
            self.assertEqual(store.load(), cfg)
            self.assertFalse(os.path.exists(store.path + ".tmp"))
            with open(store.path, "w") as fh:
                fh.write("{ not json")
            self.assertEqual(store.load(), C.default_config())
            self.assertTrue(os.path.exists(store.path + ".bad"))  # kept for inspection, not deleted

    def test_store_tolerates_hand_edited_and_old_files(self):
        with tempfile.TemporaryDirectory() as d:
            store = C.ConfigStore(d)
            with open(store.path, "w") as fh:  # an older file with the previous (v1) layout keys
                json.dump({"theme": "forest", "layout": {"btn_h": 60, "label_mode": "icon", "stack": "side"},
                           "buttons": [{"id": "send", "region": "dock"}, {"id": "tasks", "region": "top"}]}, fh)
            cfg = store.load()
            self.assertEqual(cfg["theme"], themes.DEFAULT_THEME)  # "forest" is no longer a theme id
            self.assertEqual(cfg["layout"]["btn_h"], 60)
            self.assertEqual(len(cfg["buttons"]), len(C.BUTTONS))
            self.assertEqual(btn(cfg, "send")["region"], "input_right")  # unknown region -> default


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
