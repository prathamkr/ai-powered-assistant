"""Icon names -> glyphs of the bundled icon font (Material Icons Round, Apache-2.0).

An icon font is drawn by the text engine (FreeType), so the shapes are real vector outlines that stay
sharp and smooth at any size. The font file is pa_ui/fonts/MaterialIconsRound-Regular.otf; the
codepoints below come from its .codepoints list (names in the comments).
Pure Python: no Kivy needed to import this module.
"""

GLYPHS = {
    "mic": "",        # mic
    "speaker": "",    # volume_up
    "sliders": "",    # tune
    "list": "",       # checklist
    "send": "",       # send
    "trash": "",      # delete
    "home": "",       # home
    "star": "",       # star
    "heart": "",      # favorite
    "bell": "",       # notifications
    "plus": "",       # add
    "check": "",      # check
    "search": "",     # search
    "phone": "",      # smartphone
    "camera": "",     # photo_camera
    "note": "",       # sticky_note_2
    "user": "",       # person
    "palette": "",    # palette
    "bookmark": "",   # bookmark
    "dots": "",       # more_horiz
    "menu": "",       # menu
    "calendar": "",   # calendar_month
    "wave": "",       # graphic_eq
    "none": "",
    # used by the screens themselves (not offered in the icon picker)
    "stop": "",       # stop
    "left": "",       # chevron_left
    "right": "",      # chevron_right
    "close": "",      # close
}

EDITOR_ONLY = ("left", "right", "close", "stop")
CHOOSABLE = [n for n in GLYPHS if n not in EDITOR_ONLY]


def glyph(name):
    """The character to draw for an icon name ('' for unknown names and for 'none')."""
    return GLYPHS.get(name, "")
