"""Lazey's typefaces (files + licences in pa_ui/fonts/).

    HEADING  Poppins SemiBold (600)  app name, headings, the greeting          (SIL OFL)
    BUTTON   Poppins Medium (500)    button, chip and pill labels              (SIL OFL)
    SUB      Poppins Regular (400)   subtitles and descriptions                (SIL OFL)
    UI       Inter Regular (400)     message input, chat text, smaller text    (SIL OFL)
    ICON     Material Icons Round    every icon (a font, so icons are real vector outlines) (Apache-2.0)

Importing this module registers the fonts, makes Inter the default for every Kivy widget, and turns
glyph hinting off for all labels. Hinting snaps letter shapes to the pixel grid, which is what makes
text look slightly rough on a phone screen; without it the outlines are rendered smoothly.
"""
import os

from kivy.core.text import DEFAULT_FONT, LabelBase
from kivy.uix.label import Label

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

HEADING = "LazeyHeading"
BUTTON = "LazeyButton"
SUB = "LazeySub"
UI = "LazeyUI"
ICON = "LazeyIcons"

FILES = {HEADING: "Poppins-SemiBold.ttf", BUTTON: "Poppins-Medium.ttf", SUB: "Poppins-Regular.ttf",
         UI: "Inter-Regular.ttf", ICON: "MaterialIconsRound-Regular.otf"}


def path(name):
    return os.path.join(_DIR, FILES[name])


def register():
    for name in FILES:
        LabelBase.register(name, fn_regular=path(name))
    # Inter is the default face for everything that does not ask for another one
    LabelBase.register(DEFAULT_FONT, fn_regular=path(UI))
    # smooth glyph outlines for every Label/Button (hinting off), unless a caller asks otherwise
    if not getattr(Label, "_lazey_smooth", False):
        original = Label.__init__

        def smooth_init(self, **kw):
            kw.setdefault("font_hinting", None)
            original(self, **kw)
        Label.__init__ = smooth_init
        Label._lazey_smooth = True


register()
