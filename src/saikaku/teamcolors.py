"""Team colours for the post images.

A good call is drawn in the deciding team's colour and a poor one in its
complement (hue turned half way round), so the two teams' calls never share
a colour. Even calls stay grey. Colours are darkened until they read as text
on the light background, which matters for pale ones such as yellow.

The hex values are approximations of each club's main colour, chosen so that
clubs sharing a hue (Chunichi and DeNA are both blue) still differ in
lightness. Adjust them here.
"""

from __future__ import annotations

import colorsys

TEAM_COLORS = {
    "中日": "#002E8A",       # deep Dragons blue
    "DeNA": "#0091D7",       # bright Yokohama blue
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
#: Default colours for a team not in the table.
FALLBACK = {"pos": "#1B7A55", "neg": "#B4432B"}
#: Contrast against the background needed for coloured numbers and labels.
MIN_CONTRAST = 3.0


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
        l -= 0.03
        color = _hex(colorsys.hls_to_rgb(h, l, s))
    return color


def complement(hex_color: str) -> str:
    """The colour on the other side of the colour wheel, at the same lightness.

    Near-grey colours have no meaningful opposite, so they get a red instead.
    """

    h, l, s = colorsys.rgb_to_hls(*_rgb(hex_color))
    if s < 0.15:
        return FALLBACK["neg"]
    return _hex(colorsys.hls_to_rgb((h + 0.5) % 1.0, l, s))


def soft(hex_color: str, amount: float = 0.82) -> str:
    """A pale tint of a colour, for pills and filled areas."""

    r, g, b = _rgb(hex_color)
    w = _rgb(BACKGROUND)
    return _hex(tuple(c + (wc - c) * amount for c, wc in zip((r, g, b), w)))


def palette(team: str) -> dict[str, str]:
    """Colours for one team: pos/neg (and their soft tints) and even."""

    base = TEAM_COLORS.get(team)
    pos = readable(base) if base else FALLBACK["pos"]
    neg = readable(complement(base)) if base else FALLBACK["neg"]
    return {
        "pos": pos,
        "neg": neg,
        "even": GREY,
        "pos_soft": soft(pos),
        "neg_soft": soft(neg),
        "even_soft": GREY_SOFT,
    }
