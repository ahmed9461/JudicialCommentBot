from .admin import router as admin_router
from .start import router as start_router
from .subjects import router as subjects_router

__all__ = ["admin_router", "start_router", "subjects_router"]
