from __future__ import annotations

import pytest

from app.services.episode_parse import ParsedRelease, guess_episode_number, parse_release_filename


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("[Group] Mushoku Tensei S02E07 [1080p].mkv", "7"),
        ("Attack on Titan - 12.mkv", "12"),
        ("Some Anime Episode 3.mkv", "3"),
        ("Fate Zero E05.mkv", "5"),
    ],
)
def test_guess_episode_number(filename: str, expected: str) -> None:
    assert guess_episode_number(filename) == expected


def test_guess_episode_number_no_match() -> None:
    assert guess_episode_number("no_numbers_here.mkv") is None


@pytest.mark.parametrize(
    "filename,expected",
    [
        # Underscore-separated release with a trailing language tag -- the
        # motivating real-world case: no space/dot/dash anywhere near the
        # episode number, only underscores, which the old regex-only
        # guess_episode_number couldn't handle at all (word-boundary
        # assertions never fire between two word characters, and "_" counts
        # as one).
        (
            "No_Waifu_No_Life_02_ENG.mkv",
            ParsedRelease(title="No Waifu No Life", season=None, episode="2"),
        ),
        # Dash-separated title words, with the episode number glued to a
        # trailing resolution tag via "_".
        (
            "h-na-gishi-series-the-animation-2_1440p.mp4",
            ParsedRelease(title="h na gishi series the animation", season=None, episode="2"),
        ),
        (
            "[Group] Mushoku Tensei S02E07 [1080p].mkv",
            ParsedRelease(title="Mushoku Tensei", season=2, episode="7"),
        ),
        ("Attack on Titan - 12.mkv", ParsedRelease(title="Attack on Titan", season=None, episode="12")),
        ("Some Anime Episode 3.mkv", ParsedRelease(title="Some Anime", season=None, episode="3")),
        ("Fate Zero E05.mkv", ParsedRelease(title="Fate Zero", season=None, episode="5")),
        (
            "[SubsPlease] No Waifu No Life - 04 (1080p) [ABCD1234].mkv",
            ParsedRelease(title="No Waifu No Life", season=None, episode="4"),
        ),
        # A leading "site.tld"-shaped token is dropped from the title.
        (
            "AnimeSite.to_No_Waifu_No_Life_03.mkv",
            ParsedRelease(title="No Waifu No Life", season=None, episode="3"),
        ),
        ("no_numbers_here.mkv", ParsedRelease(title="no numbers here", season=None, episode=None)),
    ],
)
def test_parse_release_filename(filename: str, expected: ParsedRelease) -> None:
    assert parse_release_filename(filename) == expected


def test_a_year_in_the_title_is_not_the_episode_number() -> None:
    """"First number ends the title" breaks on a release year: `Dororo
    (2019) - 01` parsed as episode 2019, and the scan then overwrote the
    correct stored number with it."""
    parsed = parse_release_filename("Dororo (2019) - 01.mkv")
    assert parsed.episode == "1"
    assert parsed.title == "Dororo"

    assert guess_episode_number("Anime 2011 - 03.mkv") == "3"
    # A year as the only number means there is no episode number at all.
    assert guess_episode_number("Movie 2019.mkv") is None


def test_a_title_starting_with_a_number_keeps_it() -> None:
    """Real entries in the library start with a number ("69 Itsuwari no
    Bishou", "86 Eighty-Six"); the leading number is part of the name as long
    as a real episode number follows."""
    parsed = parse_release_filename("69 Itsuwari no Bishou - 02.mkv")
    assert parsed.episode == "2"
    assert parsed.title == "69 Itsuwari no Bishou"

    parsed = parse_release_filename("86 Eighty-Six - 01.mkv")
    assert parsed.episode == "1"
    assert parsed.title == "86 Eighty Six"

    # A lone leading number is still the episode.
    assert guess_episode_number("01.mkv") == "1"


def test_an_explicit_episode_marker_beats_any_bare_number() -> None:
    assert guess_episode_number("Show 2019 Ep03.mkv") == "3"
    assert guess_episode_number("Show - E07 - Name.mkv") == "7"
