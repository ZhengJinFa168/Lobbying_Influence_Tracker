"""Organisation-name matching helpers shared by S06 and S06b (moved out of s06_orgs)."""
from __future__ import annotations

import re

from .textutil import ascii_fold, normalise_name


def acronyms(name: str, initials: bool = True) -> set[str]:
    """Acronyms a name carries: bracketed upper-case tokens, an all-caps leading token ('AFNUM - ...'),
    and (register side only) the initials of a 3+ word name."""
    out = set()
    for b in re.findall(r"\(([^)]+)\)", name or ""):
        for tok in re.findall(r"\b[A-Z][A-Z0-9&\-]{1,9}\b", b):
            out.add(tok.replace("-", "").replace("&", ""))
    # Have Your Say side: only an acronym that stands alone or before a separator; register side: any
    # all-caps leading token ("CFE-CGC Confédération ...")
    lead = r"\s*([A-Z][A-Z0-9&\-]{1,9})\b" if initials else r"\s*([A-Z][A-Z0-9&\-]{1,9})(\s+[-\u2013:|(]|\s*$)"
    first = re.match(lead, name or "")
    if first:
        out.add(first.group(1).replace("-", "").replace("&", ""))
    if initials:
        words = [w for w in re.findall(r"[A-Za-z]+", ascii_fold(re.sub(r"\([^)]*\)", " ", name or "")))
                 if w.lower() not in {"of", "and", "for", "the", "de", "des", "du", "la", "le", "et", "fur", "und", "in"}]
        if len(words) >= 3:
            out.add("".join(w[0] for w in words).upper())
    return {a for a in out if len(a) >= 3}


def mnorm(name: str) -> str:
    """Matching normalisation on top of normalise_name: drops a leading 'the' and Dutch 'stichting'."""
    s = normalise_name(name)
    return re.sub(r"^(the|stichting)\s+", "", s)
