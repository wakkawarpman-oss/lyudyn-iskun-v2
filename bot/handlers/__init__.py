from aiogram import Router

from bot.handlers.alerts import router as alerts_router
from bot.handlers.radar import router as radar_router
from bot.handlers.analytics import router as analytics_router
from bot.handlers.shelters import router as shelters_router
from bot.handlers.osint import router as osint_router
from bot.handlers.admin import router as admin_router
from bot.handlers.common import router as common_router

from bot.handlers.districts import router as districts_router
from bot.handlers.transport import router as transport_router

router = Router()

# Register modular sub-routers in clean deterministic priority order:
# Specific command/button routers first, catch-all text search (shelters) last.
router.include_router(alerts_router)
router.include_router(districts_router)
router.include_router(transport_router)
router.include_router(radar_router)
router.include_router(analytics_router)
router.include_router(osint_router)
router.include_router(admin_router)
router.include_router(common_router)
router.include_router(shelters_router)

__all__ = ["router"]
