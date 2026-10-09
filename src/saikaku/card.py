"""Turn a scored game into images and text for a daily X post.

    python -m saikaku.card 試合/2026-08-30_DeNA-中日.md

Writes ``<note>_1.png`` (and ``<note>_2.png`` only when the full list of
decisions does not fit on one image) and ``<note>_投稿文.txt`` next to the
note. The layout is fixed so every day's post reads the same way; see
POST_FORMAT.md. Nothing is posted; posting stays a manual step.

Needs Pillow (``pip install pillow``) and a Japanese font, which Windows has.
"""

from __future__ import annotations

import datetime
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .events import EventTable
from .game import (
    Game,
    GameFormatError,
    ScoredRow,
    parse_game,
    score_game,
    team_totals,
)
from .model import GameState, WinProbabilityModel
from .tactics import TacticTable

WIDTH = 1200
MARGIN = 56
#: 3:4, the tallest a single image shows uncropped in most X timelines. Taller
#: content is compacted first and only then split onto a second image.
MAX_HEIGHT = 1600
#: How many decisions are featured as the game's turning points.
KEY_DECISIONS = 3
#: X counts most CJK characters as 2 of its 280 units.
POST_LIMIT = 280

COLORS = {
    "bg": "#F7F6F2",
    "surface": "#FFFFFF",
    "ink": "#1D1D1B",
    "muted": "#6B6A64",
    "line": "#DCD9D0",
    "header": "#1F2A33",
    "header_ink": "#FFFFFF",
    "header_muted": "#B8C2CA",
    "pos": "#1B7A55",
    "pos_soft": "#D5ECDF",
    "neg": "#B4432B",
    "neg_soft": "#F4DCD4",
    "even": "#8A867B",
    "even_soft": "#ECEAE4",
}

#: (file, face index). Index 1 of the BIZ UD Gothic collection is the
#: proportional UDPGothic, whose figures do not spread out like the fixed one.
_FONT_CANDIDATES = {
    "bold": [("BIZ-UDGothicB.ttc", 1), ("YuGothB.ttc", 0), ("meiryob.ttc", 0), ("NotoSansJP-VF.ttf", 0)],
    "regular": [("BIZ-UDGothicR.ttc", 1), ("YuGothM.ttc", 0), ("meiryo.ttc", 0), ("NotoSansJP-VF.ttf", 0)],
}
_FONT_DIRS = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts"), Path("/Library/Fonts")]

_BASE_NAMES = ["走者なし", "一塁", "二塁", "一二塁", "三塁", "一三塁", "二三塁", "満塁"]
_OUT_NAMES = ["無死", "一死", "二死"]


def _pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise SystemExit("画像の作成には Pillow が必要です: python -m pip install pillow") from None
    return Image, ImageDraw, ImageFont


class Fonts:
    def __init__(self) -> None:
        _, _, ImageFont = _pillow()
        self._font = ImageFont
        self._paths = {weight: self._find(names) for weight, names in _FONT_CANDIDATES.items()}
        self._cache: dict = {}

    @staticmethod
    def _find(names: list[tuple[str, int]]) -> tuple[Path, int] | None:
        for directory in _FONT_DIRS:
            for name, index in names:
                path = directory / name
                if path.exists():
                    return path, index
        return None

    def get(self, size: int, bold: bool = False):
        key = (size, bold)
        if key not in self._cache:
            found = self._paths["bold" if bold else "regular"]
            if found is None:
                raise SystemExit("日本語フォントが見つかりません（BIZ UDゴシック、游ゴシック、メイリオなど）")
            path, index = found
            self._cache[key] = self._font.truetype(str(path), size, index=index)
        return self._cache[key]


# ---------------------------------------------------------------- wording


def scene(state: GameState, short: bool = False) -> str:
    bases = sum(1 << i for i, on in enumerate(state.runners) if on)
    half = "表" if state.half == "top" else "裏"
    if short:
        return f"{state.inning}{half} {_OUT_NAMES[state.outs]}{_BASE_NAMES[bases]}"
    return (f"{state.inning}回{half} {_OUT_NAMES[state.outs]}{_BASE_NAMES[bases]}"
            f"（{state.away_score}-{state.home_score}）")


