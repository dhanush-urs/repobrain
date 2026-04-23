from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models.dependency_edge import DependencyEdge
from app.db.models.file import File
from app.db.models.repo_snapshot import RepoSnapshot
from app.db.models.symbol import Symbol
from app.db.models.repository import Repository
from app.parsers.javascript_parser import JavaScriptParser
from app.parsers.python_parser import PythonParser
from app.utils.path_utils import normalize_repo_snapshot_path
from app.services.graph_service import GraphService
from app.llm.providers import get_chat_provider
import logging

logger = logging.getLogger(__name__)

class SemanticService:
    def __init__(self, db: Session):
        self.db = db
        self.parsers = [
            PythonParser(),
            JavaScriptParser(),
        ]
        self.graph_service = GraphService(db)

    def _get_repo_root(self, repository: Repository) -> Path | None:
        snapshot = self.db.scalar(
            select(RepoSnapshot)
            .where(RepoSnapshot.repository_id == repository.id)
            .order_by(RepoSnapshot.created_at.desc())
            .limit(1)
        )

        if not snapshot:
            return None

        return normalize_repo_snapshot_path(snapshot.local_path)

    def _get_parser_for_language(self, language: str | None):
        if language == "Python":
            return self.parsers[0]

        if language in {"JavaScript", "TypeScript"}:
            return self.parsers[1]

        return None

    def parse_repository(self, repository: Repository) -> dict:
        repo_root = self._get_repo_root(repository)
        if not repo_root:
            raise ValueError("No repository snapshot found")

        self.db.execute(delete(Symbol).where(Symbol.repository_id == repository.id))
        self.db.execute(delete(DependencyEdge).where(DependencyEdge.repository_id == repository.id))

        # Identify files ready for semantic parsing
        files_to_parse = list(
            self.db.scalars(
                select(File).where(
                    File.repository_id == repository.id,
                    File.parse_status == "content_extracted",
                   File.file_kind.in_({"source", "test", "config", "build", "script"})
                )
            ).all()
        )

        parsed_files = 0
        failed_files = 0
        skipped_files = 0
        total_symbols = 0
        total_dependencies = 0

        for file_record in files_to_parse:
            try:
                file_path = repo_root / file_record.path

                if not file_path.exists() or not file_path.is_file():
                    file_record.parse_status = "failed: missing_on_disk"
                    failed_files += 1
                    continue

                # PREVENT PATHOLOGICAL SLOWDOWNS: Skip massive files (e.g. bundled/vendor JS, heavy auto-generated code)
                file_size = file_path.stat().st_size
                if file_size > 512 * 1024 or (file_record.line_count and file_record.line_count > 8000):
                    file_record.parse_status = "skipped_large"
                    skipped_files += 1
                    continue

                parser = self._get_parser_for_language(file_record.language)

                if not parser:
                    # Still content_extracted or considered skipped specifically for symbols
                    file_record.parse_status = "parsed"
                    skipped_files += 1
                    continue

                result = parser.parse(file_path)

                if result.get("error"):
                    file_record.parse_status = "failed"
                    failed_files += 1
                    continue

                # BOUNDARY: Limit maximum extracted symbols/edges to prevent ORM / Session bloat
                max_items = 2000
                extracted_symbols = result.get("symbols", [])[:max_items]
                extracted_deps = result.get("dependencies", [])[:max_items]

                for symbol_data in extracted_symbols:
                    symbol = Symbol(
                        repository_id=repository.id,
                        file_id=file_record.id,
                        name=symbol_data["name"][:255],  # ensure safe length
                        symbol_type=symbol_data["symbol_type"],
                        signature=str(symbol_data.get("signature"))[:1000] if symbol_data.get("signature") else None,
                        start_line=symbol_data.get("start_line", 0),
                        end_line=symbol_data.get("end_line", 0),
                        summary=str(symbol_data.get("summary"))[:2000] if symbol_data.get("summary") else None,
                    )
                    self.db.add(symbol)
                    total_symbols += 1

                for dep_data in extracted_deps:
                    edge = DependencyEdge(
                        repository_id=repository.id,
                        source_file_id=file_record.id,
                        target_file_id=None,
                        edge_type=dep_data["edge_type"],
                        source_ref=str(dep_data.get("source_ref"))[:255] if dep_data.get("source_ref") else None,
                        target_ref=str(dep_data.get("target_ref"))[:255] if dep_data.get("target_ref") else None,
                    )
                    self.db.add(edge)
                    total_dependencies += 1

                file_record.parse_status = "parsed"
                parsed_files += 1

                # Populate imports_list for fast fallback inference in graph queries
                imports_list = result.get("imports_list", "")
                if imports_list:
                    file_record.imports_list = imports_list[:4000]  # cap to column budget
                
                # FLUSH incrementally to prevent monolithic session bloat
                self.db.flush()

            except Exception as _file_parse_err:
                self.db.rollback()
                # NON-FATAL: parser crash or DB flush error on this file — mark it and continue
                failed_files += 1
                logger.warning(f"[SemanticService] Parser/DB exception for {file_record.path}: {_file_parse_err}")
                try:
                    from sqlalchemy import update
                    self.db.execute(
                        update(File)
                        .where(File.id == file_record.id)
                        .values(parse_status="failed")
                    )
                    self.db.commit()
                except Exception:
                    self.db.rollback()


        repository.total_symbols = total_symbols
        self.db.commit()

        # Step 3: Resolve Dependency Graph
        resolved = self.graph_service.resolve_repository_dependencies(repository.id)
        
        return {
            "parsed_files": parsed_files,
            "failed_files": failed_files,
            "skipped_files": skipped_files,
            "total_symbols": total_symbols,
            "total_dependencies": total_dependencies,
            "resolved_dependencies": resolved,
        }

    def enrich_repository(self, repository: Repository) -> dict:
        """
        Uses an LLM to generate a high-level summary of the repository based on 
        README, manifests, and file headers.
        """
        chat_provider = get_chat_provider()
        if not chat_provider:
            return {"status": "skipped", "reason": "No LLM provider available"}

        # Fetch README and entry points for project-level summary
        readme = self.db.scalar(
            select(File).where(File.repository_id == repository.id, File.path.ilike("%README.md%"))
        )
        package_json = self.db.scalar(
            select(File).where(File.repository_id == repository.id, File.path == "package.json")
        )
        pyproject = self.db.scalar(
            select(File).where(File.repository_id == repository.id, File.path == "pyproject.toml")
        )

        metadata_context = []
        if readme and readme.content:
            metadata_context.append(f"README.md:\n{readme.content[:4000]}")
        if package_json and package_json.content:
            metadata_context.append(f"package.json:\n{package_json.content}")
        if pyproject and pyproject.content:
            metadata_context.append(f"pyproject.toml:\n{pyproject.content}")

        if not metadata_context:
            return {"status": "skipped", "reason": "No metadata files found"}

        system_prompt = (
            "You are a repository assistant. Summarize the following project information "
            "into a 3-paragraph executive summary covering:\n"
            "1. Purpose & Core Functionality\n"
            "2. Tech Stack & Primary Core Logic\n"
            "3. Key Entrypoints & Architecture\n"
            "Be technical, concise, and accurate."
        )
        user_prompt = "\n\n".join(metadata_context)

        try:
            summary = chat_provider.answer(system_prompt, user_prompt)
            repository.summary = summary
            self.db.commit()
            return {"status": "completed", "summary": summary}
        except Exception as e:
            logger.error(f"Enrichment failed: {e}")
            return {"status": "error", "message": str(e)}

    def list_symbols(
        self,
        repository_id: str,
        file_id: str | None = None,
        symbol_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Symbol], int]:
        base_stmt = select(Symbol).where(Symbol.repository_id == repository_id)

        if file_id:
            base_stmt = base_stmt.where(Symbol.file_id == file_id)

        if symbol_type:
            base_stmt = base_stmt.where(Symbol.symbol_type == symbol_type)

        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total = self.db.scalar(count_stmt) or 0

        stmt = base_stmt.order_by(Symbol.name.asc()).offset(offset).limit(limit)
        items = list(self.db.scalars(stmt).all())

        return items, total

    def list_dependencies(
        self,
        repository_id: str,
        edge_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[DependencyEdge], int]:
        base_stmt = select(DependencyEdge).where(DependencyEdge.repository_id == repository_id)

        if edge_type:
            base_stmt = base_stmt.where(DependencyEdge.edge_type == edge_type)

        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total = self.db.scalar(count_stmt) or 0

        stmt = base_stmt.order_by(DependencyEdge.created_at.desc()).offset(offset).limit(limit)
        items = list(self.db.scalars(stmt).all())

        return items, total
