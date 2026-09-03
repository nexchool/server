"""
Per-tenant colour themes.

A school picks two or three brand colours; every colour the mobile app uses is
derived from them here. The alternative — letting an operator fill in all
thirty-eight semantic tokens the app needs — is not a kindness: nobody
hand-picks `onPrimaryContainer` correctly, and the first anyone would learn of
white text on a yellow button is a parent ringing the school.

Derivation lives on the server, not in the app, for three reasons: the panel's
preview is then exactly what the app will render, the app needs no colour
maths of its own, and this file can be improved without shipping a release to
every phone.

Tenants with no seeds stored get `None` from `resolve_theme` and the app falls
back to the palette compiled into it, so an existing school's app does not
change appearance until somebody deliberately themes it.

Keep `DEFAULT_SEEDS` in step with `client/common/theme/palettes.ts` — they are
the primary/secondary/tertiary of the palette the app ships with, and the panel
shows them as the starting point for a tenant that has never been themed.
"""

from __future__ import annotations

import colorsys
import re
from typing import Dict, List, Optional, Tuple

#: The palette the app ships with, reduced to the three colours it is built on.
DEFAULT_SEEDS: Dict[str, str] = {
    "primary": "#4648d4",
    "secondary": "#006591",
    "tertiary": "#6b38d4",
}

SEED_KEYS: Tuple[str, ...] = ("primary", "secondary", "tertiary")

#: Colours a school may not choose.
#:
#: Red means stop and green means saved in every app on the phone, and a school
#: whose brand is red does not get to make its error messages look like
#: confirmations. These stay as the app ships them.
FIXED_TOKENS: Dict[str, str] = {
    "error": "#ba1a1a",
    "onError": "#ffffff",
    "errorContainer": "#ffdad6",
    "onErrorContainer": "#93000a",
    "success": "#34C759",
    "warning": "#FF9500",
}

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

#: WCAG AA for body text. Anything the app writes *on* a brand colour has to
#: clear this, which is why the `on*` tokens are chosen rather than supplied.
_AA_CONTRAST = 4.5

# ---------------------------------------------------------------- colour maths


def normalise_hex(value: str) -> Optional[str]:
    """Return `#rrggbb` lowercase, or None when the input is not a hex colour."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not _HEX_RE.match(candidate):
        return None
    candidate = candidate.lower()
    if len(candidate) == 4:  # #abc -> #aabbcc
        candidate = "#" + "".join(ch * 2 for ch in candidate[1:])
    return candidate


def _to_rgb(hex_colour: str) -> Tuple[float, float, float]:
    h = hex_colour.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _to_hex(rgb: Tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in rgb)


def _relative_luminance(hex_colour: str) -> float:
    """WCAG relative luminance."""
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in _to_rgb(hex_colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast ratio between two hex colours, 1.0 to 21.0."""
    la, lb = _relative_luminance(a), _relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _with_lightness(hex_colour: str, lightness: float, saturation_scale: float = 1.0) -> str:
    """The same hue at a different lightness — one rung of a tonal ramp."""
    r, g, b = _to_rgb(hex_colour)
    h, _, s = colorsys.rgb_to_hls(r, g, b)
    s = max(0.0, min(1.0, s * saturation_scale))
    return _to_hex(colorsys.hls_to_rgb(h, max(0.0, min(1.0, lightness)), s))


def readable_on(background: str, hue_source: Optional[str] = None) -> str:
    """
    Pick text/icon colour for `background` by measuring, not by guessing.
    Prefers a tinted near-white or near-black over pure values so the result
    still reads as part of the palette; falls back to whichever plain extreme
    wins when a tinted one cannot clear AA.
    """
    source = hue_source or background
    candidates: List[str] = [
        _with_lightness(source, 0.98, 0.35),
        _with_lightness(source, 0.12, 0.6),
        "#ffffff",
        "#000000",
    ]
    for candidate in candidates:
        if contrast_ratio(background, candidate) >= _AA_CONTRAST:
            # First match wins, and the tinted pair is listed first on purpose:
            # picking by *most* contrast would always return pure black or
            # white, which reads as unstyled next to a branded surface.
            return candidate
    return max(candidates, key=lambda c: contrast_ratio(background, c))


