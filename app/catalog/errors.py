from app.research.robust import ResearchServiceError


class CatalogNotReadyError(ResearchServiceError):
    """The current parser generation has not completed its first full refresh."""

    def __init__(self, detail: str = "") -> None:
        super().__init__(
            "catalog_not_ready",
            "🗂️ الفهرس القضائي للجيل الحالي ما زال قيد البناء أو لم يكتمل بناؤه بعد. "
            "لن يستخدم البوت سجلات جزئية أثناء الفهرسة. انتظر اكتمال تحديث الفهرس ثم أعد المحاولة.",
            detail=detail or "current catalog generation has not completed a full refresh",
        )
