from __future__ import annotations

import pytest

from app.services.episode_parse import guess_episode_number


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
