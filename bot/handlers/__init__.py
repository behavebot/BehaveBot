from aiogram import Router

from .start import router as start_router
from .guide import router as guide_router
from .feedback import router as feedback_router
from .admin_feedback import router as admin_feedback_router
from .admin_analytics import router as admin_analytics_router
from .token import router as token_router
from .open_position import router as open_position_router
from .close_position import router as close_position_router
from .stats import router as stats_router
from .misc import router as misc_router


def setup_routers() -> Router:
    root = Router()
    root.include_router(start_router)
    root.include_router(guide_router)
    root.include_router(stats_router)
    root.include_router(feedback_router)
    root.include_router(admin_feedback_router)
    root.include_router(admin_analytics_router)
    root.include_router(open_position_router)
    root.include_router(close_position_router)
    root.include_router(misc_router)
    root.include_router(token_router)  # last: must not override FSM free-text handlers
    return root
