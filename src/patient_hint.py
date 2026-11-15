"""Shared filename-based patient hint matching."""

import logging
import re

logger = logging.getLogger(__name__)


def match_patient_hint(
    filename: str, names: list[str], aliases: dict[str, str] | None = None
) -> str | None:
    """Return the one family member a filename names, or None.

    The whole filename is scanned, extension included. Letters are the only word
    characters, so digits, "_", "-", "." and spaces all separate words. A spelling
    contained in a longer matched spelling is dropped. An alias counts as its
    canonical name, which need not be in `names`. Two different people, including
    a name and another person's alias on the same span, give None.
    """
    spans: list[tuple[int, int, str]] = []
    candidates = [(name, name) for name in names] + list((aliases or {}).items())
    for spelling, canonical in candidates:
        if not spelling.strip():
            continue
        words = r"[\s_.-]+".join(re.escape(w) for w in spelling.split())
        pattern = rf"(?<![^\W\d_]){words}(?![^\W\d_])"
        spans.extend((m.start(), m.end(), canonical) for m in re.finditer(pattern, filename, re.I))

    matched = {
        name
        for start, end, name in spans
        if not any(
            o_name != name
            and o_start <= start
            and end <= o_end
            and (o_start, o_end) != (start, end)
            for o_start, o_end, o_name in spans
        )
    }
    if len(matched) > 1:
        logger.info(f"Ambiguous patient hint in {filename}: leaving it to the detector")
        return None
    return next(iter(matched), None)
