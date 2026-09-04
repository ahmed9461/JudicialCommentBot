"""Build research prompts from editable subject knowledge."""

from app.knowledge import SubjectProfile


def build_search_input(
    subject: SubjectProfile,
    excluded_cases: list[dict[str, str | None]],
    limit: int,
) -> str:
    excluded = "لا توجد قضايا مستبعدة حتى الآن."
    if excluded_cases:
        rows = []
        for item in excluded_cases[:50]:
            rows.append(
                f"- رقم القضية: {item.get('case_number') or 'غير متوفر'} | "
                f"المحكمة: {item.get('court_name') or 'غير متوفرة'} | "
                f"الرابط: {item.get('source_url') or 'غير متوفر'}"
            )
        excluded = "\n".join(rows)

    return f"""المقرر: {subject.name_ar}

الموضوعات ذات الأولوية:
{_bullets(subject.priority_topics)}

أنماط القضايا المناسبة:
{_bullets(subject.suitable_case_patterns)}

أنماط يجب تجنبها:
{_bullets(subject.avoid_case_patterns)}

كلمات بحث مقترحة:
{_bullets(subject.search_keywords)}

محاور التعليق التي يجب أن تسمح بها القضية:
{_bullets(subject.commentary_focus)}

القضايا المستخدمة أو المستبعدة التي يجب عدم اقتراحها مرة أخرى:
{excluded}

ابحث في الويب عن أحكام قضائية سعودية حقيقية. فضّل المصادر الرسمية لوزارة العدل وديوان المظالم واللجان القضائية وشبه القضائية الرسمية، ويمكن استخدام Tashree للاكتشاف ثم محاولة الوصول للمصدر الأصلي.
أعد حتى {limit} مرشحين مختلفين. لا تختلق رقم قضية أو محكمة أو رابطاً. إذا لم تجد معلومة اترك الحقل null. لا تدّع أن PDF أصلي صالح قبل أن تتحقق منه طبقة التنزيل البرمجية.
"""


def _bullets(items: tuple[str, ...]) -> str:
    return "\n".join(f"- {item}" for item in items) or "- لا يوجد"
