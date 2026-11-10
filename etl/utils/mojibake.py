"""
Standalone mojibake repair, usable on any single value from any file --
not wired into OrderDatasetTransformer's rule list, so adding this
doesn't change either main.py's or main_hybrid.py's already-verified
output. Call repair_mojibake() directly wherever a file is suspected of
carrying text that was decoded with the wrong encoding upstream.

What this fixes, specifically: text that was originally valid UTF-8, got
decoded using the WRONG single-byte codec (latin-1, windows-1252,
mac_roman) at some point before reaching us, and is now a string of
technically-valid-but-wrong characters. Re-encoding with that same wrong
codec reproduces the original raw bytes; decoding THOSE as UTF-8 recovers
the original text. This is exactly the shape of corruption found (and
fixed at its source, by using the correct encoding to begin with) in
handoff.md's bug #4 -- this utility exists for the case where the
original bytes are already gone and only the already-mis-decoded string
is available to repair.

What this does NOT fix: text where the original bytes were already lost
upstream and replaced with literal "?" characters before this file was
ever created (see handoff.md's note on the pre-existing "?????" mojibake
in messy_sample_4.csv) -- there's no encoding trick that recovers
information that's already gone.
"""

from __future__ import annotations

#: Characters that only show up when a decode has gone wrong -- the
#: Unicode replacement character, and the C1 control range (0x80-0x9F)
#: that latin-1 maps raw UTF-8 continuation bytes into. Used as a guard so
#: this only ever attempts a repair when there's actual evidence of
#: corruption, rather than "fixing" ordinary text that happens to round-trip.
_MOJIBAKE_MARKERS = ("\ufffd",) + tuple(chr(c) for c in range(0x80, 0xA0))

#: Candidate codecs the text might have been wrongly decoded with. Tried
#: in this order; the first one that both decodes successfully AND
#: produces text with no remaining mojibake markers wins.
_CANDIDATE_ENCODINGS = ("latin-1", "windows-1252", "mac_roman")


def looks_like_mojibake(text: str) -> bool:
    return bool(text) and any(marker in text for marker in _MOJIBAKE_MARKERS)


def repair_mojibake(text: str, candidate_encodings: tuple[str, ...] = _CANDIDATE_ENCODINGS) -> str:
    """
    Returns the repaired string if a candidate encoding round-trip both
    succeeds and removes the mojibake markers; otherwise returns `text`
    completely unchanged. Never guesses past what it can verify -- same
    "don't invent, don't silently change what you can't confirm" rule the
    rest of this project follows (see rules/consistency.py's docstring in
    the other tool for the same principle applied to formatting fixes).
    """
    if not looks_like_mojibake(text):
        return text

    for encoding in candidate_encodings:
        try:
            repaired = text.encode(encoding).decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            continue

        if not looks_like_mojibake(repaired):
            return repaired

    return text
