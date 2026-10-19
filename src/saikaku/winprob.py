"""Win probability through a game, play by play, from the 試合経過 section.

Every row of the log that records the situation after it (アウト, 走者, 得点)
becomes a point: the chance that the followed team wins, with both teams taken
as league average so that each play is valued by the situation alone. The
change across a row is that play's win probability added (WPA), credited to
the batter (or runner) and, with the sign flipped, to the pitcher.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Sequence

from .gamelog import LogEntry
from .model import GameState, WinProbabilityModel

#: The team charts follow when it is playing; otherwise the home team.
DEFAULT_FOCUS = "中日"


@dataclass(frozen=True)
class Point:
    #: Position on the chart: 0 is the first pitch, i is after row i - 1.
    x: int
    #: Followed team's chance of winning, 0-1 (a draw counts half).
    wp: float
    #: The row that led here (None for the first pitch).
    entry: LogEntry | None = None
    #: Change from the previous point, for the followed team.
    delta: float = 0.0


def focus(away: str, home: str, wanted: str | None = None) -> tuple[str, bool]:
    """The team to follow and whether it is the home side."""

    for name in (wanted, DEFAULT_FOCUS):
        if name and name in (away, home):
            return name, name == home
    return home, True


def series(
    log: Sequence[LogEntry], model: WinProbabilityModel, focus_is_home: bool
) -> list[Point] | None:
    """Points for every row, or None if any row lacks the situation after it."""

    if not log or any(e.after is None for e in log):
        return None

    def for_focus(home_value: float) -> float:
        return home_value if focus_is_home else 1.0 - home_value

    start = model.probability(GameState(1, "top", 0, 0, 0))
    points = [Point(0, for_focus(1.0 - start))]
    for i, entry in enumerate(log):
        a = entry.after
        if i == len(log) - 1:
            # The last row ends the game: the score decides.
            home_value = 1.0 if a.home_score > a.away_score else 0.0
            if a.home_score == a.away_score:
                home_value = 0.5
        else:
            state = GameState(entry.inning, entry.half, a.outs, a.home_score, a.away_score,
                              a.runners)
            batting = model.probability(state)
            home_value = batting if entry.half == "bottom" else 1.0 - batting
        wp = for_focus(home_value)
        points.append(Point(i + 1, wp, entry, wp - points[-1].wp))
    return points


def swings(points: Sequence[Point], count: int = 5) -> list[Point]:
    """The plays that moved the followed team's chances most, in game order."""

    moved = sorted((p for p in points if p.entry), key=lambda p: -abs(p.delta))[:count]
    return sorted(moved, key=lambda p: p.x)


def player_totals(points: Sequence[Point], focus_is_home: bool) -> dict[tuple[str, str], float]:
    """WPA per (player, 打/投), each from his own team's side, in points."""

    totals: dict[tuple[str, str], float] = defaultdict(float)
    for p in points:
        if p.entry is None:
            continue
        batting_is_focus = (p.entry.half == "bottom") == focus_is_home
        for_batting = p.delta if batting_is_focus else -p.delta
        if p.entry.batter:
            totals[(p.entry.batter, "打")] += for_batting * 100
        if p.entry.pitcher:
            totals[(p.entry.pitcher, "投")] -= for_batting * 100
    return dict(totals)


