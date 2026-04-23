from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.api.deps import get_db
from app.services.flow_service import FlowService
from app.services.repository_service import RepositoryService

router = APIRouter(tags=["flows"])


@router.get("/repos/{repo_id}/flows")
def get_execution_flow(
    repo_id: str,
    mode: str = Query(default="primary", regex="^(route|file|function|impact|primary)$"),
    query: Optional[str] = Query(default=""),
    changed: Optional[str] = Query(default=""),
    depth: int = Query(default=4, ge=1, le=6),
    db: Session = Depends(get_db),
):
    """
    Execution Flow Map — infer likely execution paths through the repository.

    Modes:
    - primary:  (default) auto-detect entrypoint and render primary app flow
    - route:    trace flow from a route/endpoint (e.g. /login, /api/users)
    - file:     show upstream + downstream flow for a file path
    - function: trace cross-file call path from a function/symbol name
    - impact:   show workflows affected by changed files (comma-separated)

    Examples:
      GET /repos/{id}/flows                              ← auto primary flow
      GET /repos/{id}/flows?mode=primary&query=app.py   ← primary from hint
      GET /repos/{id}/flows?mode=route&query=/login
      GET /repos/{id}/flows?mode=file&query=app/services/auth.py
      GET /repos/{id}/flows?mode=function&query=authenticate_user
      GET /repos/{id}/flows?mode=impact&changed=app/api/routes.py,app/services/auth.py
    """
    repository_service = RepositoryService(db)
    repo = repository_service.get_repository(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    flow_service = FlowService(db)
    result = flow_service.get_flow(
        repository_id=repo_id,
        mode=mode,
        query=query or "",
        changed=changed or "",
        depth=depth,
    )
    result["repo_id"] = repo_id
    return result