# ------------------------------------------------------------------ derivation


def _brand_group(name: str, seed: str) -> Dict[str, str]:
    """A brand colour and the three tokens that travel with it."""
    container = _with_lightness(seed, 0.88, 0.9)
    return {
        name: seed,
        f"on{name[0].upper()}{name[1:]}": readable_on(seed, seed),
        f"{name}Container": container,
        f"on{name[0].upper()}{name[1:]}Container": readable_on(container, seed),
    }


def derive_palette(seeds: Dict[str, str]) -> Dict[str, str]:
    """
    Build the app's full token set from two or three brand colours.

    Surfaces are near-neutral tints of the primary hue rather than plain greys:
    it is what makes a themed app feel themed even on the screens that are
    mostly white, and it is why the palette the app ships with reads as blue
    rather than grey.
    """
    primary = normalise_hex(seeds.get("primary")) or DEFAULT_SEEDS["primary"]
    secondary = normalise_hex(seeds.get("secondary")) or primary
    tertiary = normalise_hex(seeds.get("tertiary")) or secondary

    tint = lambda lightness, sat: _with_lightness(primary, lightness, sat)  # noqa: E731

    palette: Dict[str, str] = {
        # Surfaces — a ramp from the page background up to the raised cards.
        "surface": tint(0.975, 0.5),
        "surfaceDim": tint(0.88, 0.5),
        "surfaceBright": tint(0.99, 0.4),
        "surfaceContainerLowest": "#ffffff",
        "surfaceContainerLow": tint(0.96, 0.5),
        "surfaceContainer": tint(0.94, 0.55),
        "surfaceContainerHigh": tint(0.91, 0.55),
        "surfaceContainerHighest": tint(0.88, 0.55),
        "onSurface": tint(0.11, 0.7),
        "onSurfaceVariant": tint(0.32, 0.25),
        "inverseSurface": tint(0.18, 0.4),
        "inverseOnSurface": tint(0.95, 0.5),
        "outline": tint(0.5, 0.12),
        "outlineVariant": tint(0.79, 0.25),
    }
    palette.update(_brand_group("primary", primary))
    palette.update(_brand_group("secondary", secondary))
    palette.update(_brand_group("tertiary", tertiary))
    palette.update(FIXED_TOKENS)
    return palette


def validate_seeds(raw: object) -> Tuple[Optional[Dict[str, str]], Dict[str, str]]:
    """
    Check what the panel sent. Returns (seeds, errors).

    `primary` is required because everything else is derived from it — there is
    no palette without it. `secondary` and `tertiary` fall back to it, so a
    school with one brand colour is a legitimate school rather than a form the
    operator cannot submit.
    """
    errors: Dict[str, str] = {}
    if not isinstance(raw, dict):
        return None, {"seeds": "Must be an object of colour name -> hex value"}

    unknown = sorted(set(raw) - set(SEED_KEYS))
    if unknown:
        errors["seeds"] = f"Unknown colour(s): {', '.join(unknown)}"

    seeds: Dict[str, str] = {}
    for key in SEED_KEYS:
        if key not in raw or raw[key] in (None, ""):
            if key == "primary":
                errors[key] = "Required"
            continue
        normalised = normalise_hex(raw[key])
        if normalised is None:
            errors[key] = "Must be a hex colour such as #4648d4"
        else:
            seeds[key] = normalised

    return (None, errors) if errors else (seeds, {})


def resolve_theme(tenant) -> Optional[Dict[str, object]]:
    """
    The theme to serve for a tenant, or None when it has never been themed.

    None is meaningful: the app falls back to the palette compiled into it, so
    a school that has not asked for branding is not quietly re-coloured by a
    change to the derivation above.
    """
    seeds = getattr(tenant, "theme_seeds", None)
    if not seeds or not isinstance(seeds, dict):
        return None
    valid, errors = validate_seeds(seeds)
    if errors or not valid:
        # Stored seeds that no longer validate (hand-edited, or written by an
        # older build) must not take an app down; fall back to the default.
        return None
    return {"seeds": valid, "colors": derive_palette(valid)}