def describe(row: ScoredRow) -> str:
    """The call in a few words, naming who it was about."""

    r = row.row
    if r.call in ("代打", "代打なし"):
        return f"{r.call}（{r.batter}→{r.substitute}）" if r.call == "代打" else f"代打なし（{r.batter}）"
    if r.call in ("継投", "続投"):
        return f"継投（{r.pitcher}→{r.substitute}）" if r.call == "継投" else f"続投（{r.pitcher}）"
    if r.call in ("敬遠", "勝負", "強攻", "送りバント"):
        return f"{r.call}（{r.batter}）" if r.batter else r.call
    return r.call


def long_date(text: str) -> str:
    """``2026-08-30`` as ``2026年8月30日（日）``; anything else unchanged."""

    try:
        day = datetime.date.fromisoformat(text)
    except ValueError:
        return text
    weekday = "月火水木金土日"[day.weekday()]
    return f"{day.year}年{day.month}月{day.day}日（{weekday}）"


def tone(value: float | None) -> str:
    if value is None or abs(value) < 0.5:
        return "even"
    return "pos" if value > 0 else "neg"


def key_decisions(rows: list[ScoredRow], limit: int = KEY_DECISIONS) -> list[ScoredRow]:
    """The calls that moved win probability most, shown in game order."""

    scored = [r for r in rows if r.value is not None and abs(r.value) >= 0.5]
    top = sorted(scored, key=lambda r: -abs(r.value))[:limit]
    return sorted(top, key=lambda r: r.row.number)


def post_text(game: Game, rows: list[ScoredRow]) -> str:
    """The fixed-format post body, kept within X's length limit."""

    date = game.properties.get("日付", "")
    try:
        _, month, day = date.split("-")
        date = f"{int(month)}/{int(day)}"
    except ValueError:
        pass
    result = game.properties.get("結果", f"{game.away} vs {game.home}")
    totals = sorted(team_totals(game, rows), key=lambda t: -t.total)
    lines = [
        f"【采配採点】{date} {result}".strip(),
        "采配点 " + "／".join(f"{t.team} {t.total:+.1f}" for t in totals),
    ]
    keys = key_decisions(rows)
    if keys:
        turning = max(keys, key=lambda r: abs(r.value))
        lines.append(
            f"分かれ目：{scene(turning.row.state)} {turning.team}の{describe(turning)}"
            f" {turning.value:+.1f}pt"
        )
    else:
        lines.append("両軍とも采配で大きな損得はなし")
    lines.append("※結果ではなく判断した時点の勝率で評価")
    lines.append("#采配採点")
    text = "\n".join(lines)
    # Drop the least essential lines until it fits.
    for optional in ("※結果ではなく判断した時点の勝率で評価",):
        if weighted_length(text) <= POST_LIMIT:
            break
        text = text.replace("\n" + optional, "")
    return text


def weighted_length(text: str) -> int:
    """X's weighted length: wide (CJK) characters count 2, others 1."""

    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F", "A") else 1 for c in text)


# ---------------------------------------------------------------- drawing


@dataclass
class Canvas:
    fonts: Fonts
    height: int

    def __post_init__(self) -> None:
        Image, ImageDraw, _ = _pillow()
        self.image = Image.new("RGB", (WIDTH, self.height), COLORS["bg"])
        self.draw = ImageDraw.Draw(self.image)

    def text(self, xy, text, size, color="ink", bold=False, anchor="la"):
        self.draw.text(xy, text, font=self.fonts.get(size, bold), fill=COLORS.get(color, color),
                       anchor=anchor)

    def width_of(self, text, size, bold=False) -> float:
        return self.fonts.get(size, bold).getlength(text)

    def fit(self, text, size, width, bold=False) -> str:
        if self.width_of(text, size, bold) <= width:
            return text
        while text and self.width_of(text + "…", size, bold) > width:
            text = text[:-1]
        return text + "…"

    def wrap(self, text, size, width) -> list[str]:
        """Break by width, never starting a line with closing punctuation."""

        lines, current = [], ""
        for char in text:
            too_wide = self.width_of(current + char, size) > width and current
            if too_wide and char not in "、。，．）」』】)%":
                lines.append(current)
                current = char
            else:
                current += char
        if current:
            lines.append(current)
        return lines

    def box(self, xy, fill, radius=16, outline=None):
        self.draw.rounded_rectangle(xy, radius=radius, fill=COLORS.get(fill, fill),
                                    outline=COLORS.get(outline, outline) if outline else None,
                                    width=2 if outline else 0)


