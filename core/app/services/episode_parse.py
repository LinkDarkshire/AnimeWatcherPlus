from __future__ import annotations

import re

# Lightweight regex-based episode-number guess used only to populate LocalEpisode
# rows for the M1-M4 completeness badge. The full anitopy-based parser (accurate
# release-name parsing feeding the Soll-Ist "fehlende Episoden" comparison) is
# scoped to M5, per the project plan.
_PATTERNS = [
    re.compile(r"[Ss](?P<season>\d{1,2})[Ee](?P<ep>\d{1,4})"),
    re.compile(r"\b[Ee][Pp]?(?:isode)?[ _.-]?(?P<ep>\d{1,4})\b"),
    re.compile(r"[ _-]-[ _-](?P<ep>\d{1,4})(?:v\d)?[ _.\[]"),
    re.compile(r"\b(?P<ep>\d{1,4})\b(?=[^\d]*$)"),
]


def guess_episode_number(filename: str) -> str | None:
    for pattern in _PATTERNS:
        match = pattern.search(filename)
        if match:
            return str(int(match.group("ep")))
    return None
