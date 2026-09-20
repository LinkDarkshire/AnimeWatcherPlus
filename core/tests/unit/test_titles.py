from __future__ import annotations

from app.services import artwork
from app.services.titles import load_variants_from_aniinfo
from app.domain.titles import (
    DEFAULT_TITLE_ORDER,
    TITLE_VARIANT_EN,
    TITLE_VARIANT_JA,
    TITLE_VARIANT_MAIN,
    normalize_title_order,
    pick_variants,
    resolve_title,
)

# Same shape AniDB emits: one type="main" entry plus several per-language
# entries of differing quality.
SAMPLE_ENTRIES = [
    ("Seikai no Monshou", "x-jat", "main"),
    ("Zvyozdnyy Gerb", "ru", "synonym"),
    ("CotS", "en", "short"),
    ("星界の紋章", "ja", "official"),
    ("Crest of the Stars", "en", "official"),
]


def test_pick_variants_splits_the_three_languages() -> None:
    variants = pick_variants(SAMPLE_ENTRIES)
    assert variants == {
        TITLE_VARIANT_MAIN: "Seikai no Monshou",
        TITLE_VARIANT_EN: "Crest of the Stars",
        TITLE_VARIANT_JA: "星界の紋章",
    }


def test_pick_variants_prefers_official_over_synonym_over_short() -> None:
    entries = [
        ("Short", "en", "short"),
        ("Synonym", "en", "synonym"),
        ("Official", "en", "official"),
    ]
    assert pick_variants(entries)[TITLE_VARIANT_EN] == "Official"


def test_pick_variants_uses_short_title_when_nothing_better_exists() -> None:
    """"short" is ranked worst, but a worst-ranked title still beats no title
    -- the variant must not come back empty just because the only English
    entry is an abbreviation."""
    assert pick_variants([("CotS", "en", "short")])[TITLE_VARIANT_EN] == "CotS"


def test_pick_variants_falls_back_to_romanized_lang_without_main_type() -> None:
    entries = [("Nihongo no Taitoru", "x-jat", "official"), ("日本語", "ja", "official")]
    variants = pick_variants(entries)
    assert variants[TITLE_VARIANT_MAIN] == "Nihongo no Taitoru"
    assert variants[TITLE_VARIANT_JA] == "日本語"


def test_pick_variants_leaves_missing_languages_none() -> None:
    variants = pick_variants([("Only Main", "x-jat", "main")])
    assert variants[TITLE_VARIANT_MAIN] == "Only Main"
    assert variants[TITLE_VARIANT_EN] is None
    assert variants[TITLE_VARIANT_JA] is None


def test_resolve_title_follows_the_given_order() -> None:
    variants = pick_variants(SAMPLE_ENTRIES)
    assert resolve_title(variants, ["main", "en", "ja"], "fb") == "Seikai no Monshou"
    assert resolve_title(variants, ["en", "main", "ja"], "fb") == "Crest of the Stars"
    assert resolve_title(variants, ["ja", "en", "main"], "fb") == "星界の紋章"


def test_resolve_title_skips_missing_variants() -> None:
    variants = pick_variants([("Only Main", "x-jat", "main")])
    assert resolve_title(variants, ["en", "ja", "main"], "fb") == "Only Main"


def test_resolve_title_falls_back_when_no_variant_is_known() -> None:
    """The case every anime identified before the variant columns existed is
    in: all three NULL, so the already-stored title has to survive."""
    assert resolve_title({}, DEFAULT_TITLE_ORDER, "Existing Title") == "Existing Title"


def test_normalize_title_order_completes_a_partial_order() -> None:
    assert normalize_title_order(["ja"]) == ["ja", "en", "main"]


def test_normalize_title_order_drops_unknown_and_duplicate_entries() -> None:
    assert normalize_title_order(["en", "en", "klingon", "ja"]) == ["en", "ja", "main"]


def test_normalize_title_order_rejects_non_list_values() -> None:
    for value in (None, "en", 42, {"en": 1}):
        assert normalize_title_order(value) == DEFAULT_TITLE_ORDER


def test_load_variants_from_aniinfo_reads_the_sidecar_title_list(tmp_path) -> None:
    (tmp_path / artwork.ANIINFO_FILENAME).write_text(
        '{"titles": [{"language": "en", "type": "official", "value": "Crest of the Stars"}]}',
        encoding="utf-8",
    )
    assert load_variants_from_aniinfo(tmp_path) == {
        TITLE_VARIANT_MAIN: None,
        TITLE_VARIANT_EN: "Crest of the Stars",
        TITLE_VARIANT_JA: None,
    }


def test_load_variants_from_aniinfo_returns_none_without_a_sidecar(tmp_path) -> None:
    assert load_variants_from_aniinfo(tmp_path) is None


def test_load_variants_from_aniinfo_tolerates_a_corrupt_sidecar(tmp_path) -> None:
    (tmp_path / artwork.ANIINFO_FILENAME).write_text("{not json", encoding="utf-8")
    assert load_variants_from_aniinfo(tmp_path) is None


def test_load_variants_from_aniinfo_tolerates_a_title_less_sidecar(tmp_path) -> None:
    (tmp_path / artwork.ANIINFO_FILENAME).write_text('{"anidb_id": 1}', encoding="utf-8")
    assert load_variants_from_aniinfo(tmp_path) is None
