"""Build research prompts from editable subject knowledge."""

from app.knowledge import SubjectProfile


def build_search_input(subject: SubjectProfile, excluded_cases: list[dict[str, str | None]], limit: int) -> str:
    excluded = "لا توجد قضايا مستبعدة حتى الآن."
    if excluded_cases:
        excluded = "\n".join(
            f"- رقم القضية: {item.get('case_number') or 'غير متوفر'} | المحكمة: {item.get('court_name') or 'غير متوفرة'} | الرابط: {item.get('source_url') or 'غير متوفر'}"
            for item in excluded_cases[:80]
        )
    return f"""المقرر: {subject.name_ar}

الموضوعات ذات الأولوية:
{_bullets(subject.priority_topics)}

أنماط القضايا المناسبة:
{_bullets(subject.suitable_case_patterns)}

أنماط يجب تجنبها:
{_bullets(subject.avoid_case_patterns)}

كلمات بحث مقترحة:
{_bullets(subject.search_keywords)}

محاور التعليق:
{_bullets(subject.commentary_focus)}

القضايا المستخدمة أو المستبعدة:
{excluded}

ابحث عن أحكام قضائية سعودية حقيقية، وفضّل وزارة العدل وديوان المظالم واللجان الرسمية. يمكن استخدام Tashree للاكتشاف فقط ثم ابحث عن المصدر الرسمي.
أعد حتى {limit} مرشحين مختلفين. حاول تقديم رابط PDF الرسمي المباشر. إذا كان الحكم داخل مجموعة PDF رسمية كبيرة وحددت صفحات القضية بثقة، أعد pdf_page_start وpdf_page_end كأرقام صفحات الملف الفعلية، وإلا اجعلهما null.
قيّم كل قضية بهذه الحدود: subject_relevance من 40، legal_issue_clarity من 20، reasoning_quality من 15، academic_commentary_value من 15، ثم estimated_score من 100 كتقدير أولي. لا تمنح نقاط جودة المصدر؛ النظام يحسبها بعد تنزيل PDF.
لا تختلق رقماً أو محكمة أو رابطاً أو صفحات. المعلومة غير المتحققة تكون null.
"""


def _bullets(items: tuple[str, ...]) -> str:
    return "\n".join(f"- {item}" for item in items) or "- لا يوجد"
