from dataclasses import dataclass

from app.knowledge import SubjectLoader
from app.ranking import assess_subject_relevance, select_candidates


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


def test_research_methods_accepts_structured_judgment_without_fake_topic_keyword() -> None:
    subject = SubjectLoader().get_subject("research_methods")
    assert subject.relevance_mode == "methodological"
    text = (
        "رقم القضية 35159749 المحكمة العامة. أقام المدعي دعواه وذكر في الوقائع طلباته. "
        "وحيث ثبت للمحكمة من المستندات ما جاء في الدعوى، ولما كان ذلك قررت المحكمة "
        "وحكمت بإلزام المدعى عليه وفق ما انتهى إليه التسبيب. " * 30
    )
    assessment = assess_subject_relevance(subject, text)
    assert assessment.accepted is True
    assert assessment.score >= 24


def test_research_methods_rejects_short_unanalyzable_order() -> None:
    subject = SubjectLoader().get_subject("research_methods")
    assessment = assess_subject_relevance(subject, "قررت المحكمة رفض الطلب.")
    assert assessment.accepted is False
