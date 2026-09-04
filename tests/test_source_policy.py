from app.sources import SourceRegistry


def test_official_and_discovery_sources_are_classified() -> None:
    registry = SourceRegistry()

    moj = registry.classify("https://www.moj.gov.sa/example.pdf")
    assert moj.is_official is True
    assert moj.source_id == "ministry_of_justice"

    tashree = registry.classify("https://tashree.app/judgments/123")
    assert tashree.is_discovery_only is True
    assert tashree.source_id == "tashree"

    unknown = registry.classify("https://example.com/case")
    assert unknown.source_id is None
    assert unknown.is_discovery_only is True


def test_http_is_rejected_by_https_policy() -> None:
    registry = SourceRegistry()
    assert registry.is_https_allowed("http://www.moj.gov.sa/example.pdf") is False
    assert registry.is_https_allowed("https://www.moj.gov.sa/example.pdf") is True
