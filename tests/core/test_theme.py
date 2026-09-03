"""The derived palette has to be readable, complete, and stable."""

import re
from pathlib import Path

import pytest

from core.theme import (
    DEFAULT_SEEDS,
    contrast_ratio,
    derive_palette,
    normalise_hex,
    validate_seeds,
)

AA = 4.5

#: Every `onX` token is drawn on top of `X`; these are the pairs the app makes.
PAIRS = [
    ("primary", "onPrimary"),
    ("primaryContainer", "onPrimaryContainer"),
    ("secondary", "onSecondary"),
    ("secondaryContainer", "onSecondaryContainer"),
    ("tertiary", "onTertiary"),
    ("tertiaryContainer", "onTertiaryContainer"),
    ("surface", "onSurface"),
    ("surface", "onSurfaceVariant"),
    ("surfaceContainerHighest", "onSurfaceVariant"),
    ("inverseSurface", "inverseOnSurface"),
]

#: Colours chosen to be awkward: near-white, near-black, and a mid yellow that
#: white text cannot sit on — the case a hand-filled palette gets wrong.
AWKWARD = ["#ffffff", "#000000", "#ffd400", "#7a7a7a", "#ff0000", "#004466"]


def _app_palette_keys() -> set:
    """The token names the Expo app's `Palette` type declares."""
    source = Path(__file__).resolve().parents[3] / "client/common/theme/palettes.ts"
    block = source.read_text(encoding="utf-8").split("export type Palette = {", 1)[1]
    return set(re.findall(r"^\s*(\w+):\s*string;", block.split("};", 1)[0], re.M))


def test_derives_exactly_the_tokens_the_app_declares():
    assert set(derive_palette(DEFAULT_SEEDS)) == _app_palette_keys()


@pytest.mark.parametrize("seed", AWKWARD)
def test_text_stays_readable_on_any_seed(seed):
    palette = derive_palette({"primary": seed, "secondary": seed, "tertiary": seed})
    for background, foreground in PAIRS:
        ratio = contrast_ratio(palette[background], palette[foreground])
        assert ratio >= AA, f"{seed}: {foreground} on {background} is only {ratio:.2f}:1"


def test_one_brand_colour_is_enough():
    """A school with a single colour is a school, not a form that won't submit."""
    seeds, errors = validate_seeds({"primary": "#4648d4"})
    assert errors == {}
    assert set(derive_palette(seeds)) == _app_palette_keys()


def test_status_colours_are_not_the_schools_to_choose():
    palette = derive_palette({"primary": "#00aa00"})
    assert palette["error"] == "#ba1a1a"
    assert palette["success"] == "#34C759"


@pytest.mark.parametrize(
    "value,expected",
    [("#abc", "#aabbcc"), ("#AABBCC", "#aabbcc"), ("  #4648d4 ", "#4648d4")],
)
def test_accepts_the_shapes_people_paste(value, expected):
    assert normalise_hex(value) == expected


@pytest.mark.parametrize("value", ["red", "#12345", "4648d4", "", None, 42])
def test_rejects_anything_that_is_not_a_hex_colour(value):
    assert normalise_hex(value) is None


def test_primary_is_required_and_unknown_keys_are_refused():
    assert "primary" in validate_seeds({"secondary": "#fff"})[1]
    assert "seeds" in validate_seeds({"primary": "#fff", "quaternary": "#000"})[1]
