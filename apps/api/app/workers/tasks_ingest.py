from app.db.models.repo_job import RepoJob
from app.db.models.repository import Repository
from app.db.session import SessionLocal
from app.services.ingestion_service import IngestionService
from app.utils.time import utc_now
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks_ingest.index_repository")
def index_repository(repository_id: str, job_id: str) -> dict:
    db = SessionLocal()

    try:
        repository = db.get(Repository, repository_id)
        job = db.get(RepoJob, job_id)

        if not repository or not job:
            return {"status": "error", "message": "Repository or job not found"}

        # STALE JOB CLEANUP: mark any older running index_repository jobs for this
        # repo as stale so they don't pollute the jobs list forever.
        from sqlalchemy import select as _select
        stale_jobs = list(db.scalars(
            _select(RepoJob).where(
                RepoJob.repository_id == repository_id,
                RepoJob.job_type == "index_repository",
                RepoJob.status == "running",
                RepoJob.id != job_id,
            )
        ).all())
        for stale in stale_jobs:
            stale.status = "cancelled"
            stale.completed_at = utc_now()
            stale.message = "Superseded by a newer index_repository run."
        if stale_jobs:
            db.commit()

        job.status = "running"
        job.message = "Repository ingestion started"
        repository.status = "indexing"
        job.started_at = utc_now()
        db.commit()

        ingestion_service = IngestionService(db)

        # STAGE: DISCOVER_FILES & CLONE
        job.message = "Stage: DISCOVER_FILES - Cloning repository snapshot"
        db.commit()
        local_path, commit_sha, snapshot = ingestion_service.clone_and_snapshot(repository)
        
        # STAGE: CLASSIFY_FILES & DETECT
        job.message = "Stage: CLASSIFY_FILES - Detecting frameworks and languages"
        db.commit()
        try:
            metadata = ingestion_service.detect_repo_metadata(repository, local_path)
            primary_language = metadata["primary_language"]
            detected_frameworks = metadata["detected_frameworks"]
            repository.primary_language = str(primary_language) if primary_language else "unknown"
            repository.detected_frameworks = str(detected_frameworks) if detected_frameworks else "none"
            db.commit()
        except Exception as e:
            primary_language = getattr(repository, "primary_language", "unknown")
            detected_frameworks = getattr(repository, "detected_frameworks", "none")
            
        # STAGE: EXTRACT_CONTENT
        job.message = "Stage: EXTRACT_CONTENT - Reading text files into inventory"
        db.commit()
        total_files = ingestion_service.ingest_file_inventory(repository, local_path)
        
        repository.status = "indexed"
        db.commit()

        # Track overall success
        pipeline_success = True

        # STAGE: PARSE_REPOSITORY
        job.message = "Stage: PARSE_REPOSITORY - Extracting semantics and computing repo intelligence"
        repository.status = "parsing"
        db.commit()
        try:
            from app.services.semantic_service import SemanticService
            from app.services.repo_intelligence_service import RepoIntelligenceService
            
            semantic_service = SemanticService(db)
            job.message = "Stage: PARSE_REPOSITORY - Parsing syntax and symbol graph"
            db.commit()
            parse_result = semantic_service.parse_repository(repository)
            
            job.message = "Stage: PARSE_REPOSITORY - Generating file-level LLM summaries"
            db.commit()
            semantic_service.enrich_repository(repository)
            
            job.message = "Stage: PARSE_REPOSITORY - Building global repository intelligence"
            db.commit()
            intel_service = RepoIntelligenceService(db)
            intel_service.build_repo_intelligence(repository)
            
            repository.status = "parsed"
        except Exception as _parse_err:
            print(f"Non-fatal error in semantic parsing: {str(_parse_err)}")
            db.rollback()
            repository.status = "parsed_with_errors"
            db.commit()

        # STAGE: EMBED_CONTENT
        job.message = "Stage: EMBED_CONTENT - Generating vector embeddings for semantic search"
        repository.status = "embedding"
        db.commit()
        embed_result = {}
        try:
            from app.services.embedding_service import EmbeddingService
            embedding_service = EmbeddingService(db)
            embed_result = embedding_service.embed_repository(repository)
            repository.status = "embedded"
            pipeline_success = True
        except Exception as _embed_err:
            print(f"Non-fatal error in embedding: {str(_embed_err)}")
            db.rollback()
            repository.status = "embedded_with_errors"
            db.commit()
            pipeline_success = True  # We still consider it partially successful as long as we have code

        # STAGE: FINALIZE_STATUS
        # Rules:
        #   READY   — files ingested AND searchable chunks produced
        #   DEGRADED — files ingested BUT 0 chunks (inventory only; Search/Ask Repo unusable)
        #   FAILED  — 0 files ingested (clone succeeded but nothing was readable)
        parsed_count = embed_result.get("processed_files", 0)
        chunk_count = embed_result.get("total_chunks", 0)

        if total_files > 0 and chunk_count > 0:
            repository.status = "ready"
            job.status = "completed"
            job.message = (
                f"Indexing complete: {total_files} files ingested, "
                f"{parsed_count} embedded, {chunk_count} chunks. "
                f"Repository is ready for Search and Ask Repo."
            )
        elif total_files > 0:
            # Files discovered but nothing was embeddable — inventory exists.
            # We use 'indexed' as the success-like state for this scenario.
            repository.status = "indexed"
            job.status = "completed"
            job.message = (
                f"Repository inventory complete: {total_files} files indexed. "
                f"No searchable chunks were produced — semantic search and Ask Repo "
                f"will use file-level keyword search only."
            )
        else:
            repository.status = "failed"
            job.status = "failed"
            job.message = "Pipeline finished with 0 files ingested — repository may be empty or all files were unreadable."

        job.completed_at = utc_now()
        db.commit()

        return {
            "status": job.status,
            "repository_id": repository_id,
            "job_id": job_id,
            "snapshot_id": snapshot.id,
            "commit_sha": commit_sha,
            "total_files": total_files,
            "primary_language": primary_language,
            "detected_frameworks": detected_frameworks,
            "total_chunks": embed_result.get("total_chunks", 0),
        }

    except Exception as exc:
        import traceback
        from app.core.config import get_settings
        settings = get_settings()
        # Use str(exc) directly — for ValueError (clone failures) this is already
        # a clean user-facing message.  For other exceptions include the type.
        if isinstance(exc, ValueError):
            error_msg = str(exc)
        else:
            error_msg = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] index_repository failed: {error_msg}")
        traceback.print_exc()

        db.rollback()
        job = db.get(RepoJob, job_id)
        repository = db.get(Repository, repository_id)

        # Determine whether the repository has usable content in the DB,
        # regardless of what status was set before the crash.
        # A new run that fails at clone time sets status='indexing' before any
        # work — but a PREVIOUS successful run may have left files and chunks.
        # We must check actual DB counts, not just the in-flight status string.
        _total_files_recovered = locals().get("total_files", 0)

        _has_usable_content = False
        if repository:
            # Check _INVENTORY_DONE_STATUSES first (fast path — no extra query)
            _INVENTORY_DONE_STATUSES = {
                "indexed", "ready",
                "parsing", "parsed", "parsed_with_errors",
                "embedding", "embedded", "embedded_with_errors",
            }
            if _total_files_recovered > 0 or repository.status in _INVENTORY_DONE_STATUSES:
                _has_usable_content = True
            else:
                # Slow path: the status is 'indexing' or 'connected' (set at job
                # start, before any inventory work).  A previous successful run
                # may have left files/chunks in the DB — check directly.
                from sqlalchemy import func as _func, select as _sel
                from app.db.models.file import File as _File
                _db_file_count = db.scalar(
                    _sel(_func.count(_File.id)).where(_File.repository_id == repository_id)
                ) or 0
                if _db_file_count > 0:
                    _has_usable_content = True

        if _has_usable_content:
            # Preserve the best terminal status that reflects actual capability.
            # If the repo already had a good status from a previous run, keep it.
            _KEEP_STATUSES = {
                "ready", "indexed",
                "parsed", "parsed_with_errors",
                "embedded", "embedded_with_errors",
            }
            if repository.status not in _KEEP_STATUSES:
                # Was mid-flight (indexing/parsing/embedding) when it crashed —
                # check chunks to decide between ready and indexed.
                from sqlalchemy import func as _func2, select as _sel2
                from app.db.models.embedding_chunk import EmbeddingChunk as _EC
                _db_chunk_count = db.scalar(
                    _sel2(_func2.count(_EC.id)).where(_EC.repository_id == repository_id)
                ) or 0
                repository.status = "ready" if _db_chunk_count > 0 else "indexed"
            if job:
                job.status = "completed"
                job.completed_at = utc_now()
                job.message = (
                    f"Repository re-index encountered an error ({error_msg}), "
                    f"but previous indexed content is still available."
                )
        elif repository:
            # Truly nothing usable — mark failed.
            repository.status = "failed"
            if job:
                job.status = "failed"
                job.completed_at = utc_now()
                job.message = error_msg  # already clean for ValueError (clone failures)

        db.commit()

        return {
            "status": "failed",
            "repository_id": repository_id,
            "job_id": job_id,
            "error": error_msg,
            "traceback": traceback.format_exc() if settings.DEBUG else None,
        }

    finally:
        db.close()
