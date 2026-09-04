from app.research.robust import ResearchServiceError


class CatalogNotReadyError(ResearchServiceError):
    """The official catalog has not been built on this deployment yet."""

    def __init__(self, detail: str = "") -> None:
        super().__init__(
            "catalog_not_ready",
            "🗂️ فهرس الأحكام الرسمية لم يُبنَ بعد على هذا السيرفر. لم يبدأ أي بحث ويب مدفوع. شغّل بناء الفهرس مرة واحدة ثم أعد المحاولة.",
            detail=detail or "official catalog is empty",
        )
