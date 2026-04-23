from fastapi import APIRouter

from app.api.v1.files import router as files_router
from app.api.v1.flows import router as flows_router
from app.api.v1.graph import router as graph_router
from app.api.v1.health import router as health_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.onboarding import router as onboarding_router
from app.api.v1.pr_impact import router as pr_impact_router
from app.api.v1.refresh_jobs import router as refresh_jobs_router
from app.api.v1.repo_snapshots import router as repo_snapshots_router
from app.api.v1.repos import router as repos_router
from app.api.v1.risk import router as risk_router
from app.api.v1.search import router as search_router
from app.api.v1.semantic import router as semantic_router
from app.api.v1.webhooks import router as webhooks_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health_router)
api_router.include_router(repos_router)
api_router.include_router(jobs_router)
api_router.include_router(repo_snapshots_router)
api_router.include_router(files_router)
api_router.include_router(semantic_router)
api_router.include_router(graph_router)
api_router.include_router(flows_router)
api_router.include_router(search_router)
api_router.include_router(risk_router)
api_router.include_router(pr_impact_router)
api_router.include_router(onboarding_router)
api_router.include_router(webhooks_router)
api_router.include_router(refresh_jobs_router)