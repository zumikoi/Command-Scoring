"""Post-game report formatting for X and longer-form dashboards."""

from __future__ import annotations

from collections.abc import Iterable

from .decisions import ScoredDecision


def format_post(scored: ScoredDecision) -> str:
    item = scored.decision
    sign = "+" if scored.decision_cost >= 0 else ""
    return (
        f"{item.team} {item.game_id}｜{item.decision_type}「{item.description}」\n"
        f"勝率変化 {scored.observed_change:+.2f}pt｜"
        f"代替案「{item.best_alternative}」との差 {sign}{scored.decision_cost:.2f}pt\n"
        f"判定 {scored.grade}｜結果ではなく、意思決定時点の情報だけで評価"
    )


def format_game_summary(items: Iterable[ScoredDecision]) -> str:
    scored = list(items)
    if not scored:
        return "采配評価対象なし"
    total = sum(item.decision_cost for item in scored)
    return f"采配評価 {len(scored)}件｜累積推定差 {total:+.2f}pt"
