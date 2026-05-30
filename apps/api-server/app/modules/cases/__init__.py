"""cases -- 个案与叙事：个案 CRUD、审核流程、AI 预审、EBP 校验、L1 叙事管理、L2 卡片提取。"""
from .routes import router as cases_router
from .review_routes import router as reviews_router
from .narrative_routes import router as narratives_router

__all__ = [
    "cases_router",
    "reviews_router",
    "narratives_router",
]