def render_chart(
    points: Sequence[Point],
    team: str,
    title: str,
    markers: Sequence[tuple[int, str, str, str]] = (),
    opponent: str = "",
):
    """A line chart of the followed team's chances, with decision markers.

    ``markers`` are (x, label, tone, deciding_team) for decisions, placed
    before the play they preceded; tone is "pos", "neg" or "even" from the
    deciding team's side. Colour shows the team (see :mod:`saikaku.teamcolors`);
    a good call is a filled circle, a poor one a hollow ring, an even one a
    small grey dot. The area above 50% is tinted in the followed team's
    colour, below it in the opponent's.
    """

    from .teamcolors import GREY, game_colors

    palette = game_colors(team, opponent) if opponent else game_colors(team, "")

    from .card import COLORS, Fonts, _pillow  # Pillow is optional

    Image, ImageDraw, _ = _pillow()
    fonts = Fonts()
    width, height = 1200, 660
    left, right, top, bottom = 96, 40, 110, 120
    image = Image.new("RGB", (width, height), COLORS["bg"])
    draw = ImageDraw.Draw(image)
    draw.text((left, 30), title, font=fonts.get(30, True), fill=COLORS["ink"])
    draw.text((width - right, 38), f"{team}の勝率", font=fonts.get(22), fill=COLORS["muted"], anchor="ra")

    span = max(points[-1].x, 1)

    def px(x: float) -> float:
        return left + (width - left - right) * x / span

    def py(wp: float) -> float:
        return top + (height - top - bottom) * (1.0 - wp)

    for level in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = py(level)
        draw.line((left, y, width - right, y), fill=COLORS["line"], width=2 if level == 0.5 else 1)
        draw.text((left - 12, y), f"{int(level * 100)}%", font=fonts.get(18), fill=COLORS["muted"], anchor="rm")

    seen = set()
    for p in points:
        if p.entry and (p.entry.inning, p.entry.half) not in seen:
            seen.add((p.entry.inning, p.entry.half))
            x = px(p.x - 1)
            if p.entry.half == "top":
                draw.line((x, top, x, height - bottom), fill=COLORS["line"], width=1)
                draw.text((x + 6, height - bottom + 10), f"{p.entry.inning}回", font=fonts.get(18),
                          fill=COLORS["muted"])

    half_line = py(0.5)
    for a, b in zip(points, points[1:]):
        for wp_a, wp_b, x_a, x_b in ((a.wp, b.wp, px(a.x), px(b.x)),):
            above = (wp_a + wp_b) / 2 >= 0.5
            draw.polygon([(x_a, half_line), (x_a, py(wp_a)), (x_b, py(wp_b)), (x_b, half_line)],
                         fill=palette[team if above else opponent]["soft"])
    draw.line([(px(p.x), py(p.wp)) for p in points], fill=COLORS["ink"], width=3, joint="curve")

    placed: list[tuple[float, float, float, float]] = []
    label_font = fonts.get(16, True)
    circles = []
    for x, label, tone, deciding in markers:
        wp = points[min(max(x, 0), len(points) - 1)].wp
        cx, cy = px(x), py(wp)
        color = palette.get(deciding, palette[team])["main"]
        if tone == "even":
            draw.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill=GREY, outline=COLORS["surface"], width=2)
        elif tone == "pos":
            draw.ellipse((cx - 10, cy - 10, cx + 10, cy + 10), fill=color, outline=COLORS["surface"], width=2)
        else:
            draw.ellipse((cx - 10, cy - 10, cx + 10, cy + 10), fill=COLORS["surface"], outline=color, width=4)
        circles.append((cx - 10, cy - 10, cx + 10, cy + 10))
    # Put each label in the first free slot: above, below, then further out.
    for (x, label, tone, deciding), circle in zip(markers, circles):
        cx, cy = (circle[0] + circle[2]) / 2, (circle[1] + circle[3]) / 2
        w = label_font.getlength(label)
        box = None
        for dy in (-26, 12, -46, 32, -66, 52):
            candidate = (cx - w / 2 - 2, cy + dy, cx + w / 2 + 2, cy + dy + 18)
            if all(candidate[2] < b[0] or candidate[0] > b[2] or candidate[3] < b[1] or candidate[1] > b[3]
                   for b in placed + circles):
                box = candidate
                break
        box = box or (cx - w / 2 - 2, cy - 26, cx + w / 2 + 2, cy - 8)
        placed.append(box)
        label_color = GREY if tone == "even" else palette.get(deciding, palette[team])["main"]
        draw.text(((box[0] + box[2]) / 2, box[1]), label, font=label_font,
                  fill=label_color, anchor="ma")

    final = points[-1].wp
    fy = py(final)
    # Outside the plot near the edges, so it never sits on the line or a marker.
    label_y = fy - 8 if final > 0.5 else fy + 8
    draw.text((px(points[-1].x), label_y), f"{final:.0%}", font=fonts.get(20, True),
              fill=COLORS["ink"], anchor="rs" if final > 0.5 else "ra")

    legend_y = height - bottom + 44
    x0 = left
    legend_font, bold_font = fonts.get(17), fonts.get(17, True)
    for name in (team, opponent):
        if not name:
            continue
        main = palette[name]["main"]
        draw.rounded_rectangle((x0, legend_y - 8, x0 + 16, legend_y + 8), radius=3, fill=main)
        draw.text((x0 + 22, legend_y), name, font=bold_font, fill=main, anchor="lm")
        x0 += 22 + bold_font.getlength(name) + 22
    sample = COLORS["ink"]
    for shape, word in (("filled", "好判断"), ("ring", "疑問"), ("dot", "互角")):
        if shape == "filled":
            draw.ellipse((x0, legend_y - 8, x0 + 16, legend_y + 8), fill=sample)
        elif shape == "ring":
            draw.ellipse((x0, legend_y - 8, x0 + 16, legend_y + 8), fill=COLORS["surface"], outline=sample, width=3)
        else:
            draw.ellipse((x0 + 3, legend_y - 5, x0 + 13, legend_y + 5), fill=GREY)
        draw.text((x0 + 22, legend_y), word, font=legend_font, fill=COLORS["muted"], anchor="lm")
        x0 += 22 + legend_font.getlength(word) + 18
    note = "両チームを平均的な戦力とした勝率。得点の起こりやすさはMLB（Retrosheet 2022〜24）から推定。"
    draw.text((left, height - 46), note, font=fonts.get(16), fill=COLORS["muted"])
    attribution = ("The information used here was obtained free of charge from and is copyrighted by "
                   "Retrosheet. Interested parties may contact Retrosheet at \"www.retrosheet.org\".")
    size = 13
    while fonts.get(size).getlength(attribution) > width - left - right and size > 9:
        size -= 1
    draw.text((left, height - 22), attribution, font=fonts.get(size), fill=COLORS["muted"])
    return image


