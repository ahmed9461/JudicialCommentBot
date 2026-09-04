from dataclasses import dataclass

from app.ranking import select_candidates


@dataclass
class Item:
    final_score: int


def test_auto_selection_requires_threshold_and_margin() -> None:
    decision = select_candidates([Item(94), Item(86)], auto_accept_score=90, display_count=3, min_margin=5, require_margin=True)
    assert decision.is_auto
    assert decision.selected_index == 0


def test_close_scores_fall_back_to_manual_top_three() -> None:
    decision = select_candidates([Item(94), Item(92), Item(88), Item(80)], auto_accept_score=90, display_count=3, min_margin=5, require_margin=True)
    assert decision.mode == "manual"
    assert decision.visible_count == 3