HEADER_H = 176
TEAM_CARD_H = 150


@dataclass(frozen=True)
class Layout:
    keys: int
    key_h: int
    row_h: int


#: Tried in order until one fits on a single image.
LAYOUTS = (
    Layout(keys=3, key_h=156, row_h=44),
    Layout(keys=3, key_h=132, row_h=38),
    Layout(keys=2, key_h=132, row_h=38),
    Layout(keys=2, key_h=132, row_h=34),
    Layout(keys=1, key_h=132, row_h=34),
)


def _footer_lines(canvas: Canvas) -> list[tuple[str, int, str]]:
    notes = (
        "点数は判断ごとに「選んだ采配」と「代わりにあり得た采配」の勝率を比べた差の合計（+1.0pt＝勝つ確率を1%上げた）。"
        "結果ではなく、判断した時点の状況で評価。±0.5pt未満は互角。"
        "得点の起こりやすさはMLB（Retrosheet 2022〜24）から推定。選手の成績を入れていない場面は平均的な選手として計算。"
    )
    attribution = ("The information used here was obtained free of charge from and is copyrighted by "
                   "Retrosheet. Interested parties may contact Retrosheet at \"www.retrosheet.org\".")
    width = WIDTH - 2 * MARGIN
    lines = [(line, 21, "muted") for line in canvas.wrap(notes, 21, width)]
    lines += [(line, 17, "muted") for line in canvas.wrap(attribution, 17, width)]
    return lines


def _draw_header(c: Canvas, game: Game, page: int, pages: int) -> int:
    c.draw.rectangle((0, 0, WIDTH, HEADER_H), fill=COLORS["header"])
    c.text((MARGIN, 34), "采配採点", 26, "#9FD3B9", bold=True)
    right = long_date(game.properties.get("日付", ""))
    if pages > 1:
        right += f"　{page}/{pages}"
    c.text((WIDTH - MARGIN, 34), right, 26, "header_muted", anchor="ra")
    c.text((MARGIN, 74), c.fit(f"{game.away} vs {game.home}", 52, WIDTH - 2 * MARGIN, True),
           52, "header_ink", bold=True)
    subtitle = " ".join(v for v in (game.properties.get("結果", ""), game.properties.get("球場", "")) if v)
    c.text((MARGIN, 138), c.fit(subtitle, 26, WIDTH - 2 * MARGIN), 26, "header_muted")
    return HEADER_H


def _draw_teams(c: Canvas, game: Game, rows: list[ScoredRow], y: int) -> int:
    y += 36
    c.text((MARGIN, y), "采配点", 30, bold=True)
    c.text((MARGIN + 110, y + 6), "判断ごとの勝率差の合計", 22, "muted")
    y += 52
    totals = team_totals(game, rows)
    gap = 24
    card_w = (WIDTH - 2 * MARGIN - gap) // 2
    best = max(t.total for t in totals) if totals else 0
    for i, t in enumerate(totals):
        x = MARGIN + i * (card_w + gap)
        leading = t.total == best and len([s for s in totals if s.total == best]) == 1
        c.box((x, y, x + card_w, y + TEAM_CARD_H), "surface", outline="ink" if leading else "line")
        c.text((x + 28, y + 20), c.fit(t.team, 30, card_w - 56, True), 30, bold=True)
        score_tone = tone(t.total) if t.scored else "even"
        score = f"{t.total:+.1f}"
        c.text((x + 28, y + 54), score, 60, score_tone, bold=True)
        c.text((x + 28 + c.width_of(score, 60, True) + 6, y + 82), "pt", 26, score_tone, bold=True)
        counts = f"判断{len(t.scored)}　好判断{t.count('好判断')}・互角{t.count('互角')}・疑問{t.count('疑問')}"
        c.text((x + card_w - 28, y + 20), counts, 21, "muted", anchor="ra")
    return y + TEAM_CARD_H


