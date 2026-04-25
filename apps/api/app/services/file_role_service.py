"""
Universal File Role Classification Service

Classifies files into semantic roles across different repository archetypes.
Uses multi-signal analysis: path, extension, imports, content patterns, usage references.

Roles:
- entrypoint: Main launch/bootstrap files
- route: HTTP route handlers
- handler: Request/event handlers
- controller: MVC controllers
- service: Business logic services
- model: Data models/schemas
- schema: API schemas/DTOs
- db: Database utilities
- config: Configuration files
- ui_screen: GUI screens/windows
- component: UI components
- style: Stylesheets
- asset: Static assets
- test: Test files
- utility: Helper utilities
- script: Executable scripts
- cli_command: CLI command handlers
- library_export: Library public API
- data: Data files
- generated: Generated code
- vendor: Third-party code
- unknown: Unclear role
"""

import logging
import re
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import File, Symbol, DependencyEdge

logger = logging.getLogger(__name__)


class FileRoleService:
    """Universal file role classification across repository archetypes."""

    # Role priority (higher = more specific, wins in conflicts)
    ROLE_PRIORITY = {
        "entrypoint": 10,
        "route": 9,
        "handler": 8,
        "controller": 8,
        "service": 7,
        "model": 6,
        "schema": 6,
        "ui_screen": 8,
        "component": 7,
        "cli_command": 8,
        "library_export": 9,
        "config": 5,
        "db": 5,
        "utility": 4,
        "script": 6,
        "style": 3,
        "asset": 2,
        "data": 2,
        "test": 1,
        "generated": 0,
        "vendor": 0,
        "unknown": 0,
    }

    def __init__(self, db: Session):
        self.db = db

    def classify_file_roles(
        self,
        repository_id: str,
        archetype: str = "generic_codebase",
        limit: int = 200
    ) -> dict[str, dict]:
        """
        Classify all files in repository by role.
        
        Returns:
        {
            file_id: {
                "role": "service",
                "confidence": "high" | "medium" | "low",
                "reasons": ["service path keyword", "imports business logic"],
                "signals": {...}
            }
        }
        """
        try:
            # Load files
            file_rows = list(self.db.execute(
                select(File.id, File.path, File.language, File.content, File.line_count, 
                       File.is_test, File.is_generated, File.is_vendor)
                .where(File.repository_id == repository_id)
                .limit(limit)
            ).all())

            if not file_rows:
                return {}

            # Load symbols for content analysis
            symbol_data = self._load_symbol_data(repository_id)
            
            # Load dependency data for usage analysis
            dependency_data = self._load_dependency_data(repository_id)

            results = {}
            for fid, path, lang, content, line_count, is_test, is_gen, is_vendor in file_rows:
                role_data = self._classify_single_file(
                    fid, path, lang, content, line_count, is_test, is_gen, is_vendor,
                    archetype, symbol_data, dependency_data
                )
                results[fid] = role_data

            return results

        except Exception as e:
            logger.error(f"classify_file_roles failed for repo {repository_id}: {e}")
            return {}

    def _load_symbol_data(self, repository_id: str) -> dict:
        """Load symbol data for content analysis."""
        try:
            symbol_rows = list(self.db.execute(
                select(Symbol.file_id, Symbol.name, Symbol.symbol_type, Symbol.imports_list)
                .join(File, File.id == Symbol.file_id)
                .where(Symbol.repository_id == repository_id)
                .limit(500)
            ).all())

            # Group by file_id
            by_file: dict[str, dict] = {}
            for fid, name, stype, imports in symbol_rows:
                if fid not in by_file:
                    by_file[fid] = {"symbols": [], "imports": []}
                by_file[fid]["symbols"].append({"name": name, "type": stype})
                if imports:
                    if isinstance(imports, list):
                        by_file[fid]["imports"].extend(imports)
                    elif isinstance(imports, str):
                        try:
                            import json
                            parsed = json.loads(imports)
                            if isinstance(parsed, list):
                                by_file[fid]["imports"].extend(parsed)
                        except Exception:
                            pass

            return by_file

        except Exception as e:
            logger.warning(f"_load_symbol_data failed: {e}")
            return {}

    def _load_dependency_data(self, repository_id: str) -> dict:
        """Load dependency edge data for usage analysis."""
        try:
            edge_rows = list(self.db.execute(
                select(DependencyEdge.source_file_id, DependencyEdge.target_file_id, 
                       DependencyEdge.edge_type, DependencyEdge.target_ref)
                .where(
                    DependencyEdge.repository_id == repository_id,
                    DependencyEdge.source_file_id.isnot(None),
                    DependencyEdge.target_file_id.isnot(None),
                )
                .limit(1000)
            ).all())

            # Build usage maps
            incoming: dict[str, list] = {}  # file_id -> [files that depend on it]
            outgoing: dict[str, list] = {}  # file_id -> [files it depends on]

            for src, tgt, etype, tref in edge_rows:
                outgoing.setdefault(src, []).append({"target": tgt, "type": etype, "ref": tref})
                incoming.setdefault(tgt, []).append({"source": src, "type": etype, "ref": tref})

            return {"incoming": incoming, "outgoing": outgoing}

        except Exception as e:
            logger.warning(f"_load_dependency_data failed: {e}")
            return {"incoming": {}, "outgoing": {}}

    def _classify_single_file(
        self,
        file_id: str,
        path: str,
        language: str,
        content: str | None,
        line_count: int | None,
        is_test: bool,
        is_generated: bool,
        is_vendor: bool,
        archetype: str,
        symbol_data: dict,
        dependency_data: dict
    ) -> dict:
        """Classify a single file's role."""
        
        # Early exits for obvious cases
        if is_test:
            return {"role": "test", "confidence": "high", "reasons": ["marked as test"], "signals": {}}
        if is_generated:
            return {"role": "generated", "confidence": "high", "reasons": ["marked as generated"], "signals": {}}
        if is_vendor:
            return {"role": "vendor", "confidence": "high", "reasons": ["marked as vendor"], "signals": {}}

        # Extract signals
        signals = self._extract_file_signals(
            path, language, content, line_count, symbol_data.get(file_id, {}), 
            dependency_data, file_id
        )

        # Score roles
        role_scores = self._score_file_roles(signals, archetype)

        # Select best role
        if not role_scores:
            return {"role": "unknown", "confidence": "low", "reasons": ["no clear signals"], "signals": signals}

        best_role = max(role_scores.keys(), key=lambda r: role_scores[r]["score"])
        best_data = role_scores[best_role]

        confidence = "high" if best_data["score"] >= 5.0 else \
                    "medium" if best_data["score"] >= 2.0 else "low"

        return {
            "role": best_role,
            "confidence": confidence,
            "reasons": best_data["reasons"],
            "signals": signals,
        }

    def _extract_file_signals(
        self,
        path: str,
        language: str,
        content: str | None,
        line_count: int | None,
        symbol_info: dict,
        dependency_data: dict,
        file_id: str
    ) -> dict:
        """Extract all relevant signals from a file."""
        path_lower = path.lower().replace("\\", "/")
        parts = path_lower.split("/")
        basename = parts[-1]
        stem = basename.rsplit(".", 1)[0] if "." in basename else basename
        ext = "." + basename.rsplit(".", 1)[-1] if "." in basename else ""

        signals = {
            "path": path_lower,
            "basename": basename,
            "stem": stem,
            "extension": ext,
            "language": language or "",
            "depth": len(parts) - 1,
            "line_count": line_count or 0,
            "symbols": symbol_info.get("symbols", []),
            "imports": symbol_info.get("imports", []),
            "incoming_deps": len(dependency_data.get("incoming", {}).get(file_id, [])),
            "outgoing_deps": len(dependency_data.get("outgoing", {}).get(file_id, [])),
            "content_patterns": [],
        }

        # Path-based signals
        signals["path_keywords"] = self._extract_path_keywords(path_lower)

        # Content-based signals (if available)
        if content:
            signals["content_patterns"] = self._extract_content_patterns(content, language)

        return signals

    def _extract_path_keywords(self, path: str) -> list[str]:
        """Extract semantic keywords from file path."""
        keywords = []
        
        # Common role keywords
        role_keywords = {
            "entrypoint": ["main", "app", "server", "index", "start", "run", "launcher", "bootstrap"],
            "route": ["route", "routes", "router", "endpoint", "api"],
            "handler": ["handler", "handlers", "controller", "controllers"],
            "service": ["service", "services", "usecase", "use_case", "business", "logic"],
            "model": ["model", "models", "entity", "entities", "orm"],
            "schema": ["schema", "schemas", "dto", "dtos", "types"],
            "db": ["db", "database", "mysql", "postgres", "mongo", "redis", "connection", "query"],
            "config": ["config", "configuration", "settings", "constants", "env"],
            "ui_screen": ["screen", "window", "frame", "dialog", "panel", "form"],
            "component": ["component", "components", "widget", "widgets"],
            "utility": ["util", "utils", "utility", "utilities", "helper", "helpers", "common"],
            "script": ["script", "scripts", "bin", "tools"],
            "cli_command": ["cli", "cmd", "command", "commands"],
            "library_export": ["__init__", "index", "lib", "exports"],
        }

        for role, kwords in role_keywords.items():
            if any(kw in path for kw in kwords):
                keywords.append(role)

        return keywords

    def _extract_content_patterns(self, content: str, language: str) -> list[str]:
        """Extract patterns from file content."""
        patterns = []
        content_lower = content.lower()

        # Language-specific patterns
        if language == "python":
            if "if __name__ == \"__main__\"" in content_lower:
                patterns.append("python_main")
            if re.search(r'@(?:app|router|blueprint)\s*\.', content, re.IGNORECASE):
                patterns.append("route_decorator")
            if re.search(r'class\s+\w+\(.*model.*\)', content, re.IGNORECASE):
                patterns.append("model_class")
            if re.search(r'@click\.command|@typer\.command', content, re.IGNORECASE):
                patterns.append("cli_command")

        elif language in ("javascript", "typescript"):
            if re.search(r'export\s+default|module\.exports', content, re.IGNORECASE):
                patterns.append("module_export")
            if re.search(r'app\.(?:get|post|put|delete)', content, re.IGNORECASE):
                patterns.append("route_handler")
            if re.search(r'React\.Component|extends Component', content, re.IGNORECASE):
                patterns.append("react_component")

        elif language == "java":
            if re.search(r'public\s+static\s+void\s+main', content, re.IGNORECASE):
                patterns.append("java_main")
            if re.search(r'extends\s+JFrame|new\s+JFrame', content, re.IGNORECASE):
                patterns.append("swing_frame")
            if re.search(r'@Entity|@Table', content, re.IGNORECASE):
                patterns.append("jpa_entity")
            if re.search(r'ActionListener|actionPerformed', content, re.IGNORECASE):
                patterns.append("action_listener")

        # Framework patterns
        if any(fw in content_lower for fw in ("fastapi", "flask", "django", "express")):
            patterns.append("web_framework")
        if any(ui in content_lower for ui in ("swing", "javafx", "tkinter", "pyqt")):
            patterns.append("gui_toolkit")
        if any(db in content_lower for db in ("mysql", "postgres", "mongodb", "sqlite")):
            patterns.append("database_access")

        return patterns

    def _score_file_roles(self, signals: dict, archetype: str) -> dict[str, dict]:
        """Score each possible role for the file."""
        scores = {}

        def _score(role: str, weight: float, matched: bool, reason: str = "") -> None:
            if not matched:
                return
            if role not in scores:
                scores[role] = {"score": 0.0, "reasons": []}
            scores[role]["score"] += weight
            if reason:
                scores[role]["reasons"].append(reason)

        path_kw = signals.get("path_keywords", [])
        content_pat = signals.get("content_patterns", [])
        ext = signals.get("extension", "")
        stem = signals.get("stem", "")
        imports = signals.get("imports", [])
        incoming = signals.get("incoming_deps", 0)
        outgoing = signals.get("outgoing_deps", 0)

        # ── entrypoint ───────────────────────────────────────────────────────
        _score("entrypoint", 5.0, "entrypoint" in path_kw, "entrypoint path keyword")
        _score("entrypoint", 4.0, "python_main" in content_pat, "Python __main__ guard")
        _score("entrypoint", 4.0, "java_main" in content_pat, "Java main() method")
        _score("entrypoint", 3.0, stem in ("main", "app", "server", "index"), f"entrypoint name: {stem}")
        _score("entrypoint", 2.0, signals.get("depth", 0) <= 2, "root-level file")

        # ── route ────────────────────────────────────────────────────────────
        _score("route", 5.0, "route" in path_kw, "route path keyword")
        _score("route", 4.0, "route_decorator" in content_pat, "route decorator")
        _score("route", 4.0, "route_handler" in content_pat, "route handler pattern")
        _score("route", 3.0, "web_framework" in content_pat, "web framework usage")

        # ── service ──────────────────────────────────────────────────────────
        _score("service", 4.0, "service" in path_kw, "service path keyword")
        _score("service", 3.0, outgoing >= 2, f"depends on {outgoing} files")
        _score("service", 2.0, incoming >= 1, f"used by {incoming} files")
        _score("service", 2.0, signals.get("line_count", 0) >= 100, "substantial file")

        # ── model ────────────────────────────────────────────────────────────
        _score("model", 4.0, "model" in path_kw, "model path keyword")
        _score("model", 4.0, "model_class" in content_pat, "model class pattern")
        _score("model", 3.0, "jpa_entity" in content_pat, "JPA entity annotation")
        _score("model", 2.0, "schema" in path_kw, "schema path keyword")

        # ── ui_screen (Java GUI) ─────────────────────────────────────────────
        if archetype == "java_desktop_gui":
            _score("ui_screen", 5.0, "swing_frame" in content_pat, "Swing JFrame")
            _score("ui_screen", 4.0, "action_listener" in content_pat, "ActionListener")
            _score("ui_screen", 3.0, "ui_screen" in path_kw, "screen path keyword")
            _score("ui_screen", 3.0, "gui_toolkit" in content_pat, "GUI toolkit usage")
            _score("ui_screen", 2.0, stem.lower() in ("login", "home", "main", "welcome"), f"GUI screen name: {stem}")

        # ── component (Frontend) ─────────────────────────────────────────────
        if archetype in ("frontend_app", "fullstack_web"):
            _score("component", 4.0, "react_component" in content_pat, "React component")
            _score("component", 3.0, "component" in path_kw, "component path keyword")
            _score("component", 3.0, ext in (".tsx", ".jsx", ".vue", ".svelte"), f"UI component extension: {ext}")
            _score("component", 2.0, "module_export" in content_pat, "module export")

        # ── cli_command ──────────────────────────────────────────────────────
        if archetype == "cli_tool":
            _score("cli_command", 5.0, "cli_command" in content_pat, "CLI command decorator")
            _score("cli_command", 4.0, "cli_command" in path_kw, "CLI path keyword")
            _score("cli_command", 3.0, "python_main" in content_pat, "Python main guard")

        # ── config ───────────────────────────────────────────────────────────
        _score("config", 5.0, ext in (".env", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".conf"), f"config extension: {ext}")
        _score("config", 4.0, "config" in path_kw, "config path keyword")
        _score("config", 3.0, stem.startswith(".env"), "env file")

        # ── db ───────────────────────────────────────────────────────────────
        _score("db", 4.0, "db" in path_kw, "database path keyword")
        _score("db", 3.0, "database_access" in content_pat, "database access patterns")

        # ── utility ──────────────────────────────────────────────────────────
        _score("utility", 3.0, "utility" in path_kw, "utility path keyword")
        _score("utility", 2.0, stem in ("util", "utils", "helper", "common"), f"utility name: {stem}")

        # ── style ────────────────────────────────────────────────────────────
        _score("style", 5.0, ext in (".css", ".scss", ".sass", ".less"), f"stylesheet extension: {ext}")

        # ── asset ────────────────────────────────────────────────────────────
        _score("asset", 4.0, ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico"), f"image extension: {ext}")
        _score("asset", 3.0, ext in (".html", ".htm"), f"HTML extension: {ext}")

        # ── data ─────────────────────────────────────────────────────────────
        _score("data", 4.0, ext in (".json", ".csv", ".xml", ".txt", ".sql"), f"data extension: {ext}")

        # ── library_export ───────────────────────────────────────────────────
        if archetype == "library_sdk":
            _score("library_export", 5.0, stem in ("__init__", "index", "lib"), f"library entry: {stem}")
            _score("library_export", 4.0, "module_export" in content_pat, "module export")

        return scores