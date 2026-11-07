"""Untrusted text (card files, agent output, file names) must never reach the terminal as control sequences.
A card or an agent could otherwise change the window title, clear the screen, spoof the UI or, in some terminals, write the clipboard."""
import re

_BAD = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")
_SGR = re.compile(r"(\x1b\[[0-9;]*m)")


def clean(s):
    """Drop every control character (ESC, BEL, CR, C1...) and invisible/bidi-override characters. Newlines stay, tabs become spaces."""
    return _BAD.sub("", str(s).replace("\t", " ").replace("\r", ""))


def keep_sgr(line):
    """For a finished screen line: only the panel's own color codes (ESC [ ... m) may remain."""
    return "".join(part if i % 2 else clean(part) for i, part in enumerate(_SGR.split(line)))