def _pill(c: Canvas, x_right: int, y: int, label: str, kind: str) -> None:
    w = c.width_of(label, 22, True) + 28
    c.box((x_right - w, y, x_right, y + 38), f"{kind}_soft", radius=19)
    c.text((x_right - w / 2, y + 19), label, 22, kind, bold=True, anchor="mm")


def _draw_keys(c: Canvas, keys: list[ScoredRow], y: int, key_h: int) -> int:
    y += 40
    c.text((MARGIN, y), "分かれ目になった判断", 30, bold=True)
    y += 52
    if not keys:
        c.box((MARGIN, y, WIDTH - MARGIN, y + 90), "surface", outline="line")
        c.text((MARGIN + 28, y + 45), "両軍とも采配で大きな損得はありませんでした（すべて±0.5pt未満）",
               24, "muted", anchor="lm")
        return y + 90
    compact = key_h < 150
    for r in keys:
        kind = tone(r.value)
        inner = key_h - 16
        c.box((MARGIN, y, WIDTH - MARGIN, y + inner), "surface", outline="line")
        c.draw.rectangle((MARGIN, y + 14, MARGIN + 8, y + inner - 14), fill=COLORS[kind])
        left = MARGIN + 32
        value_text = f"{r.value:+.1f}pt"
        value_w = c.width_of(value_text, 46, True)
        text_w = WIDTH - MARGIN - 32 - value_w - 40 - left
        top = 14 if compact else 22
        step = 30 if compact else 34
        gap = 38 if compact else 44
        c.text((left, y + top), f"#{r.row.number}　{scene(r.row.state)}", 22, "muted")
        c.text((left, y + top + step), c.fit(f"{r.team}　{describe(r)}", 30, text_w, True), 30, bold=True)
        compare = (f"{r.chosen_label} {r.chosen_probability:.1%}　／　"
                   f"{r.alternative_label}なら {r.alternative_probability:.1%}")
        c.text((left, y + top + step + gap), c.fit(compare, 23, text_w), 23, "muted")
        c.text((WIDTH - MARGIN - 32, y + top + 4), value_text, 46, kind, bold=True, anchor="ra")
        _pill(c, WIDTH - MARGIN - 32, y + inner - 52, r.verdict, kind)
        y += key_h
    return y - 16


def _draw_list(c: Canvas, rows: list[ScoredRow], y: int, title: str, row_h: int) -> int:
    y += 40
    c.text((MARGIN, y), title, 30, bold=True)
    y += 52
    scale = max([abs(r.value) for r in rows if r.value is not None] + [5.0])
    col_scene, col_call = MARGIN + 8, MARGIN + 250
    bar_left, bar_right = MARGIN + 610, WIDTH - MARGIN - 110
    zero = (bar_left + bar_right) / 2
    half = (bar_right - bar_left) / 2
    c.box((MARGIN, y, WIDTH - MARGIN, y + row_h * len(rows) + 16), "surface", outline="line")
    y += 8
    for i, r in enumerate(rows):
        mid = y + row_h / 2
        if i:
            c.draw.line((MARGIN + 16, y, WIDTH - MARGIN - 16, y), fill=COLORS["line"], width=1)
        c.text((col_scene + 12, mid), scene(r.row.state, short=True), 22, "muted", anchor="lm")
        c.text((col_call, mid), c.fit(f"{r.team} {describe(r)}", 22, bar_left - col_call - 16),
               22, anchor="lm")
        c.draw.line((zero, y + 8, zero, y + row_h - 8), fill=COLORS["line"], width=2)
        if r.value is None:
            c.text((zero, mid), "対象外", 20, "muted", anchor="mm")
            continue
        kind = tone(r.value)
        length = max(abs(r.value) / scale * half, 3)
        x0, x1 = (zero, zero + length) if r.value >= 0 else (zero - length, zero)
        c.draw.rounded_rectangle((x0, mid - 9, x1, mid + 9), radius=4, fill=COLORS[kind])
        c.text((WIDTH - MARGIN - 20, mid), f"{r.value:+.1f}", 24, kind, bold=True, anchor="rm")
        y += row_h
    return y + 8


