"""Score every decision in one game and total them per team.

    python -m saikaku.game 試合/2026-09-27_A-B.md

A game is an Obsidian note: properties for the date and teams, then tables
for players, head-to-head records and the decisions in order. Each decision is
scored on its own, at the moment it was made, and a team's score for the game
is the sum of its decisions in win-probability points. The report is written
next to the note as ``<note>_採点.md``, together with the X post images and
text from :mod:`saikaku.card` when Pillow is installed; the note itself is
never changed.

Calls not made count too. ``強攻`` (no bunt), ``二盗せず``, ``三盗せず``,
``勝負`` (no intentional walk), ``代打なし`` and ``続投`` are scored as the
opposite of the call they decline.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable, Mapping

from .abilities import (
    AVERAGE,
    BATTER_KEYS,
    HANDS,
    Ability,
    StatLine,
    batter_ability,
    league_rates,
    pitcher_ability,
)
from .decisions import EVEN_MARGIN
from .events import EventTable
from .model import GameState, WinProbabilityModel
from .retrosheet import ATTRIBUTION
from .tactics import (
    DECISION_TYPES,
    TACTIC_NAMES,
    InsufficientData,
    Matchup,
    TacticTable,
    evaluate,
)

#: Declined calls and the call each one declines.
NOT_TAKEN = {
    "強攻": "送りバント",
    "二盗せず": "二盗",
    "三盗せず": "三盗",
    "勝負": "敬遠",
    "代打なし": "代打",
    "続投": "継投",
}

#: A player's stat columns. Pitcher rows read 打席 as batters faced, 安打 as
#: hits allowed and so on; doubles and triples may be left blank.
STAT_COLUMNS = ("打席", "安打", "二塁打", "三塁打", "本塁打", "四球", "死球", "三振")

_BASE_CHARS = {"一": 0, "1": 0, "二": 1, "2": 1, "三": 2, "3": 2}


class GameFormatError(ValueError):
    """Raised when a game note cannot be read."""


@dataclass(frozen=True)
class Player:
    name: str
    batting: bool
    ability: Ability


@dataclass(frozen=True)
class DecisionRow:
    number: int
    state: GameState
    call: str
    batter: str = ""
    next_batters: tuple[str, ...] = ()
    pitcher: str = ""
    substitute: str = ""
    note: str = ""


@dataclass(frozen=True)
class Game:
    properties: dict[str, str]
    #: Keyed by (name, batting): a pitcher who also bats has two rows.
    players: dict[tuple[str, bool], Player]
    head_to_head: dict[tuple[str, str], StatLine]
    decisions: tuple[DecisionRow, ...]
    warnings: tuple[str, ...] = ()

    @property
    def away(self) -> str:
        return self.properties.get("ビジター", "ビジター")

    @property
    def home(self) -> str:
        return self.properties.get("ホーム", "ホーム")


@dataclass(frozen=True)
class ScoredRow:
    row: DecisionRow
    team: str
    #: Points for the deciding team; None when the call could not be scored.
    value: float | None = None
    chosen_label: str = ""
    alternative_label: str = ""
    chosen_probability: float | None = None
    alternative_probability: float | None = None
    problem: str = ""

    @property
    def verdict(self) -> str:
        if self.value is None:
            return "対象外"
        if abs(self.value) < EVEN_MARGIN:
            return "互角"
        return "好判断" if self.value > 0 else "疑問"


@dataclass
class TeamTotal:
    team: str
    rows: list[ScoredRow] = field(default_factory=list)

    @property
    def scored(self) -> list[ScoredRow]:
        return [r for r in self.rows if r.value is not None]

    @property
    def total(self) -> float:
        return sum(r.value for r in self.scored)

    def count(self, verdict: str) -> int:
        return sum(1 for r in self.scored if r.verdict == verdict)


# ---------------------------------------------------------------- reading


def _split_sections(text: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    properties: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    properties[key.strip()] = value.strip().strip('"')
            body = text[end + 4 :]
    sections: dict[str, list[str]] = {}
    current = None
    for line in body.splitlines():
        heading = re.match(r"^#{2,}\s*(.+?)\s*$", line)
        if heading:
            current = heading.group(1)
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return properties, sections


def _table(lines: Iterable[str]) -> list[dict[str, str]]:
    """Rows of the first Markdown table in ``lines``, keyed by header."""

    rows = [line.strip() for line in lines if line.strip().startswith("|")]
    if len(rows) < 2:
        return []

    def cells(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip().strip("|").split("|")]

    header = cells(rows[0])
    result = []
    for line in rows[2:]:
        values = cells(line)
        if not any(values):
            continue
        result.append(dict(zip(header, values + [""] * (len(header) - len(values)))))
    return result


def _int(value: str, what: str) -> int | None:
    value = value.strip()
    if value in ("", "-", "—"):
        return None
    try:
        return int(value)
    except ValueError:
        raise GameFormatError(f"{what} must be a whole number, got {value!r}") from None


def parse_runners(text: str) -> tuple[bool, bool, bool]:
    """Read 走者 such as ``なし``, ``一塁``, ``一三塁``, ``満塁`` or ``1,3``."""

    text = text.strip()
    if text in ("", "なし", "-", "—", "0"):
        return (False, False, False)
    if "満" in text:
        return (True, True, True)
    bases = [False, False, False]
    for char in text:
        if char in _BASE_CHARS:
            bases[_BASE_CHARS[char]] = True
    if not any(bases):
        raise GameFormatError(f"走者 could not be read: {text!r}")
    return tuple(bases)


def _stat_line(row: Mapping[str, str], what: str) -> StatLine | None:
    values = {column: _int(row.get(column, ""), f"{what} {column}") for column in STAT_COLUMNS}
    if all(v is None for v in values.values()):
        return None
    raw = {BATTER_KEYS[key]: values[BATTER_KEYS[key]] for key in
           ("pa", "h", "doubles", "triples", "hr", "bb", "hbp", "so")}
    try:
        return StatLine.from_mapping(raw, BATTER_KEYS)
    except ValueError as error:
        raise GameFormatError(f"{what}: {error}") from None


def parse_game(text: str, events: EventTable) -> Game:
    properties, sections = _split_sections(text)
    warnings: list[str] = []

    league = events.league
    league_rows = _table(sections.get("リーグ平均", []))
    if league_rows:
        line = _stat_line(league_rows[0], "リーグ平均")
        if line is not None:
            league = league_rates(line)

    players: dict[tuple[str, bool], Player] = {}
    for row in _table(sections.get("選手", [])):
        name = row.get("名前", "")
        if not name:
            continue
        kind = row.get("区分", "打")
        batting = not kind.startswith("投")
        profile = row.get("型", "")
        line = _stat_line(row, name)
        if line is not None:
            ability = (batter_ability if batting else pitcher_ability)(line, league, name)
        elif profile:
            try:
                ability = events.profile(profile, batting)
            except KeyError:
                raise GameFormatError(f"{name}: 型「{profile}」は存在しません") from None
        else:
            ability = AVERAGE
        hand = row.get("左右", "")
        if hand:
            if hand not in HANDS or (not batting and hand == "両"):
                raise GameFormatError(f"{name}: 左右は 右・左{'・両' if batting else ''} で書いてください")
            ability = replace(ability, hand=HANDS[hand])
        players[(name, batting)] = Player(name, batting, replace(ability, label=name))

    head_to_head: dict[tuple[str, str], StatLine] = {}
    for row in _table(sections.get("対戦成績", [])):
        batter, pitcher = row.get("打者", ""), row.get("投手", "")
        line = _stat_line(row, f"対戦成績 {batter}×{pitcher}")
        if batter and pitcher and line is not None:
            head_to_head[(batter, pitcher)] = line

    decisions = []
    for index, row in enumerate(_table(sections.get("采配", [])), start=1):
        number = _int(row.get("#", ""), "#") or index
        call = row.get("采配", "")
        if call not in DECISION_TYPES and call not in NOT_TAKEN:
            raise GameFormatError(
                f"#{number}: 采配「{call}」は {'・'.join([*DECISION_TYPES, *NOT_TAKEN])} のどれかで書いてください"
            )
        half = {"表": "top", "裏": "bottom"}.get(row.get("表裏", ""))
        if half is None:
            raise GameFormatError(f"#{number}: 表裏は「表」か「裏」で書いてください")
        score = re.match(r"^\s*(\d+)\s*[-－–]\s*(\d+)\s*$", row.get("得点", ""))
        if not score:
            raise GameFormatError(f"#{number}: 得点は「ビジター-ホーム」の形（例 3-2）で書いてください")
        try:
            state = GameState(
                inning=_int(row.get("回", ""), f"#{number} 回") or 0,
                half=half,
                outs=_int(row.get("アウト", ""), f"#{number} アウト") or 0,
                away_score=int(score.group(1)),
                home_score=int(score.group(2)),
                runners=parse_runners(row.get("走者", "")),
            )
        except ValueError as error:
            raise GameFormatError(f"#{number}: {error}") from None
        names = [row.get("次の打者", ""), row.get("その次", "")]
        decisions.append(
            DecisionRow(
                number=number,
                state=state,
                call=call,
                batter=row.get("打者", ""),
                next_batters=tuple(n for n in names if n),
                pitcher=row.get("投手", ""),
                substitute=row.get("代わり", ""),
                note=row.get("メモ", ""),
            )
        )
        substitute_bats = call in ("代打", "代打なし")
        roles = [(row.get("打者", ""), True), *((n, True) for n in names),
                 (row.get("投手", ""), False), (row.get("代わり", ""), substitute_bats)]
        for name, batting in roles:
            if name and (name, batting) not in players and name not in _profile_labels(events):
                role = "打者" if batting else "投手"
                warnings.append(f"#{number}: 「{name}」の{role}としての行が選手表にないのでリーグ平均として扱いました")

    return Game(properties, players, head_to_head, tuple(decisions), tuple(dict.fromkeys(warnings)))


def _profile_labels(events: EventTable) -> set[str]:
    return {a.label for a in (*events.batter_profiles, *events.pitcher_profiles)} | {AVERAGE.label}


# ---------------------------------------------------------------- scoring


def _resolve(name: str, batting: bool, game: Game, events: EventTable) -> Ability:
    if not name:
        return AVERAGE
    if (name, batting) in game.players:
        return game.players[(name, batting)].ability
    try:
        return events.profile(name, batting)
    except KeyError:
        return AVERAGE


def score_game(
    game: Game, model: WinProbabilityModel, table: TacticTable, events: EventTable
) -> list[ScoredRow]:
    results = []
    for row in game.decisions:
        declined = row.call in NOT_TAKEN
        decision_type = NOT_TAKEN.get(row.call, row.call)
        kind = DECISION_TYPES[decision_type]
        offense_team = game.away if row.state.half == "top" else game.home
        defense_team = game.home if row.state.half == "top" else game.away
        team = offense_team if kind.by_offense else defense_team

        # One Ability object per name, so head-to-head records match by identity.
        cache: dict[tuple[str, bool], Ability] = {}

        def ability(name: str, batting: bool) -> Ability:
            key = (name, batting)
            if key not in cache:
                cache[key] = _resolve(name, batting, game, events)
            return cache[key]

        batter = ability(row.batter, True)
        lineup = (batter, *(ability(n, True) for n in row.next_batters))
        pitcher = ability(row.pitcher, False)
        pinch = ability(row.substitute, True) if decision_type == "代打" else None
        reliever = ability(row.substitute, False) if decision_type == "継投" else None
        pairs = [(row.batter, row.pitcher, batter, pitcher)]
        if pinch is not None:
            pairs.append((row.substitute, row.pitcher, pinch, pitcher))
        if reliever is not None:
            pairs.append((row.batter, row.substitute, batter, reliever))
        records = tuple(
            (b, p, game.head_to_head[(bn, pn)])
            for bn, pn, b, p in pairs
            if (bn, pn) in game.head_to_head
        )
        matchup = Matchup(lineup, pitcher, pinch, reliever, records)

        if decision_type in ("代打", "継投") and not row.substitute:
            results.append(ScoredRow(row, team, problem="「代わり」に交代要員の名前が必要です"))
            continue
        try:
            ev = evaluate(decision_type, row.state, model, table, events, matchup)
        except (InsufficientData, ValueError) as error:
            results.append(ScoredRow(row, team, problem=_explain(error)))
            continue

        chosen, alternative = TACTIC_NAMES[ev.chosen], TACTIC_NAMES[ev.alternative]
        if decision_type == "代打":
            chosen, alternative = f"代打 {row.substitute}", f"{row.batter or '打者'}のまま"
        if decision_type == "継投":
            chosen, alternative = f"継投 {row.substitute}", f"{row.pitcher or '投手'}続投"
        if declined:
            if decision_type not in ("代打", "継投"):
                alternative = row.call
            results.append(ScoredRow(
                row, team, -ev.value, alternative, chosen,
                ev.alternative_probability, ev.chosen_probability,
            ))
        else:
            results.append(ScoredRow(
                row, team, ev.value, chosen, alternative,
                ev.chosen_probability, ev.alternative_probability,
            ))
    return results


def _explain(error: Exception) -> str:
    if isinstance(error, InsufficientData):
        return "この場面での実例が少なく推定できません"
    return f"この場面では選べない采配です（{error}）"


def team_totals(game: Game, rows: list[ScoredRow]) -> list[TeamTotal]:
    totals = {game.away: TeamTotal(game.away), game.home: TeamTotal(game.home)}
    for row in rows:
        totals.setdefault(row.team, TeamTotal(row.team)).rows.append(row)
    return list(totals.values())


# ---------------------------------------------------------------- report

_BASE_NAMES = ["走者なし", "一塁", "二塁", "一二塁", "三塁", "一三塁", "二三塁", "満塁"]
_OUT_NAMES = ["無死", "一死", "二死"]


def _scene(state: GameState) -> str:
    bases = sum(1 << i for i, on in enumerate(state.runners) if on)
    half = "表" if state.half == "top" else "裏"
    return (f"{state.inning}回{half} {_OUT_NAMES[state.outs]}{_BASE_NAMES[bases]}"
            f" {state.away_score}-{state.home_score}")


def render_report(
    game: Game,
    rows: list[ScoredRow],
    source_name: str,
    post_images: list[str] = (),
    post: str = "",
) -> str:
    date = game.properties.get("日付", "")
    title = f"{date} {game.away} vs {game.home}".strip()
    lines = [
        "---",
        f"試合: \"[[{source_name}]]\"",
        "種類: 采配採点",
        "---",
        "",
        f"# 采配採点：{title}",
        "",
        "点数は、判断ごとに「選んだ采配」と「代わりにあり得た采配」の勝率を比べた差（pt）の合計です。"
        "+1.0pt は、その采配で勝つ確率を1%上げたという意味です。結果がどうなったかは点数に入れていません。",
        "",
    ]
    if post_images or post:
        lines += ["## 投稿用", ""]
        lines += [f"![[{name}]]" for name in post_images]
        if post:
            lines += ["", "```", post, "```"]
        lines += [""]
    lines += [
        "## 総合",
        "",
        "| チーム | 点数 | 判断数 | 好判断 | 互角 | 疑問 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    totals = team_totals(game, rows)
    for t in totals:
        lines.append(
            f"| {t.team} | **{t.total:+.1f}pt** | {len(t.scored)} | {t.count('好判断')} "
            f"| {t.count('互角')} | {t.count('疑問')} |"
        )

    scored = [r for r in rows if r.value is not None]
    if scored:
        best = max(scored, key=lambda r: r.value)
        worst = min(scored, key=lambda r: r.value)
        lines += ["", "## 目立った判断", ""]
        if best.value >= EVEN_MARGIN:
            lines.append(f"- **最も良かった**：#{best.row.number} {best.team} {best.row.call}"
                         f"（{_scene(best.row.state)}）{best.value:+.1f}pt")
        if worst.value <= -EVEN_MARGIN:
            lines.append(f"- **最も疑問**：#{worst.row.number} {worst.team} {worst.row.call}"
                         f"（{_scene(worst.row.state)}）{worst.value:+.1f}pt。"
                         f"{worst.alternative_label}なら勝率 {worst.alternative_probability:.1%}"
                         f"（実際の選択は {worst.chosen_probability:.1%}）")
        if best.value < EVEN_MARGIN and worst.value > -EVEN_MARGIN:
            lines.append("- どの判断も差は小さく、采配で大きく損得した場面はありませんでした")

    lines += [
        "",
        "## 判断ごと",
        "",
        "| # | 場面 | チーム | 采配 | 選んだ方 | 代わりの選択 | 差 | 判定 | メモ |",
        "| ---: | --- | --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for r in rows:
        if r.value is None:
            lines.append(f"| {r.row.number} | {_scene(r.row.state)} | {r.team} | {r.row.call} "
                         f"| — | — | — | 対象外：{r.problem} | {r.row.note} |")
            continue
        lines.append(
            f"| {r.row.number} | {_scene(r.row.state)} | {r.team} | {r.row.call} "
            f"| {r.chosen_label} {r.chosen_probability:.1%} "
            f"| {r.alternative_label} {r.alternative_probability:.1%} "
            f"| {r.value:+.1f} | {r.verdict} | {r.row.note} |"
        )

    if game.warnings:
        lines += ["", "## 確認してほしいこと", ""] + [f"- {w}" for w in game.warnings]

    lines += [
        "",
        "## 前提",
        "",
        "- 勝率は両チームを平均的な戦力とし、打席の打者から3人目まではこの試合で指定した打者・投手・左右・対戦成績で計算しています",
        "- 得点の起こりやすさはMLB 2022〜2024年（Retrosheet）から推定しており、NPBの得点環境との差は補正していません",
        f"- 「互角」は差が±{EVEN_MARGIN}pt未満のもの（表示上の区切りで、統計的な基準ではありません）",
        f"- {ATTRIBUTION}",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m saikaku.game <試合ノート.md>")
    path = Path(sys.argv[1])
    events = EventTable.load()
    try:
        game = parse_game(path.read_text(encoding="utf-8"), events)
    except GameFormatError as error:
        raise SystemExit(f"{path.name}: {error}") from None
    rows = score_game(game, WinProbabilityModel.load_default(), TacticTable.load(), events)
    images, post = [], ""
    try:
        from .card import write_post
    except ImportError:
        pass
    else:
        try:
            images, post = write_post(path, game, rows)
        except SystemExit as error:  # Pillow or a font is missing: report only
            print(f"投稿用の画像は作れませんでした: {error}")
    out = path.with_name(f"{path.stem}_採点.md")
    out.write_text(
        render_report(game, rows, path.stem, [p.name for p in images], post), encoding="utf-8"
    )
    for t in team_totals(game, rows):
        print(f"{t.team}: {t.total:+.1f}pt（{len(t.scored)}判断）")
    for warning in game.warnings:
        print(f"注意: {warning}")
    for image in images:
        print(f"-> {image}")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
