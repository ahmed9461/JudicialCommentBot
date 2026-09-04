"""Mixed automatic/manual selection policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class RankedCase(Protocol):
    final_score: int


@dataclass(frozen=True, slots=True)
class SelectionDecision:
    mode: str
    selected_index: int | None
    visible_count: int

    @property
    def is_auto(self) -> bool:
        return self.mode == "auto"


def select_candidates(
    ranked: list[RankedCase],
    *,
    auto_accept_score: int,
    display_count: int,
    min_margin: int,
    require_margin: bool,
) -> SelectionDecision:
    if not ranked:
        return SelectionDecision(mode="none", selected_index=None, visible_count=0)

    top = ranked[0].final_score
    second = ranked[1].final_score if len(ranked) > 1 else None
    margin_ok = second is None or top - second >= min_margin
    if top >= auto_accept_score and (margin_ok or not require_margin):
        return SelectionDecision(mode="auto", selected_index=0, visible_count=1)

    return SelectionDecision(
        mode="manual",
        selected_index=None,
        visible_count=min(max(display_count, 1), len(ranked)),
    )
