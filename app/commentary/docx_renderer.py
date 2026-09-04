"""Arabic RTL DOCX renderer for the final academic commentary."""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from .models import CommentaryDraft


class DocxRenderer:
    def __init__(self, *, font_name: str = "Arial") -> None:
        self.font_name = font_name

    def render(self, draft: CommentaryDraft, *, subject_name: str, output_path: Path,
               subject_slug: str | None = None) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc = Document()
        section = doc.sections[0]
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.right_margin = Cm(2.2)
        section.left_margin = Cm(2.2)

        normal = doc.styles["Normal"]
        normal.font.name = self.font_name
        normal.font.size = Pt(14)
        r_pr = normal._element.get_or_add_rPr()
        r_fonts = r_pr.get_or_add_rFonts()
        r_fonts.set(qn("w:eastAsia"), self.font_name)
        r_fonts.set(qn("w:cs"), self.font_name)

        title = doc.add_paragraph()
        self._set_rtl(title)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = title.add_run(draft.title.strip())
        run.bold = True
        run.font.name = self.font_name
        run.font.size = Pt(17)

        course = doc.add_paragraph()
        self._set_rtl(course)
        course.alignment = WD_ALIGN_PARAGRAPH.CENTER
        course_run = course.add_run(f"المقرر: {subject_name}")
        course_run.font.name = self.font_name
        course_run.font.size = Pt(13)

        headings = self._headings(subject_slug)
        bodies = (draft.facts_and_course_link, draft.legal_issue, draft.court_reasoning, draft.comment_and_opinion)
        for heading, body in zip(headings, bodies, strict=True):
            self._add_heading(doc, heading)
            self._add_body(doc, body)

        if draft.references:
            self._add_heading(doc, "المراجع")
            for reference in draft.references:
                p = doc.add_paragraph()
                self._set_rtl(p)
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                r = p.add_run(reference.strip())
                r.font.name = self.font_name
                r.font.size = Pt(12)

        footer = section.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        field = OxmlElement("w:fldSimple")
        field.set(qn("w:instr"), "PAGE")
        footer._p.append(field)

        props = doc.core_properties
        props.author = ""
        props.last_modified_by = ""
        props.comments = ""
        doc.save(output_path)
        return output_path

    @staticmethod
    def _headings(subject_slug: str | None) -> tuple[str, str, str, str]:
        if subject_slug == "usul_al_fiqh":
            return (
                "أولاً: تلخيص وقائع القضية وربطها بالمفاهيم الأصولية",
                "ثانياً: تحديد المسألة القانونية الأصولية في الحكم وصلتها بالمقرر",
                "ثالثاً: تحليل تسبيب المحكمة في ضوء المبادئ الأصولية",
                "رابعاً: التعليق على الحكم وتبرير الرأي",
            )
        if subject_slug in {"administrative_law", "administrative_judiciary", "administrative_contracts"}:
            return (
                "أولاً: تلخيص وقائع القضية وربطها بالمفاهيم القانونية الإدارية",
                "ثانياً: تحديد المسألة القانونية وصلتها بالمقرر",
                "ثالثاً: تحليل تسبيب المحكمة في ضوء المبادئ والنصوص الإدارية",
                "رابعاً: التعليق على الحكم وتبرير الرأي",
            )
        return (
            "أولاً: تلخيص وقائع القضية وربطها بالمقرر",
            "ثانياً: تحديد المسألة القانونية وصلتها بالمقرر",
            "ثالثاً: تحليل تسبيب المحكمة",
            "رابعاً: التعليق على الحكم وتبرير الرأي",
        )

    def _add_heading(self, doc: Document, text: str) -> None:
        p = doc.add_paragraph()
        self._set_rtl(p)
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r = p.add_run(text)
        r.bold = True
        r.font.name = self.font_name
        r.font.size = Pt(15)

    def _add_body(self, doc: Document, text: str) -> None:
        chunks = [chunk.strip() for chunk in re.split(r"\n+", text) if chunk.strip()]
        for chunk in chunks or [text.strip()]:
            p = doc.add_paragraph()
            self._set_rtl(p)
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.line_spacing = 1.25
            p.paragraph_format.space_after = Pt(6)
            r = p.add_run(chunk)
            r.font.name = self.font_name
            r.font.size = Pt(14)

    @staticmethod
    def _set_rtl(paragraph) -> None:
        p_pr = paragraph._p.get_or_add_pPr()
        bidi = p_pr.find(qn("w:bidi"))
        if bidi is None:
            bidi = OxmlElement("w:bidi")
            p_pr.append(bidi)
        bidi.set(qn("w:val"), "1")
