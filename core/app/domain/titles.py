from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.domain.metadata import AnimeMetadata

# The three title variants AniDB distinguishes for every anime. Two
# independent user-configurable preference orders pick between them: one for
# the name shown in the library overview, one for the on-disk directory and
# file names. They're separate on purpose -- a user may well want to browse by
# the English title while keeping folder names in the romanized form an
# external media server already indexed.
TITLE_VARIANT_MAIN = "main"  # <title type="main">, in practice romanized Japanese (x-jat)
TITLE_VARIANT_EN = "en"  # official/primary English title
TITLE_VARIANT_JA = "ja"  # original title in Japanese script
TITLE_VARIANTS = (TITLE_VARIANT_MAIN, TITLE_VARIANT_EN, TITLE_VARIANT_JA)

# English first, then the romanized main title, and Japanese script only as a
# last resort -- the behavior the provider's own cascade had before these
# orders became configurable, so an existing library doesn't rename itself
# just because the setting was introduced.
DEFAULT_TITLE_ORDER = [TITLE_VARIANT_EN, TITLE_VARIANT_MAIN, TITLE_VARIANT_JA]

# AniDB marks exactly one title per anime as type="main" and tags the rest by
# language; within one language it emits several entries of differing quality.
# Ranked so an "official" title always beats a fan synonym, and an
# abbreviation ("short") is only ever used when nothing else exists.
_TITLE_TYPE_RANK = {"main": 0, "official": 1, "syn": 2, "synonym": 2, "short": 4}
_DEFAULT_TYPE_RANK = 3
_WORST_TYPE_RANK = max(*_TITLE_TYPE_RANK.values(), _DEFAULT_TYPE_RANK) + 1

# The language AniDB uses for romanized Japanese; the type="main" title is
# normally tagged with it, so it doubles as the fallback for the main variant.
_ROMANIZED_LANG = "x-jat"

TitleEntry = tuple[str, str | None, str | None]  # (text, xml:lang, type)
Variants = dict[str, str | None]


def _best_for_lang(entries: Iterable[TitleEntry], lang: str) -> str | None:
    best: str | None = None
    best_rank = _WORST_TYPE_RANK
    for text, title_lang, title_type in entries:
        if not text or title_lang != lang:
            continue
        rank = _TITLE_TYPE_RANK.get(title_type or "", _DEFAULT_TYPE_RANK)
        if rank < best_rank:
            best, best_rank = text, rank
    return best


def pick_variants(entries: Sequence[TitleEntry]) -> Variants:
    """Splits one anime's full AniDB title list into the three variants the
    display/folder preference orders choose between."""
    main = next((text for text, _, ttype in entries if text and ttype == "main"), None)
    return {
        TITLE_VARIANT_MAIN: main or _best_for_lang(entries, _ROMANIZED_LANG),
        TITLE_VARIANT_EN: _best_for_lang(entries, "en"),
        TITLE_VARIANT_JA: _best_for_lang(entries, "ja"),
    }


def variants_from_metadata(metadata: AnimeMetadata) -> Variants:
    return {
        TITLE_VARIANT_MAIN: metadata.title_main,
        TITLE_VARIANT_EN: metadata.title_en,
        TITLE_VARIANT_JA: metadata.title_ja,
    }


def resolve_title(variants: Mapping[str, str | None], order: Sequence[str], fallback: str) -> str:
    """First non-empty variant in preference order, else `fallback`. The
    fallback matters for every anime identified before the variant columns
    existed (all three are NULL until a rescan or an aniinfo.json backfill
    fills them) -- those keep the title they already have instead of going
    blank."""
    for variant in order:
        value = variants.get(variant)
        if value:
            return value
    return fallback


def normalize_title_order(value: Any) -> list[str]:
    """Coerces whatever is in the free-form settings table into a complete,
    duplicate-free order over TITLE_VARIANTS. The settings endpoint takes
    arbitrary JSON, so a stored value can be missing entries, contain unknown
    ones, or not be a list at all -- appending the variants the caller left
    out keeps resolution total instead of leaving nothing to fall back to."""
    order: list[str] = []
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, str) and entry in TITLE_VARIANTS and entry not in order:
                order.append(entry)
    for variant in DEFAULT_TITLE_ORDER:
        if variant not in order:
            order.append(variant)
    return order
