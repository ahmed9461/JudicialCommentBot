"""End-to-end case discovery, PDF verification, reservation, deduplication and selection."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.core.settings import Settings
from app.db import Database
from app.knowledge import SubjectLoader
from app.pdf import (
    PdfAcquisitionError, PdfAcquisitionService, PdfArtifact, PdfValidationError,
    extract_page_range, extract_pdf_text, locate_case_page_range, verify_case_number_in_pdf,
)
from app.pdf.validation import validate_pdf_file
from app.ranking import ScoreResult, ScoringPolicy, SelectionDecision, select_candidates
from app.research import CaseCandidate, ResearchProvider
from app.sources import SourceRegistry

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[str], Awaitable[None]]


class NoSuitableCasesError(RuntimeError):
    pass


@dataclass(slots=True)
class PreparedCase:
    token: str
    candidate: CaseCandidate
    artifact: PdfArtifact
    judgment_text: str
    score: ScoreResult
    artifact_kind: str = "official_pdf"
    source_page_start: int | None = None
    source_page_end: int | None = None

    @property
    def final_score(self) -> int:
        return self.score.total


@dataclass(slots=True)
class WorkflowSession:
    subject_slug: str
    cases: dict[str, PreparedCase] = field(default_factory=dict)
    selected_token: str | None = None
    recorded: bool = False

    @property
    def selected(self) -> PreparedCase | None:
        return self.cases.get(self.selected_token or "")


@dataclass(frozen=True, slots=True)
class PreparedBatch:
    decision: SelectionDecision
    cases: tuple[PreparedCase, ...]


class CaseWorkflowService:
    def __init__(self, *, database: Database, subject_loader: SubjectLoader,
                 research_provider: ResearchProvider, source_registry: SourceRegistry,
                 pdf_service: PdfAcquisitionService, scoring: ScoringPolicy,
                 settings: Settings) -> None:
        self.database = database
        self.subject_loader = subject_loader
        self.research_provider = research_provider
        self.source_registry = source_registry
        self.pdf_service = pdf_service
        self.scoring = scoring
        self.settings = settings
        self._sessions: dict[int, WorkflowSession] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock(self, user_id: int) -> asyncio.Lock:
        return self._locks.setdefault(user_id, asyncio.Lock())

    async def prepare(self, user_id: int, subject_slug: str,
                      progress: ProgressCallback | None = None) -> PreparedBatch:
        async with self._lock(user_id):
            await self._cleanup_session(user_id)
            subject = self.subject_loader.get_subject(subject_slug)
            await _notify(progress, f"⚙️ جاري تجهيز البحث لمادة: {subject.name_ar}…")
            dynamic_exclusions = list(await self.database.used_cases_for_subject(subject_slug))
            verified: list[PreparedCase] = []
            seen_identity: set[tuple[str, ...]] = set()

            for round_index in range(max(1, self.settings.search_retry_rounds)):
                await _notify(
                    progress,
                    f"🔎 جاري البحث عن القضية المناسبة…\nالجولة {round_index + 1} من {max(1, self.settings.search_retry_rounds)}",
                )
                try:
                    candidates = await self.research_provider.search_cases(
                        subject, excluded_cases=dynamic_exclusions,
                        limit=self.settings.search_candidate_limit,
                    )
                except Exception:
                    if verified:
                        break
                    raise
                if not candidates:
                    await _notify(progress, "⚠️ لم تظهر نتائج قابلة للفحص في هذه الجولة، جاري المحاولة التالية…")
                    continue

                await _notify(
                    progress,
                    f"📚 تم العثور على {len(candidates)} مرشحًا، جاري فحص المصادر وملفات الأحكام الأصلية…",
                )
                for index, candidate in enumerate(candidates, start=1):
                    identity = self._candidate_identity(candidate)
                    if identity in seen_identity:
                        continue
                    seen_identity.add(identity)
                    await _notify(
                        progress,
                        f"🌐 جاري فتح مصدر القضية {index}/{len(candidates)} والتحقق من الحكم…\n{candidate.title[:120]}",
                    )
                    prepared = await self._verify_candidate(
                        candidate,
                        progress=progress,
                        candidate_index=index,
                        candidate_total=len(candidates),
                    )
                    if prepared is None:
                        dynamic_exclusions.append({
                            "case_number": candidate.case_number,
                            "court_name": candidate.court_name,
                            "source_url": candidate.source_url_str,
                        })
                        continue
                    verified.append(prepared)
                    await _notify(
                        progress,
                        f"✅ تم التحقق من قضية مناسبة ({prepared.final_score}/100).\nجاري استكمال فحص بقية المرشحين واختيار الأفضل…",
                    )
                if len(verified) >= self.settings.candidate_display_count:
                    break

            if not verified:
                raise NoSuitableCasesError("No candidate survived official PDF verification and deduplication")

            await _notify(progress, "⚖️ جاري ترتيب القضايا الموثقة واختيار الأعلى ملاءمة للمقرر…")
            verified.sort(key=lambda item: item.final_score, reverse=True)
            decision = select_candidates(
                verified, auto_accept_score=self.settings.auto_accept_score,
                display_count=self.settings.candidate_display_count,
                min_margin=self.scoring.min_auto_accept_margin,
                require_margin=self.scoring.require_score_margin,
            )
            session = WorkflowSession(
                subject_slug=subject_slug,
                cases={item.token: item for item in verified},
            )
            self._sessions[user_id] = session
            if decision.is_auto and decision.selected_index is not None:
                await self._select_session_case(session, verified[decision.selected_index].token)
            return PreparedBatch(
                decision=decision,
                cases=tuple(verified[:decision.visible_count]),
            )

    async def _verify_candidate(self, candidate: CaseCandidate,
                                progress: ProgressCallback | None = None,
                                candidate_index: int | None = None,
                                candidate_total: int | None = None) -> PreparedCase | None:
        pdf_url = candidate.pdf_url_str
        if not pdf_url and self.source_registry.can_be_original_pdf_source(candidate.source_url_str):
            pdf_url = candidate.source_url_str
        if not pdf_url or not self.source_registry.can_be_original_pdf_source(pdf_url):
            await _notify(progress, "↪️ المصدر الحالي لا يوفر PDF رسميًا مباشرًا، جاري الانتقال لمرشح آخر…")
            return None

        artifact: PdfArtifact | None = None
        artifact_kind = "official_pdf"
        start_page: int | None = None
        end_page: int | None = None
        token = secrets.token_urlsafe(9)
        label = ""
        if candidate_index is not None and candidate_total is not None:
            label = f" {candidate_index}/{candidate_total}"
        try:
            await _notify(progress, f"📥 جاري تنزيل ملف الحكم الرسمي{label} والتحقق من المصدر…")
            artifact = await self.pdf_service.acquire(
                pdf_url,
                suggested_name=candidate.case_number or candidate.title,
            )
            await _notify(
                progress,
                f"🔐 تم تنزيل PDF رسمي، جاري فحص سلامة الملف والهوية والبصمة الرقمية…\nعدد الصفحات: {artifact.page_count}",
            )

            if artifact.page_count > self.settings.compilation_page_threshold:
                if not candidate.case_number:
                    raise PdfValidationError("Large compilation requires a case number for identity verification")
                await _notify(progress, "📚 الحكم داخل مجموعة أحكام رسمية، جاري تحديد صفحات القضية الأصلية…")
                if candidate.has_page_range:
                    start_page, end_page = candidate.pdf_page_start, candidate.pdf_page_end
                    assert start_page is not None and end_page is not None
                else:
                    start_page, end_page = locate_case_page_range(
                        artifact.path, candidate.case_number
                    )
                artifact = self._extract_compilation_case(
                    artifact, candidate, start_page, end_page
                )
                artifact_kind = "official_compilation_extract"
            elif candidate.has_page_range:
                if not candidate.case_number:
                    raise PdfValidationError("Page-range extraction requires a case number")
                assert candidate.pdf_page_start is not None and candidate.pdf_page_end is not None
                start_page, end_page = candidate.pdf_page_start, candidate.pdf_page_end
                await _notify(progress, "📄 جاري استخراج صفحات القضية المحددة من الملف الرسمي…")
                artifact = self._extract_compilation_case(
                    artifact, candidate, start_page, end_page
                )
                artifact_kind = "official_compilation_extract"

            if candidate.case_number and not verify_case_number_in_pdf(
                artifact.path, candidate.case_number
            ):
                raise PdfValidationError("Verified PDF does not contain the claimed case number")

            if await self.database.is_case_used(
                case_number=candidate.case_number,
                court_name=candidate.court_name,
                pdf_sha256=artifact.sha256,
            ):
                artifact.path.unlink(missing_ok=True)
                await _notify(progress, "♻️ هذه القضية مستخدمة سابقًا، جاري الانتقال لغيرها…")
                return None

            await _notify(progress, "📖 جاري قراءة نص الحكم والتحقق من أنه صالح للتحليل الأكاديمي…")
            text = extract_pdf_text(
                artifact.path,
                max_chars=self.settings.commentary_input_max_chars,
            )
            if len(text) < self.settings.commentary_min_text_chars:
                raise PdfValidationError("Judgment PDF contains too little extractable text")

            score = self.scoring.score(
                candidate,
                pdf_is_official=self.source_registry.classify(artifact.source_url).is_official,
            )
            if not await self.database.reserve_case(
                token,
                case_number=candidate.case_number,
                court_name=candidate.court_name,
                pdf_sha256=artifact.sha256,
            ):
                artifact.path.unlink(missing_ok=True)
                await _notify(progress, "↪️ تم حجز القضية في جلسة أخرى، جاري الانتقال لمرشح آخر…")
                return None

            return PreparedCase(
                token=token,
                candidate=candidate,
                artifact=artifact,
                judgment_text=text,
                score=score,
                artifact_kind=artifact_kind,
                source_page_start=start_page,
                source_page_end=end_page,
            )
        except (PdfAcquisitionError, OSError, ValueError) as exc:
            logger.info("Candidate PDF rejected title=%r reason=%s", candidate.title, exc)
            if artifact is not None:
                artifact.path.unlink(missing_ok=True)
            await self.database.release_reservation(token)
            await _notify(progress, "⚠️ لم يجتز هذا المرشح التحقق، جاري تجربة قضية أخرى…")
            return None

    def _extract_compilation_case(self, artifact: PdfArtifact, candidate: CaseCandidate,
                                  start_page: int, end_page: int) -> PdfArtifact:
        output = artifact.path.with_name(f"{artifact.path.stem}-case.pdf")
        extract_page_range(
            artifact.path,
            start_page=start_page,
            end_page=end_page,
            output_pdf=output,
        )
        artifact.path.unlink(missing_ok=True)
        if not candidate.case_number or not verify_case_number_in_pdf(
            output, candidate.case_number
        ):
            output.unlink(missing_ok=True)
            raise PdfValidationError("Extracted compilation pages do not match the case number")
        page_count = validate_pdf_file(output, max_pages=self.settings.pdf_max_pages)
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        return PdfArtifact(
            path=output,
            source_url=artifact.source_url,
            sha256=digest,
            size_bytes=output.stat().st_size,
            page_count=page_count,
        )

    @staticmethod
    def _candidate_identity(candidate: CaseCandidate) -> tuple[str, ...]:
        if candidate.case_number and candidate.court_name:
            return (
                "case",
                candidate.case_number.strip().casefold(),
                candidate.court_name.strip().casefold(),
            )
        return ("url", candidate.source_url_str)

    async def select(self, user_id: int, token: str) -> PreparedCase:
        session = self._sessions.get(user_id)
        if session is None or token not in session.cases:
            raise KeyError("Candidate session expired")
        await self._select_session_case(session, token)
        return session.cases[token]

    async def _select_session_case(self, session: WorkflowSession, token: str) -> None:
        selected = session.cases[token]
        discarded = [key for key in session.cases if key != token]
        for key in discarded:
            session.cases[key].artifact.path.unlink(missing_ok=True)
        await self.database.release_reservations(discarded)
        session.cases = {token: selected}
        session.selected_token = token

    def selected(self, user_id: int) -> PreparedCase:
        session = self._sessions.get(user_id)
        if session is None or session.selected is None:
            raise KeyError("No selected case")
        return session.selected

    def session_subject(self, user_id: int) -> str:
        session = self._sessions.get(user_id)
        if session is None:
            raise KeyError("Session expired")
        return session.subject_slug

    async def record_sent(self, user_id: int) -> None:
        session = self._sessions.get(user_id)
        if session is None or session.selected is None:
            raise KeyError("No selected case")
        selected = session.selected
        if not session.recorded:
            await self.database.record_case(
                subject_slug=session.subject_slug,
                case_number=selected.candidate.case_number,
                court_name=selected.candidate.court_name,
                source_name=selected.candidate.source_name,
                source_url=selected.artifact.source_url,
                pdf_sha256=selected.artifact.sha256,
                suitability_score=selected.final_score,
                artifact_kind=selected.artifact_kind,
                source_page_start=selected.source_page_start,
                source_page_end=selected.source_page_end,
            )
            await self.database.add_audit(
                "assignment_sent",
                subject_slug=session.subject_slug,
                case_number=selected.candidate.case_number,
                details=f"score={selected.final_score};artifact={selected.artifact_kind}",
            )
            session.recorded = True
        await self.database.release_reservation(selected.token)
        if self.settings.delete_files_after_send:
            selected.artifact.path.unlink(missing_ok=True)

    async def cleanup_user(self, user_id: int) -> None:
        async with self._lock(user_id):
            await self._cleanup_session(user_id)

    async def _cleanup_session(self, user_id: int) -> None:
        session = self._sessions.pop(user_id, None)
        if not session:
            return
        tokens = list(session.cases)
        for item in session.cases.values():
            item.artifact.path.unlink(missing_ok=True)
        await self.database.release_reservations(tokens)


async def _notify(progress: ProgressCallback | None, text: str) -> None:
    if progress is not None:
        await progress(text)
