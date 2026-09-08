from pathlib import Path

from app.catalog.manifest import CatalogManifestLoader
from app.pdf.compilation import extract_judgment_metadata
from app.pdf.headers import primary_judicial_header


def test_moj_legacy_header_is_a_primary_case_boundary() -> None:
    text = """
    جنايات - حرق وإتلاف ملك الغير
    رقم الصك: ٣٤١٨٨٧٦٧
    تاريخه: ١٥/٤/١٤٣٥هـ
    رقم الدعوى: ١٩٩٠/١٤٣٤هـ
    رقم قرار التصديق من محكمة الاستئناف: ٧٤٠٦/٠٥/١٤٣٥هـ
    الموضوعات
    حرق - إتلاف ملك الغير - ثبوت إدانة.
    السند الشرعي أو النظامي
    ما أشار له القاضي في تسبيب الحكم.
    ملخص القضية
    جرى توجيه الاتهام إلى المدعى عليه.
    """
    header = primary_judicial_header(text)
    assert header is not None
    assert header.case_number == "1990/1434"
    assert header.source == "case-legacy"


def test_board_of_grievances_header_uses_administrative_case_number() -> None:
    text = """
    رقم القضية في المحكمة الإدارية ١/ق/٩٢٢١ لعام ١٤٣٧هـ
    رقم القضية في محكمة الاستئناف الإدارية ٤١٦٠/ق لعام ١٤٣٨هـ
    تاريخ الجلسة ٣/٢/١٤٣٨هـ
    الموضوعات
    ملكية فكرية - قرار إداري - مشروعية.
    مستند الحكم
    نظام ديوان المظالم ونظام المرافعات أمامه.
    الأسباب
    بما أن المدعي يطلب إلغاء القرار الإداري...
    """
    header = primary_judicial_header(text)
    assert header is not None
    assert header.case_number == "1/ق/9221"
    assert header.source == "case-bog"
    metadata = extract_judgment_metadata(text, require_primary_header=True)
    assert metadata.case_number == "1/ق/9221"
    assert metadata.judgment_year == "1437"


def test_crsd_header_uses_case_number_not_decision_number() -> None:
    text = """
    لجنة الفصل في منازعات الأوراق المالية
    Committee for Resolution of Securities Disputes
    رقم القضية لدى لجنة الفصل
    45/10
    رقم قرار لجنة الفصل
    4812/ل/د/2023م لعام 1445هـ
    تاريخ صدور القرار 1445/4/30هـ
    نوع الدعوى مدنية
    التصنيف اكتتاب
    الوقائع
    تقدمت الشركة المدعية بصحيفة دعوى...
    """
    header = primary_judicial_header(text)
    assert header is not None
    assert header.case_number == "45/10"
    assert header.source == "case-crsd"


def test_idc_header_uses_insurance_lawsuit_number() -> None:
    text = """
    بسم الله الرحمن الرحيم
    لجان الفصل في المنازعات والمخالفات التأمينية
    قرار اللجنة الابتدائية بالدمام
    رقم الدعوى
    ٣٧٠٨٤١
    رقم القرار الابتدائي
    هـ/٢٠٤/١٤٣٧
    تاريخ صدور القرار الابتدائي
    الأحد ٠٣/٠٧/١٤٣٧ هـ
    نوع الوثيقة
    المسؤولية تجاه الغير
    التصنيف الموضوعي
    دية شرعية
    الوقائع
    تقدم وكيل المدعين بلائحة دعوى ضد شركة التأمين.
    """
    header = primary_judicial_header(text)
    assert header is not None
    assert header.case_number == "370841"
    assert header.source == "case-idc"
    metadata = extract_judgment_metadata(text, require_primary_header=True)
    assert metadata.decision_number is not None


def test_gstc_immediate_publication_header_uses_appeal_identifier() -> None:
    text = """
    الدائرة االستئنافية األولى لمخالفات ومنازعات ضريبة الدخل
    قرار رقم: -2023-136308IR
    الصادر في االستئناف المقيد برقم )-136308-2022Z)
    في الدعوى المقامة من المكلف ضد هيئة الزكاة والضريبة والجمارك
    أسباب القرار
    بعد فحص ملف القضية والمداولة نظاماً...
    منطوق القرار
    قبول الاستئناف شكلاً وإلغاء قرار دائرة الفصل فيما يتعلق بالبند محل النزاع.
    """
    header = primary_judicial_header(text)
    assert header is not None
    assert header.case_number == "136308-2022Z"
    assert header.source == "case-gstc"
    metadata = extract_judgment_metadata(text, require_primary_header=True)
    assert metadata.decision_number == "2023-136308IR"


def test_manifest_separates_navigation_pages_from_judicial_documents(tmp_path: Path) -> None:
    manifest_path = tmp_path / "sources.yaml"
    manifest_path.write_text(
        """
        sources:
          - id: crsd
            source_id: securities_disputes
            source_name: CRSD
            kind: landing_page_crawl
            landing_pages: [https://crsd.gov.sa/ar/ResolutionsCommittee/Decisions/Pages/default.aspx]
            page_path_prefixes: [/ar/ResolutionsCommittee/Decisions/]
            document_path_prefixes: [/ar/ResolutionsCommittee/Decisions/Documents/]
            exclude_path_fragments: [/Statistics/, /Templates/]
        """,
        encoding="utf-8",
    )
    spec = CatalogManifestLoader(manifest_path).load().sources[0]
    assert spec.allows_page("https://crsd.gov.sa/ar/ResolutionsCommittee/Decisions/Pages/default.aspx")
    assert spec.allows_document("https://crsd.gov.sa/ar/ResolutionsCommittee/Decisions/Documents/4812.pdf")
    assert not spec.allows_page("https://crsd.gov.sa/ar/ResolutionsCommittee/Statistics/Pages/default.aspx")
    assert not spec.allows_document("https://crsd.gov.sa/ar/ResolutionsCommittee/Templates/Documents/Form.pdf")
