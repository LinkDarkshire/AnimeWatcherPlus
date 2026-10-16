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
# An episode number alone in square brackets: "Show [01][1080p]". Up to three
# digits, so resolutions ([1080p]) and years don't count; CRCs have letters.
_BRACKETED_NUMBER = re.compile(r"\[(\d{1,3})(?:v\d)?\]")
# "01v3": episode 1, third version of the release.
_VERSIONED_NUMBER = re.compile(r"^(\d{1,4})v\d$", re.IGNORECASE)
_STRAY_BRACKET_CHARS = re.compile(r"[()\[\]{}]")
_SEPARATORS = re.compile(r"[_\-]")
_SEASON_EPISODE = re.compile(r"[Ss](?P<season>\d{1,2})[Ee](?P<ep>\d{1,4})")
# An episode number with its marker in one token: "E05", "Ep05", "Episode05",
# "Ep.05", "Vol.01", "Folge3", "Part2", "#04".
_EP_PREFIXED_TOKEN = re.compile(
    r"^(?:e|ep|episode|vol|folge|part|#)\.?(?P<ep>\d{1,4})$", re.IGNORECASE
)
# The same markers as separate words ("Vol 01"): they belong to neither the
# title nor the number.
_SKIP_WORDS = {"ep", "ep.", "epi", "episode", "vol", "vol.", "folge", "part", "#"}
_NOISE_TOKEN = re.compile(r"^(?:\d{3,4}p|[xh]26[45]|eng|jpn|ger|fre|sub|dub|raw)$", re.IGNORECASE)
# A leading "site.com"-style tag (letters after the dot, so "Vol.01" isn't one).
_SITE_TAG = re.compile(r"^\w+\.[A-Za-z]{2,4}$")
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

    # "Show.Name.02" -- dots instead of spaces, common for scene releases.
    if " " not in stem.strip() and stem.count(".") >= 2:
        stem = stem.replace(".", " ")

    tokens = [_VERSIONED_NUMBER.sub(r"\1", t) for t in _SEPARATORS.sub(" ", stem).split() if t]
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
        # Last resort: the number may sit in brackets, which were dropped above.
        bracketed = _BRACKETED_NUMBER.search(Path(filename).stem)
        episode = str(int(bracketed.group(1))) if bracketed else None
        return ParsedRelease(title=_title_from(tokens), season=None, episode=episode)
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
