from fastapi import APIRouter

from app.api.v1.endpoints import auth, ai, uploads

api_router = APIRouter()

# Include essential endpoint routers
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(uploads.router, prefix="/uploads", tags=["uploads"])
