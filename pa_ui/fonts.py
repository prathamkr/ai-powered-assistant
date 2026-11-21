"""Lazey's typefaces (all SIL Open Font Licence, files + licences in pa_ui/fonts/).

    HEADING  Poppins SemiBold (600)  app name, headings and the greeting
    SUB      Poppins Regular (400)   subtitles and descriptions
    UI       Inter Regular (400)     message input, chat text and smaller UI text

Importing this module registers the three fonts and makes Inter the default for every Kivy widget, so
anything without an explicit font_name (buttons, text boxes, chat bubbles, small labels) is Inter.
"""
import os

from kivy.core.text import DEFAULT_FONT, LabelBase

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

HEADING = "LazeyHeading"
SUB = "LazeySub"
UI = "LazeyUI"

FILES = {HEADING: "Poppins-SemiBold.ttf", SUB: "Poppins-Regular.ttf", UI: "Inter-Regular.ttf"}


def path(name):
    return os.path.join(_DIR, FILES[name])


def register():
    for name in FILES:
        LabelBase.register(name, fn_regular=path(name))
    # Inter is the default face for everything that does not ask for another one
    LabelBase.register(DEFAULT_FONT, fn_regular=path(UI))


register()
