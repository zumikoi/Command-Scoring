"""Plain-text formatting of scored decisions."""

from __future__ import annotations

from collections.abc import Iterable

from .decisions import ScoredDecision
from .tactics import TACTIC_NAMES


def format_decision(scored: ScoredDecision) -> str:
    item = scored.decision
    ev = scored.evaluation
    lines = [
        f"{item.team} {item.game_id}｜{item.decision_type}「{item.description}」",
        *_players(scored),
        f"判断: {TACTIC_NAMES[ev.chosen]} {ev.chosen_probability:.1%} vs "
        f"{TACTIC_NAMES[ev.alternative]} {ev.alternative_probability:.1%} "
        f"→ {ev.value:+.1f}pt（{scored.verdict}）",
    ]
    if scored.result_change is not None:
        lines.append(f"結果: 勝率 {scored.result_change:+.1f}pt（評価には使わない）")
    return "\n".join(lines)


def _players(scored: ScoredDecision) -> list[str]:
    m = scored.decision.matchup
    parts = []
    if m.lineup:
        parts.append("打者 " + " → ".join(a.label for a in m.lineup))
    if not m.pitcher.is_average:
        parts.append(f"投手 {m.pitcher.label}")
    if m.pinch_hitter is not None:
        parts.append(f"代打 {m.pinch_hitter.label}")
    if m.reliever is not None:
        parts.append(f"継投 {m.reliever.label}")
    return ["／".join(parts)] if parts else []


def format_game_summary(items: Iterable[ScoredDecision]) -> str:
    scored = list(items)
    if not scored:
        return "采配評価対象なし"
    total = sum(item.evaluation.value for item in scored)
    return f"采配評価 {len(scored)}件｜判断による勝率の増減 合計 {total:+.1f}pt"
