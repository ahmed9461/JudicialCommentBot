from app.knowledge import SubjectLoader


def test_all_subject_files_load() -> None:
    loader = SubjectLoader()
    loader.validate_all()
    subjects = loader.list_subjects()

    assert len(subjects) == 34
    assert subjects[0].slug == "law_intro"
    assert subjects[0].name_ar == "المدخل لدراسة علم القانون"


def test_law_intro_has_expected_search_map() -> None:
    profile = SubjectLoader().get_subject("law_intro")

    assert "استعمال الحق والتعسف في استعماله" in profile.priority_topics
    assert "التعسف في استعمال الحق" in profile.search_keywords
    assert profile.suitable_case_patterns