def _draw_footer(c: Canvas, y: int) -> None:
    y += 32
    for line, size, color in _footer_lines(c):
        c.text((MARGIN, y), line, size, color)
        y += size + 9


def _heights(fonts: Fonts, rows: list[ScoredRow], layout: Layout) -> dict[str, int]:
    probe = Canvas(fonts, 10)
    keys = key_decisions(rows, layout.keys)
    return {
        "header": HEADER_H,
        "teams": 36 + 52 + TEAM_CARD_H,
        "keys": 92 + (len(keys) * layout.key_h - 16 if keys else 90),
        "list": 92 + layout.row_h * len(rows) + 16,
        "footer": 32 + sum(size + 9 for _, size, _ in _footer_lines(probe)) + 40,
    }


def render_cards(game: Game, rows: list[ScoredRow]) -> list:
    """One image when possible; two only when the decision list cannot fit."""

    fonts = Fonts()
    for layout in LAYOUTS:
        h = _heights(fonts, rows, layout)
        if sum(h.values()) <= MAX_HEIGHT:
            c = Canvas(fonts, sum(h.values()))
            y = _draw_header(c, game, 1, 1)
            y = _draw_teams(c, game, rows, y)
            y = _draw_keys(c, key_decisions(rows, layout.keys), y, layout.key_h)
            y = _draw_list(c, rows, y, f"全判断（{len(rows)}）", layout.row_h)
            _draw_footer(c, y)
            return [c.image]

    layout = LAYOUTS[0]
    h = _heights(fonts, rows, layout)
    one = Canvas(fonts, h["header"] + h["teams"] + h["keys"] + h["footer"])
    y = _draw_header(one, game, 1, 2)
    y = _draw_teams(one, game, rows, y)
    y = _draw_keys(one, key_decisions(rows, layout.keys), y, layout.key_h)
    _draw_footer(one, y)
    two = Canvas(fonts, h["header"] + h["list"] + h["footer"])
    y = _draw_header(two, game, 2, 2)
    y = _draw_list(two, rows, y, f"全判断（{len(rows)}）", layout.row_h)
    _draw_footer(two, y)
    return [one.image, two.image]


def write_post(path: Path, game: Game, rows: list[ScoredRow]) -> tuple[list[Path], str]:
    """Write ``<note>_1.png`` (``_2.png``) and ``<note>_投稿文.txt`` next to a note."""

    images = render_cards(game, rows)
    for old in path.parent.glob(f"{path.stem}_[0-9].png"):
        old.unlink()
    written = []
    for i, image in enumerate(images, start=1):
        out = path.with_name(f"{path.stem}_{i}.png")
        image.save(out, optimize=True)
        written.append(out)
    text = post_text(game, rows)
    path.with_name(f"{path.stem}_投稿文.txt").write_text(text + "\n", encoding="utf-8")
    return written, text


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m saikaku.card <試合ノート.md>")
    path = Path(sys.argv[1])
    events = EventTable.load()
    try:
        game = parse_game(path.read_text(encoding="utf-8"), events)
    except GameFormatError as error:
        raise SystemExit(f"{path.name}: {error}") from None
    rows = score_game(game, WinProbabilityModel.load_default(), TacticTable.load(), events)
    images, text = write_post(path, game, rows)
    for image in images:
        print(f"-> {image}")
    print(f"投稿文（{weighted_length(text)}/{POST_LIMIT}）:")
    print(text)


if __name__ == "__main__":
    main()
