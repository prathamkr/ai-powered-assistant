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
    "done_all": "\ue877",   # done_all (double tick on sent messages)
    "settings": "\ue8b8",   # settings (gear)
    "repeat": "\ueb7b",     # event_repeat (Automations)
    "search": "",     # search
    "phone": "",      # smartphone
    "camera": "",     # photo_camera
    "note": "",       # sticky_note_2
    "user": "",       # person
    "bookmark": "",   # bookmark
    "dots": "",       # more_horiz
    "menu": "",       # menu
    "calendar": "",   # calendar_month
    "wave": "",       # graphic_eq
    "edit": "",       # edit
    "sun": "",       # light_mode
    "moon": "",      # dark_mode
    "none": "",
    # state and navigation icons
    "stop": "",       # stop
    "left": "",       # chevron_left
    "right": "",      # chevron_right
    "close": "",      # close
}

def glyph(name):
    """The character to draw for an icon name ('' for unknown names and for 'none')."""
    return GLYPHS.get(name, "")
