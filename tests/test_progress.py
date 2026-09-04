from app.bot.progress import format_progress_text


def test_progress_text_contains_elapsed_and_interval() -> None:
    text = format_progress_text("🔎 جاري البحث عن القضية المناسبة…", 12, 3)
    assert "جاري البحث عن القضية المناسبة" in text
    assert "12 ثانية" in text
    assert "كل 3 ثوانٍ" in text


def test_progress_text_clamps_negative_elapsed() -> None:
    text = format_progress_text("مرحلة", -5, 3)
    assert "0 ثانية" in text