_BASE_NAMES = ["走者なし", "一塁", "二塁", "一二塁", "三塁", "一三塁", "二三塁", "満塁"]
_OUT_NAMES = ["無死", "一死", "二死", "三死"]


def describe(entry: LogEntry) -> str:
    a = entry.after
    bases = sum(1 << i for i, on in enumerate(a.runners) if on)
    situation = "チェンジ" if a.outs == 3 else f"{_OUT_NAMES[a.outs]}{_BASE_NAMES[bases]}"
    return f"{entry.batter} {entry.result}（→{situation} {a.away_score}-{a.home_score}）"


def report_section(points: Sequence[Point], team: str, focus_is_home: bool, chart_name: str | None) -> list[str]:
    half = {"top": "表", "bottom": "裏"}
    lines = ["## 勝率の推移", ""]
    if chart_name:
        lines += [f"![[{chart_name}]]", ""]
    lines += [
        f"両チームを平均的な戦力とした、{team}の勝率です。プレーのたびに（打席の途中の盗塁なども含めて）計算しています。",
        "",
        "### 試合の山場",
        "",
        f"| 回 | プレー | 投手 | {team}の勝率 | 増減 |",
        "| --- | --- | --- | --- | ---: |",
    ]
    for p in swings(points):
        before = p.wp - p.delta
        lines.append(f"| {p.entry.inning}回{half[p.entry.half]} | {describe(p.entry)} | {p.entry.pitcher} "
                     f"| {before:.0%}→{p.wp:.0%} | {p.delta * 100:+.1f}pt |")
    totals = player_totals(points, focus_is_home)
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    lines += ["", "### 勝率を動かした選手（自チームの勝率への寄与の合計）", "",
              "| 選手 | 打/投 | 合計 |", "| --- | --- | ---: |"]
    shown = ranked[:3] + [kv for kv in ranked[-3:] if kv not in ranked[:3]]
    for (name, role), value in shown:
        lines.append(f"| {name} | {role} | {value:+.1f}pt |")
    lines.append("")
    return lines
