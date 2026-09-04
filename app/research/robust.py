"""Preflight validation and user-safe error mapping around DeepSeek research."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

import httpx

from app.knowledge import SubjectProfile

from .models import CaseCandidate
from .provider import ResearchProvider

logger = logging.getLogger(__name__)
ResearchProgressCallback = Callable[[str], Awaitable[None]]


class ResearchServiceError(RuntimeError):
    """A research failure that can be shown safely to the Telegram user."""

    def __init__(self, code: str, user_message: str, *, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.user_message = user_message
        self.detail = detail


class RobustResearchProvider:
    """Validate balance/model availability before costly search and map API failures."""

    def __init__(
        self,
        *,
        inner: ResearchProvider,
        api_key: str,
        base_url: str,
        model: str,
        preflight_ttl_seconds: float = 300.0,
    ) -> None:
        self.inner = inner
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.preflight_ttl_seconds = max(0.0, float(preflight_ttl_seconds))
        self._preflight_ok_at = 0.0

    async def search_cases(
        self,
        subject: SubjectProfile,
        *,
        excluded_cases: list[dict[str, str | None]],
        limit: int,
        progress: ResearchProgressCallback | None = None,
    ) -> list[CaseCandidate]:
        await self._preflight(progress)
        try:
            return await self.inner.search_cases(
                subject,
                excluded_cases=excluded_cases,
                limit=limit,
                progress=progress,
            )
        except ResearchServiceError:
            raise
        except httpx.HTTPStatusError as exc:
            raise _http_error(exc.response.status_code, _safe_body(exc.response)) from exc
        except httpx.TimeoutException as exc:
            raise ResearchServiceError(
                "deepseek_timeout",
                "⏱️ انتهت مهلة DeepSeek قبل اكتمال البحث. لم يتم خصم محاولة بحث جديدة تلقائيًا.",
                detail=type(exc).__name__,
            ) from exc
        except httpx.RequestError as exc:
            raise ResearchServiceError(
                "deepseek_network",
                "🌐 تعذر الاتصال بخدمة DeepSeek حاليًا. لم يتم اعتماد أي قضية.",
                detail=f"{type(exc).__name__}: {exc}",
            ) from exc
        except ValueError as exc:
            raise ResearchServiceError(
                "deepseek_output",
                "🧩 انتهى بحث DeepSeek لكن لم تصل نتيجة منظمة قابلة للاستخدام. لم يتم اعتماد أي قضية.",
                detail=str(exc),
            ) from exc

    async def _preflight(self, progress: ResearchProgressCallback | None) -> None:
        now = time.monotonic()
        if self._preflight_ok_at and now - self._preflight_ok_at < self.preflight_ttl_seconds:
            return

        if progress is not None:
            await progress("🩺 جاري فحص اتصال DeepSeek والرصيد والنموذج قبل بدء البحث المدفوع…")

        headers = {"Authorization": f"Bearer {self.api_key}"}
        timeout = httpx.Timeout(10.0, connect=5.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                balance_response = await client.get(f"{self.base_url}/user/balance", headers=headers)
                if balance_response.status_code >= 400:
                    raise _http_error(balance_response.status_code, _safe_body(balance_response))
                balance = balance_response.json()
                if balance.get("is_available") is False:
                    raise ResearchServiceError(
                        "deepseek_balance",
                        "💳 رصيد DeepSeek غير كافٍ لتنفيذ البحث. لم يبدأ البحث المدفوع.",
                        detail="balance is unavailable",
                    )

                models_response = await client.get(f"{self.base_url}/models", headers=headers)
                if models_response.status_code >= 400:
                    raise _http_error(models_response.status_code, _safe_body(models_response))
                model_ids = {
                    str(item.get("id"))
                    for item in (models_response.json().get("data") or [])
                    if isinstance(item, dict) and item.get("id")
                }
                if model_ids and self.model not in model_ids:
                    raise ResearchServiceError(
                        "deepseek_model",
                        f"⚙️ نموذج البحث المضبوط ({self.model}) غير متاح للحساب حاليًا. لم يبدأ البحث المدفوع.",
                        detail=f"available={sorted(model_ids)}",
                    )
        except ResearchServiceError:
            raise
        except httpx.HTTPStatusError as exc:
            raise _http_error(exc.response.status_code, _safe_body(exc.response)) from exc
        except httpx.TimeoutException as exc:
            raise ResearchServiceError(
                "deepseek_preflight_timeout",
                "🌐 تعذر فحص DeepSeek قبل البحث بسبب مهلة اتصال. لم يبدأ البحث المدفوع.",
                detail=type(exc).__name__,
            ) from exc
        except httpx.RequestError as exc:
            raise ResearchServiceError(
                "deepseek_preflight_network",
                "🌐 تعذر الوصول إلى DeepSeek لفحص الخدمة. لم يبدأ البحث المدفوع.",
                detail=f"{type(exc).__name__}: {exc}",
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ResearchServiceError(
                "deepseek_preflight_response",
                "⚠️ تعذر قراءة حالة DeepSeek قبل البحث. لم يبدأ البحث المدفوع.",
                detail=str(exc),
            ) from exc

        self._preflight_ok_at = time.monotonic()
        logger.info("DeepSeek preflight passed model=%s", self.model)


def _http_error(status: int, detail: str) -> ResearchServiceError:
    mapping: dict[int, tuple[str, str]] = {
        400: ("deepseek_bad_request", "⚙️ DeepSeek رفض صيغة طلب البحث (HTTP 400). يحتاج إعداد الطلب إلى مراجعة، ولم يتم اعتماد قضية."),
        401: ("deepseek_auth", "🔑 مفتاح DeepSeek غير صالح أو غير مصرح (HTTP 401)."),
        402: ("deepseek_balance", "💳 رصيد DeepSeek غير كافٍ (HTTP 402). لم يتم تنفيذ البحث."),
        422: ("deepseek_parameters", "⚙️ DeepSeek رفض أحد إعدادات الطلب (HTTP 422). لم يتم اعتماد قضية."),
        429: ("deepseek_rate_limit", "⏳ تم الوصول إلى حد طلبات DeepSeek مؤقتًا (HTTP 429). جرّب لاحقًا."),
        500: ("deepseek_server", "🛠️ DeepSeek واجه خطأ داخليًا (HTTP 500). جرّب لاحقًا."),
        503: ("deepseek_overloaded", "🚦 DeepSeek مزدحم حاليًا (HTTP 503). جرّب لاحقًا."),
    }
    code, message = mapping.get(
        status,
        ("deepseek_http", f"🌐 فشل طلب DeepSeek برمز HTTP {status}. لم يتم اعتماد أي قضية."),
    )
    return ResearchServiceError(code, message, detail=detail)


def _safe_body(response: httpx.Response) -> str:
    try:
        text = response.text
    except Exception:
        return ""
    return text[:1200]
