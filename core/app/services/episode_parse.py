from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Release-filename parser for both scan-cache episode-number guessing
# (LocalEpisode.ep_number, used for the completeness badge) and grouping
# loose download-folder files by anime title (scanner._consolidate_loose_files,
# since there's no directory name to identify by there). Handles the fansub-
# release conventions the app actually sees in practice: a leading [SubGroup]
# tag, "_"/"-" used interchangeably with spaces as word separators, a
# trailing resolution/codec/language tag, and either "SxxEyy" or a single
# bare episode number (season assumed 1 when unspecified). Still not a full
# anitopy-equivalent parser (multi-episode ranges, batch/season-pack
# notation, hash/CRC-only episode markers etc. are out of scope) -- just
# enough to reliably recover title+episode from the common single-episode
# release-filename shapes.

_BRACKET_GROUP = re.compile(r"\[[^\]]*\]")
_STRAY_BRACKET_CHARS = re.compile(r"[()\[\]{}]")
_SEPARATORS = re.compile(r"[_\-]")
_SEASON_EPISODE = re.compile(r"[Ss](?P<season>\d{1,2})[Ee](?P<ep>\d{1,4})")
_EP_PREFIXED_TOKEN = re.compile(r"^[Ee][Pp]?(?:isode)?(?P<ep>\d{1,4})$")
_SKIP_WORDS = {"ep", "epi", "episode"}
_NOISE_TOKEN = re.compile(r"^(?:\d{3,4}p|[xh]26[45]|eng|jpn|ger|fre|sub|dub|raw)$", re.IGNORECASE)
_SITE_TAG = re.compile(r"^\w+\.\w{2,4}$")
# A release year, not an episode: "Dororo (2019) - 01" must not parse as
# episode 2019. Anime episode numbers never reach this range in practice,
# while a year in the title is a common naming convention.
_YEAR_TOKEN = re.compile(r"^(?:19|20)\d{2}$")


@dataclass
class ParsedRelease:
    title: str | None
    season: int | None
    episode: str | None


def parse_release_filename(filename: str) -> ParsedRelease:
    stem = _BRACKET_GROUP.sub(" ", Path(filename).stem)
    stem = _STRAY_BRACKET_CHARS.sub(" ", stem)

    season_ep_match = _SEASON_EPISODE.search(stem)
    if season_ep_match:
        return ParsedRelease(
            title=_clean_title(stem[: season_ep_match.start()]),
            season=int(season_ep_match.group("season")),
            episode=str(int(season_ep_match.group("ep"))),
        )

    tokens = [t for t in _SEPARATORS.sub(" ", stem).split() if t]
    if tokens and _SITE_TAG.match(tokens[0]):
        tokens = tokens[1:]

    # An explicit marker ("E01", "Ep02", "Episode03") is unambiguous and wins
    # wherever it stands, ahead of any bare number.
    for index, token in enumerate(tokens):
        marked = _EP_PREFIXED_TOKEN.match(token)
        if marked:
            return ParsedRelease(
                title=_title_from(tokens[:index]), season=None, episode=str(int(marked.group("ep")))
            )

    episode_index = _episode_token_index(tokens)
    if episode_index is None:
        return ParsedRelease(title=_title_from(tokens), season=None, episode=None)
    return ParsedRelease(
        title=_title_from(tokens[:episode_index]),
        season=None,
        episode=str(int(tokens[episode_index])),
    )


def _episode_token_index(tokens: list[str]) -> int | None:
    """Which bare number is the episode.

    "The first number ends the title" holds for the overwhelmingly common
    `Title 01` shape, but two cases break it and both occur in real
    libraries: a year in the title (`Dororo 2019 - 01`) and a title that
    *starts* with a number (`86 Eighty-Six - 01`, `69 Itsuwari no Bishou -
    02`). Years never count, and a leading number only counts when it is the
    only one left -- otherwise it belongs to the title.
    """
    numeric = [i for i, token in enumerate(tokens) if token.isdigit()]
    candidates = [i for i in numeric if not _YEAR_TOKEN.match(tokens[i])]
    if len(candidates) > 1 and candidates[0] == 0:
        candidates = candidates[1:]
    return candidates[0] if candidates else None


def _is_title_noise(token: str) -> bool:
    return (
        token.lower() in _SKIP_WORDS
        or bool(_NOISE_TOKEN.match(token))
        or bool(_YEAR_TOKEN.match(token))
    )


def _title_from(tokens: list[str]) -> str | None:
    return " ".join(t for t in tokens if not _is_title_noise(t)).strip() or None


def _clean_title(raw: str) -> str:
    return re.sub(r"\s+", " ", _SEPARATORS.sub(" ", raw)).strip()


def guess_episode_number(filename: str) -> str | None:
    return parse_release_filename(filename).episode
