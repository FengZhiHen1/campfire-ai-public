"""consultation -- 智能咨询：咨询编排、应急方案生成、流式推送、置信度校验、历史归档。"""
from .consult_service import search_cases, start_consultation
from .routes import router as consult_router
from .stream_routes import router as stream_router
from .history_routes import router as consultations_router

__all__ = [
    "search_cases",
    "start_consultation",
    "consult_router",
    "stream_router",
    "consultations_router",
]
