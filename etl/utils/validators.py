"""
Standalone validators, usable on any single value from any file --
deliberately not wired into OrderDatasetTransformer's rule list, so
adding them here doesn't change either main.py's or main_hybrid.py's
already-verified output. Call these directly wherever a per-file or
per-column check is actually wanted.
"""

from __future__ import annotations

import re

_IPV4_SHAPE_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")


def is_valid_ipv4(value: str) -> bool:
    """
    True only if `value` is a syntactically well-formed IPv4 address --
    four dot-separated octets, each 0-255. Stricter than a regex alone:
    `_IPV4_SHAPE_RE` only confirms the *shape* (four dot-separated groups
    of 1-3 digits); a value like "999.999.999.999" matches that shape but
    isn't a real address, so each octet's numeric range is checked too.
    """
    if not value:
        return False

    value = value.strip()
    if not _IPV4_SHAPE_RE.match(value):
        return False

    return all(0 <= int(octet) <= 255 for octet in value.split("."))
