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

    def render(
        self,
        draft: CommentaryDraft,
        *,
        subject_name: str,
        output_path: Path,
    ) -> Path:
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
        normal._element.rPr.rFonts.set(qn("w:eastAsia"), self.font_name)
        normal._element.rPr.rFonts.set(qn("w:cs"), self.font_name)

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

        sections = [
            ("أولاً: تلخيص وقائع القضية وربطها بالمقرر", draft.facts_and_course_link),
            ("ثانياً: تحديد المسألة القانونية وصلتها بالمقرر", draft.legal_issue),
            ("ثالثاً: تحليل تسبيب المحكمة", draft.court_reasoning),
            ("رابعاً: التعليق على الحكم وتبرير الرأي", draft.comment_and_opinion),
        ]
        for heading, body in sections:
            self._add_heading(doc, heading)
            self._add_body(doc, body)

        if draft.references:
            self._add_heading(doc, "المراجع")
            for reference in draft.references:
                paragraph = doc.add_paragraph()
                self._set_rtl(paragraph)
                paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                run = paragraph.add_run(reference.strip())
                run.font.name = self.font_name
                run.font.size = Pt(12)

        props = doc.core_properties
        props.author = ""
        props.last_modified_by = ""
        props.comments = ""
        doc.save(output_path)
        return output_path

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
