"""
Universal Repository Archetype Detection Service

Infers repository type(s) from code structure, imports, frameworks, and patterns.
Supports multi-label classification with confidence scoring.

Archetypes:
- backend_api: REST/GraphQL APIs, web services
- fullstack_web: Combined frontend + backend
- frontend_app: Browser-based UI applications
- java_desktop_gui: Swing/AWT/JavaFX desktop applications
- cli_tool: Command-line tools and utilities
- library_sdk: Reusable libraries and SDKs
- data_pipeline: ETL, batch processing, data workflows
- ml_ai_project: Machine learning training/inference
- config_infra_repo: Infrastructure as code, configs
- generic_codebase: Fallback for unclear repos
"""

import logging
import re
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import File, Symbol

logger = logging.getLogger(__name__)


class ArchetypeService:
    """Detects repository archetypes using weighted multi-signal analysis."""

    def __init__(self, db: Session):
        self.db = db

    def detect_archetypes(self, repository_id: str, limit: int = 100) -> dict[str, Any]:
        """
        Detect repository archetypes with confidence scoring.

        Returns:
            {
                "archetypes": [
                    {"name": "backend_api", "score": 8.5, "confidence": "high", "evidence": [...]},
                    {"name": "fullstack_web", "score": 6.0, "confidence": "medium", "evidence": [...]},
                ],
                "primary_archetype": "backend_api",
                "all_signals": {...},
                "analysis_quality": "high" | "medium" | "low"
            }
        """
        try:
            # Extract signals from repository
            signals = self._extract_signals(repository_id, limit)

            # Score each archetype
            scores = self._score_archetypes(signals)

            # Build result
            archetypes = []
            for name, score_data in sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True):
                if score_data["score"] > 0:
                    archetypes.append({
                        "name": name,
                        "score": score_data["score"],
                        "confidence": self._score_to_confidence(score_data["score"]),
                        "evidence": score_data["evidence"][:6],  # Top 6 evidence items
                    })

            # Determine analysis quality
            total_files = signals.get("total_files", 0)
            total_imports = len(signals.get("imports", []))
            analysis_quality = "high" if total_files >= 10 and total_imports >= 5 else \
                             "medium" if total_files >= 3 else "low"

            return {
                "archetypes": archetypes[:5],  # Top 5 archetypes
                "primary_archetype": archetypes[0]["name"] if archetypes else "generic_codebase",
                "all_signals": signals,
                "analysis_quality": analysis_quality,
            }

        except Exception as e:
            logger.error(f"Archetype detection failed for repo {repository_id}: {e}")
            return {
                "archetypes": [{"name": "generic_codebase", "score": 1.0, "confidence": "low", "evidence": ["Analysis failed"]}],
                "primary_archetype": "generic_codebase",
                "all_signals": {},
                "analysis_quality": "low",
            }

    def _extract_signals(self, repository_id: str, limit: int) -> dict[str, Any]:
        """Extract all relevant signals from repository files."""
        signals: dict[str, Any] = {
            "paths": [],
            "extensions": {},
            "imports": [],
            "frameworks": [],
            "ui_toolkits": [],
            "function_names": [],
            "class_names": [],
            "routes": [],
            "html_assets": [],
            "config_files": [],
            "env_vars": [],
            "package_manifests": [],
            "total_files": 0,
            "has_main_method": False,
            "has_gui_patterns": False,
            "has_cli_patterns": False,
        }

        # Load files
        file_rows = list(self.db.execute(
            select(File.id, File.path, File.language, File.content, File.is_test, File.is_generated, File.is_vendor)
            .where(
                File.repository_id == repository_id,
                File.is_generated.is_(False),
                File.is_vendor.is_(False),
            )
            .limit(limit)
        ).all())

        signals["total_files"] = len(file_rows)

        # Extract path and extension signals
        for fid, path, lang, content, is_test, is_gen, is_vendor in file_rows:
            if is_test:
                continue

            path_lower = path.lower().replace("\\", "/")
            signals["paths"].append(path_lower)

            # Extension counting
            ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
            if ext:
                signals["extensions"][ext] = signals["extensions"].get(ext, 0) + 1

            # HTML assets
            if ext in (".html", ".htm"):
                signals["html_assets"].append(path)

            # Config files
            if ext in (".env", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".conf", ".properties"):
                signals["config_files"].append(path)

            # Package manifests
            basename = path.split("/")[-1].lower()
            if basename in ("package.json", "pom.xml", "build.gradle", "setup.py", "pyproject.toml", "cargo.toml", "go.mod"):
                signals["package_manifests"].append(path)

            # Content analysis for key files (limit to first 50 files with content)
            if content and len(signals["function_names"]) < 200:
                self._extract_content_signals(content, signals)

        # Extract imports from Symbol table
        try:
            imp_rows = list(self.db.execute(
                select(Symbol.imports_list)
                .join(File, Symbol.file_id == File.id)
                .where(
                    File.repository_id == repository_id,
                    Symbol.imports_list.isnot(None),
                )
                .limit(100)
            ).all())

            for (imp_json,) in imp_rows:
                if isinstance(imp_json, list):
                    signals["imports"].extend(str(x).lower() for x in imp_json)
                elif isinstance(imp_json, str):
                    try:
                        import json
                        parsed = json.loads(imp_json)
                        if isinstance(parsed, list):
                            signals["imports"].extend(str(x).lower() for x in parsed)
                    except Exception:
                        pass
        except Exception:
            pass

        # Deduplicate
        signals["imports"] = list(set(signals["imports"]))
        signals["function_names"] = list(set(signals["function_names"]))[:100]
        signals["class_names"] = list(set(signals["class_names"]))[:100]

        # Detect frameworks and UI toolkits from imports
        self._classify_imports(signals)

        return signals

    def _extract_content_signals(self, content: str, signals: dict) -> None:
        """Extract signals from file content."""
        content_lower = content.lower()

        # Function names
        fn_matches = re.findall(r'(?:def|function|const|let|var)\s+([a-zA-Z_][a-zA-Z0-9_]*)', content)
        signals["function_names"].extend(fn_matches)

        # Class names
        class_matches = re.findall(r'class\s+([A-Z][a-zA-Z0-9_]*)', content)
        signals["class_names"].extend(class_matches)

        # Java main method
        if "public static void main(string[] args)" in content_lower or \
           "public static void main(string args[])" in content_lower:
            signals["has_main_method"] = True

        # GUI patterns
        if any(kw in content_lower for kw in ("jframe", "jbutton", "jpanel", "actionlistener", "swing", "javafx")):
            signals["has_gui_patterns"] = True

        # CLI patterns
        if any(kw in content_lower for kw in ("argparse", "click.command", "typer.command", "commander", "cobra")):
            signals["has_cli_patterns"] = True

        # Route decorators
        route_matches = re.findall(
            r'@(?:app|router|blueprint|api)\s*\.\s*(?:get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
            content,
            re.IGNORECASE
        )
        signals["routes"].extend(route_matches)

        # Env vars
        env_matches = re.findall(r'(?:os\.getenv|process\.env\.)\s*[\[.(]?\s*["\']?([A-Z_]{3,})["\']?', content)
        signals["env_vars"].extend(env_matches)

    def _classify_imports(self, signals: dict) -> None:
        """Classify imports into frameworks and UI toolkits."""
        imports = signals["imports"]

        # Web frameworks
        web_frameworks = ["fastapi", "flask", "django", "express", "koa", "hapi", "nest", "spring", "springboot"]
        signals["frameworks"].extend([fw for fw in web_frameworks if any(fw in imp for imp in imports)])

        # Frontend frameworks
        frontend_frameworks = ["react", "vue", "angular", "svelte", "next", "nuxt", "remix", "gatsby"]
        signals["frameworks"].extend([fw for fw in frontend_frameworks if any(fw in imp for imp in imports)])

        # UI toolkits
        ui_toolkits = ["javax.swing", "java.awt", "javafx", "tkinter", "pyqt", "pyside", "wxpython", "kivy"]
        signals["ui_toolkits"].extend([tk for tk in ui_toolkits if any(tk in imp for imp in imports)])

        # CLI frameworks
        cli_frameworks = ["click", "typer", "argparse", "commander", "yargs", "clap", "cobra"]
        signals["frameworks"].extend([fw for fw in cli_frameworks if any(fw in imp for imp in imports)])

        # ML frameworks
        ml_frameworks = ["torch", "tensorflow", "keras", "sklearn", "transformers", "huggingface", "xgboost"]
        signals["frameworks"].extend([fw for fw in ml_frameworks if any(fw in imp for imp in imports)])

        # Data frameworks
        data_frameworks = ["pandas", "polars", "dask", "pyspark", "airflow", "prefect", "dagster"]
        signals["frameworks"].extend([fw for fw in data_frameworks if any(fw in imp for imp in imports)])

        signals["frameworks"] = list(set(signals["frameworks"]))
        signals["ui_toolkits"] = list(set(signals["ui_toolkits"]))

    def _score_archetypes(self, signals: dict) -> dict[str, dict]:
        """Score each archetype based on signals."""
        scores = {}

        # Helper functions
        def _any_in(haystack: list, needles: list) -> bool:
            return any(any(n in str(item).lower() for n in needles) for item in haystack)

        def _count_in(haystack: list, needles: list) -> int:
            return sum(1 for item in haystack if any(n in str(item).lower() for n in needles))

        def _score(archetype: str, weight: float, matched: bool, evidence: str = "") -> None:
            if archetype not in scores:
                scores[archetype] = {"score": 0.0, "evidence": []}
            if matched:
                scores[archetype]["score"] += weight
                if evidence:
                    scores[archetype]["evidence"].append(evidence)

        paths = signals.get("paths", [])
        imports = signals.get("imports", [])
        frameworks = signals.get("frameworks", [])
        ui_toolkits = signals.get("ui_toolkits", [])
        routes = signals.get("routes", [])
        html_assets = signals.get("html_assets", [])
        extensions = signals.get("extensions", {})
        function_names = signals.get("function_names", [])
        class_names = signals.get("class_names", [])

        # ── backend_api ──────────────────────────────────────────────────
        _score("backend_api", 3.0, len(routes) > 0, f"{len(routes)} API route(s)")
        _score("backend_api", 2.5, _any_in(frameworks, ["fastapi", "flask", "django", "express", "spring"]), "web framework")
        _score("backend_api", 2.0, _any_in(paths, ["route", "controller", "handler", "endpoint", "api"]), "route/handler files")
        _score("backend_api", 1.5, _any_in(paths, ["service", "usecase", "business"]), "service layer")
        _score("backend_api", 1.0, _any_in(paths, ["model", "schema", "dto", "entity"]), "data models")
        _score("backend_api", -2.0, len(html_assets) == 0 and not _any_in(frameworks, ["react", "vue", "angular"]), "")

        # ── fullstack_web ────────────────────────────────────────────────
        _score("fullstack_web", 3.0, len(routes) > 0 and len(html_assets) > 0, "routes + HTML assets")
        _score("fullstack_web", 2.5, _any_in(frameworks, ["next", "nuxt", "remix", "sveltekit"]), "fullstack framework")
        _score("fullstack_web", 2.0, _any_in(frameworks, ["react", "vue"]) and _any_in(frameworks, ["fastapi", "flask", "express"]), "frontend + backend frameworks")
        _score("fullstack_web", 1.5, extensions.get(".tsx", 0) + extensions.get(".jsx", 0) >= 3, "multiple frontend files")

        # ── frontend_app ─────────────────────────────────────────────────
        _score("frontend_app", 3.0, len(html_assets) >= 1, f"{len(html_assets)} HTML file(s)")
        _score("frontend_app", 2.5, _any_in(frameworks, ["react", "vue", "angular", "svelte"]), "frontend framework")
        _score("frontend_app", 2.0, extensions.get(".tsx", 0) + extensions.get(".jsx", 0) + extensions.get(".vue", 0) >= 5, "multiple UI components")
        _score("frontend_app", 1.5, _any_in(paths, ["component", "page", "view", "layout", "router"]), "frontend structure")
        _score("frontend_app", 1.0, extensions.get(".css", 0) + extensions.get(".scss", 0) >= 2, "stylesheets")
        _score("frontend_app", -2.0, len(routes) > 3, "")

        # ── java_desktop_gui ─────────────────────────────────────────────
        _score("java_desktop_gui", 4.0, len(ui_toolkits) > 0, f"UI toolkit: {', '.join(ui_toolkits)}")
        _score("java_desktop_gui", 3.5, signals.get("has_gui_patterns", False), "GUI patterns (JFrame, JButton, etc.)")
        _score("java_desktop_gui", 3.0, signals.get("has_main_method", False), "Java main() method")
        _score("java_desktop_gui", 2.5, _any_in(class_names, ["login", "home", "main", "launcher", "screen", "frame", "dialog", "panel"]), "GUI screen classes")
        _score("java_desktop_gui", 2.0, extensions.get(".java", 0) >= 5, f"{extensions.get('.java', 0)} Java files")
        _score("java_desktop_gui", 1.5, _any_in(function_names + class_names, ["actionlistener", "actionperformed", "mouselistener", "keylistener"]), "event listeners")
        _score("java_desktop_gui", -3.0, len(html_assets) > 0 or _any_in(frameworks, ["spring", "springboot"]), "")

        # ── cli_tool ─────────────────────────────────────────────────────
        _score("cli_tool", 3.5, signals.get("has_cli_patterns", False), "CLI framework patterns")
        _score("cli_tool", 3.0, _any_in(frameworks, ["click", "typer", "argparse", "commander", "cobra", "clap"]), "CLI framework")
        _score("cli_tool", 2.5, _any_in(paths, ["cli", "cmd", "command", "tool", "bin/"]), "CLI paths")
        _score("cli_tool", 2.0, _any_in(function_names, ["main", "cli", "run", "execute", "parse_args", "command"]), "CLI entry functions")
        _score("cli_tool", -2.5, len(routes) > 0 or len(html_assets) > 0, "")

        # ── library_sdk ──────────────────────────────────────────────────
        _score("library_sdk", 3.0, len(signals.get("package_manifests", [])) > 0, "package manifest")
        _score("library_sdk", 2.5, _any_in(paths, ["__init__.py", "index.js", "lib/", "src/lib/", "pkg/"]), "library structure")
        _score("library_sdk", 2.0, _any_in(function_names + class_names, ["adapter", "provider", "client", "api", "interface", "factory"]), "SDK patterns")
        _score("library_sdk", 1.5, _any_in(paths, ["test", "tests", "spec"]) and not _any_in(paths, ["app", "server", "main"]), "tests but no app")
        _score("library_sdk", -2.0, len(routes) > 0 or signals.get("has_main_method", False), "")

        # ── data_pipeline ────────────────────────────────────────────────
        _score("data_pipeline", 3.0, _any_in(frameworks, ["airflow", "prefect", "dagster", "luigi"]), "pipeline framework")
        _score("data_pipeline", 2.5, _any_in(paths, ["pipeline", "etl", "transform", "ingest", "batch", "job"]), "pipeline paths")
        _score("data_pipeline", 2.0, _any_in(frameworks, ["pandas", "polars", "dask", "pyspark"]), "data processing library")
        _score("data_pipeline", 1.5, _any_in(function_names, ["extract", "transform", "load", "process", "ingest", "pipeline"]), "ETL functions")
        _score("data_pipeline", 1.0, extensions.get(".csv", 0) + extensions.get(".json", 0) >= 3, "data files")

        # ── ml_ai_project ────────────────────────────────────────────────
        _score("ml_ai_project", 3.5, _any_in(frameworks, ["torch", "tensorflow", "keras", "transformers"]), "ML framework")
        _score("ml_ai_project", 3.0, _any_in(paths, ["model", "train", "inference", "predict", "embedding"]), "ML paths")
        _score("ml_ai_project", 2.5, _any_in(function_names, ["train", "fit", "predict", "evaluate", "infer", "embed"]), "ML functions")
        _score("ml_ai_project", 2.0, _any_in(frameworks, ["sklearn", "xgboost", "lightgbm"]), "ML library")
        _score("ml_ai_project", 1.5, _any_in(paths, ["dataset", "data/", "checkpoint", "weights"]), "ML artifacts")

        # ── config_infra_repo ────────────────────────────────────────────
        _score("config_infra_repo", 3.0, extensions.get(".yaml", 0) + extensions.get(".yml", 0) >= 5, "many YAML files")
        _score("config_infra_repo", 2.5, _any_in(paths, ["terraform", "ansible", "kubernetes", "k8s", "helm", "docker-compose"]), "IaC tools")
        _score("config_infra_repo", 2.0, _any_in(paths, ["deployment", "infra", "infrastructure", "ops", "devops"]), "infra paths")
        _score("config_infra_repo", 1.5, extensions.get(".tf", 0) + extensions.get(".hcl", 0) >= 2, "Terraform files")
        _score("config_infra_repo", -2.0, extensions.get(".py", 0) + extensions.get(".js", 0) + extensions.get(".java", 0) >= 10, "")

        # ── generic_codebase ─────────────────────────────────────────────
        _score("generic_codebase", 1.0, signals.get("total_files", 0) > 0, "files present")
        _score("generic_codebase", 0.5, len(imports) > 0, "imports detected")

        return scores

    def _score_to_confidence(self, score: float) -> str:
        """Convert numeric score to confidence label."""
        if score >= 5.0:
            return "high"
        elif score >= 2.5:
            return "medium"
        else:
            return "low"
