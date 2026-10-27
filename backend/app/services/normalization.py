"""Normalisation used for possible-duplicate detection.

These rules deliberately err towards flagging: a match only marks a record
for human review and never blocks or rejects it.
"""

import re

_NON_ALNUM = re.compile(r"[^A-Z0-9]+")
_DIGIT_RUN = re.compile(r"\d+")
_BANK_NOISE_WORDS = {"THE", "LTD", "LIMITED", "CO", "COOPERATIVE"}


def normalize_bank_name(name: str) -> str:
    """'The Demo Co-operative Bank Ltd.' -> 'DEMO BANK'."""
    words = _NON_ALNUM.sub(" ", name.upper().replace("CO-OPERATIVE", "COOPERATIVE")).split()
    kept = [word for word in words if word not in _BANK_NOISE_WORDS]
    return " ".join(kept or words)


def normalize_fdr_number(number: str) -> str:
    """'fd/000777-a' -> 'FD777A': upper-case, separators removed, zero padding dropped from digit runs."""
    compact = _NON_ALNUM.sub("", number.upper())
    return _DIGIT_RUN.sub(lambda match: match.group().lstrip("0") or "0", compact)
