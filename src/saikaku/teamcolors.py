"""Team colours for the post images.

Colour says *whose* call it was, never whether it was good: every call of a
team is drawn in that team's colour, and good versus poor is carried by form
(bars pointing right or left, a filled versus an outlined verdict badge, a
solid versus a hollow marker). That keeps the images readable without a
second, competing colour per team, and for readers who see colour
differently. Even calls are grey.

Two teams whose colours sit close on the colour wheel (Chunichi and DeNA are
both blue) are told apart by lightness: the followed team keeps its colour
and the other is moved to a clearly lighter tone. Every colour is darkened
until it reads as text on the light background.

The hex values approximate each club's main colour; adjust them here.
"""

from __future__ import annotations

import colorsys

TEAM_COLORS = {
    "中日": "#0B3D91",       # Dragons blue (deep)
    "DeNA": "#0071BC",
    "巨人": "#F97709",
    "阪神": "#E8B800",
    "広島": "#D7000F",
    "ヤクルト": "#00843D",
    "ソフトバンク": "#F5B800",
    "日本ハム": "#006298",
    "ロッテ": "#222222",
    "楽天": "#860010",
    "オリックス": "#00285A",
    "西武": "#1F366A",
}

BACKGROUND = "#F7F6F2"
GREY = "#8A867B"
GREY_SOFT = "#ECEAE4"
FALLBACK = "#4A5560"
#: Contrast against the background needed for coloured numbers and labels.
MIN_CONTRAST = 3.0
#: Hues closer than this (in turns of the wheel) count as the same family.
SAME_FAMILY = 40 / 360


def _rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(max(0, min(1, v)) * 255):02X}" for v in rgb)


def _luminance(rgb: tuple[float, float, float]) -> float:
    def channel(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str = BACKGROUND) -> float:
    la, lb = sorted((_luminance(_rgb(a)), _luminance(_rgb(b))), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable(hex_color: str) -> str:
    """Darken a colour until it stands out against the background."""

    h, l, s = colorsys.rgb_to_hls(*_rgb(hex_color))
    color = hex_color
    while contrast(color) < MIN_CONTRAST and l > 0.05:
        l -= 0.02
        color = _hex(colorsys.hls_to_rgb(h, l, s))
    return color


def soft(hex_color: str, amount: float = 0.84) -> str:
    """A pale tint of a colour, for filled areas."""

    w = _rgb(BACKGROUND)
    return _hex(tuple(c + (wc - c) * amount for c, wc in zip(_rgb(hex_color), w)))


def _same_family(a: str, b: str) -> bool:
    ha, la, sa = colorsys.rgb_to_hls(*_rgb(a))
    hb, lb, sb = colorsys.rgb_to_hls(*_rgb(b))
    if sa < 0.15 or sb < 0.15:  # greys and blacks: compare lightness only
        return abs(la - lb) < 0.2
    gap = abs(ha - hb)
    return min(gap, 1 - gap) < SAME_FAMILY


def _lighter(hex_color: str) -> str:
    """The same hue at a clearly lighter, still readable tone."""

    h, l, s = colorsys.rgb_to_hls(*_rgb(hex_color))
    if s < 0.15:  # a grey or black stays neutral, just lighter
        return _hex(colorsys.hls_to_rgb(h, max(l, 0.45), s))
    return _hex(colorsys.hls_to_rgb(h, max(l, 0.47), max(s, 0.85)))


def colors(team: str) -> dict[str, str]:
    """One team's colours: ``main`` for marks and text, ``soft`` for areas."""

    main = readable(TEAM_COLORS.get(team, FALLBACK))
    return {"main": main, "soft": soft(main)}


def game_colors(followed: str, other: str) -> dict[str, dict[str, str]]:
    """Colours for both teams of one game, kept apart from each other."""

    first = readable(TEAM_COLORS.get(followed, FALLBACK))
    second = TEAM_COLORS.get(other, FALLBACK)
    if _same_family(first, second):
        second = _lighter(second)
    second = readable(second)
    return {
        followed: {"main": first, "soft": soft(first)},
        other: {"main": second, "soft": soft(second)},
    }
