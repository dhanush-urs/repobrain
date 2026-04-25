"""
Universal Entrypoint Detection Service

Detects executable entrypoints across different repository archetypes.
Returns multi-candidate results with confidence scoring.

Penalizes helper/utility files (config, db, mysql, util, helper, constants, settings).
Prefers actual executable entrypoints over infrastructure code.
"""

import logging
import re
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import File

logger = logging.getLogger(__name__)


class EntrypointService:
    """Detects repository entrypoints with archetype-aware logic."""

    # Helper/utility keywords that should be penalized
    HELPER_KEYWORDS = [
        "config", "configuration", "settings", "constants", "const",
        "db", "database", "mysql", "postgres", "mongo", "redis",
        "util", "utils", "utility", "utilities", "helper", "helpers",
        "common", "shared", "base", "abstract",
    ]

    # Entrypoint stem names by priority
    ENTRYPOINT_STEMS = {
        "high": ["main", "app", "server", "index", "start", "run", "launcher", "bootstrap"],
        "medium": ["init", "__init__", "entry", "startup", "begin"],
        "low": ["manage", "wsgi", "asgi"],
    }

    def __init__(self, db: Session):
        self.db = db

    def detect_entrypoints(
        self,
        repository_id: str,
        archetype: str = "generic_codebase",
        limit: int = 100
    ) -> dict[str, Any]:
        """
        Detect entrypoints with archetype-aware logic.

        Args:
            repository_id: Repository ID
            archetype: Primary archetype (from ArchetypeService)
            limit: Max files to analyze

        Returns:
            {
                "primary_entrypoint": {"path": "...", "type": "...", "confidence": "...", "reasons": [...]},
                "candidate_entrypoints": [...],
                "analysis_quality": "high" | "medium" | "low"
            }
        """
        try:
            # Load files
            file_rows = list(self.db.execute(
                select(File.id, File.path, File.language, File.content, File.line_count, File.is_test)
                .where(
                    File.repository_id == repository_id,
                    File.is_generated.is_(False),
                    File.is_vendor.is_(False),
                    File.is_test.is_(False),
                )
                .limit(limit)
            ).all())

            if not file_rows:
                return self._empty_result()

            # Score candidates
            candidates = []
            for fid, path, lang, content, line_count, is_test in file_rows:
                score_data = self._score_entrypoint_candidate(
                    path, lang, content, line_count, archetype
                )
                if score_data["score"] > 0:
                    candidates.append({
                        "file_id": fid,
                        "path": path,
                        "type": score_data["type"],
                        "score": score_data["score"],
                        "confidence": self._score_to_confidence(score_data["score"]),
                        "reasons": score_data["reasons"],
                    })

            # Sort by score
            candidates.sort(key=lambda x: x["score"], reverse=True)

            # Determine analysis quality
            analysis_quality = "high" if len(candidates) >= 3 else \
                             "medium" if len(candidates) >= 1 else "low"

            # Select primary
            primary = candidates[0] if candidates else None

            # If primary confidence is low and we have multiple candidates, mark as uncertain
            if primary and primary["confidence"] == "low" and len(candidates) > 1:
                primary["reasons"].append("Low confidence — see candidate list")

            return {
                "primary_entrypoint": primary,
                "candidate_entrypoints": candidates[:5],  # Top 5
                "analysis_quality": analysis_quality,
            }

        except Exception as e:
            logger.error(f"Entrypoint detection failed for repo {repository_id}: {e}")
            return self._empty_result()

    def _score_entrypoint_candidate(
        self,
        path: str,
        language: str,
        content: str | None,
        line_count: int,
        archetype: str
    ) -> dict[str, Any]:
        """Score a single file as potential entrypoint."""
        score = 0.0
        reasons = []
        entrypoint_type = "unknown"

        path_lower = path.lower().replace("\\", "/")
        parts = path_lower.split("/")
        basename = parts[-1]
        stem = basename.rsplit(".", 1)[0] if "." in basename else basename

        # Penalize helper/utility files heavily
        if any(kw in path_lower for kw in self.HELPER_KEYWORDS):
            penalty = -10.0
            # Exception: if it's the ONLY file with main(), still consider it
            if content and "public static void main" not in content.lower():
                score += penalty
                reasons.append(f"Penalized: helper/utility file ({stem})")

        # Archetype-specific scoring
        if archetype == "backend_api":
            score_data = self._score_backend_api(path_lower, stem, content, reasons)
            score += score_data["score"]
            entrypoint_type = score_data["type"]

        elif archetype == "frontend_app":
            score_data = self._score_frontend_app(path_lower, basename, content, reasons)
            score += score_data["score"]
            entrypoint_type = score_data["type"]

        elif archetype == "java_desktop_gui":
            score_data = self._score_java_desktop_gui(path_lower, stem, content, reasons)
            score += score_data["score"]
            entrypoint_type = score_data["type"]

        elif archetype == "cli_tool":
            score_data = self._score_cli_tool(path_lower, stem, content, reasons)
            score += score_data["score"]
            entrypoint_type = score_data["type"]

        elif archetype == "library_sdk":
            score_data = self._score_library_sdk(path_lower, basename, content, reasons)
            score += score_data["score"]
            entrypoint_type = score_data["type"]

        elif archetype == "ml_ai_project":
            score_data = self._score_ml_ai(path_lower, stem, content, reasons)
            score += score_data["score"]
            entrypoint_type = score_data["type"]

        else:
            # Generic scoring
            score_data = self._score_generic(path_lower, stem, content, reasons)
            score += score_data["score"]
            entrypoint_type = score_data["type"]

        # Boost by line count (substantial files more likely to be entrypoints)
        if line_count and line_count >= 50:
            score += 1.0
            reasons.append(f"Substantial file ({line_count} lines)")

        # Depth penalty (prefer root-level files)
        depth = len(parts) - 1
        if depth <= 2:
            score += 2.0
            reasons.append("Root-level file")
        elif depth <= 4:
            score += 0.5

        return {
            "score": max(score, 0.0),  # Never negative
            "type": entrypoint_type,
            "reasons": reasons,
        }

    def _score_backend_api(self, path: str, stem: str, content: str | None, reasons: list) -> dict:
        """Score for backend_api archetype."""
        score = 0.0
        etype = "backend_entrypoint"

        # High priority stems
        if stem in self.ENTRYPOINT_STEMS["high"]:
            score += 5.0
            reasons.append(f"Backend entrypoint name: {stem}")
            etype = "backend_entrypoint"

        # Route registration patterns
        if content:
            if re.search(r'@(?:app|router|blueprint)\s*\.', content, re.IGNORECASE):
                score += 4.0
                reasons.append("Route registration detected")
                etype = "route_entrypoint"

            if re.search(r'(?:FastAPI|Flask|Express|app)\s*\(', content, re.IGNORECASE):
                score += 3.0
                reasons.append("Framework initialization")

        # Path hints
        if any(kw in path for kw in ("app", "server", "api", "main")):
            score += 2.0
            reasons.append("Backend path keyword")

        return {"score": score, "type": etype}

    def _score_frontend_app(self, path: str, basename: str, content: str | None, reasons: list) -> dict:
        """Score for frontend_app archetype."""
        score = 0.0
        etype = "frontend_entrypoint"

        # HTML entrypoints
        if basename in ("index.html", "index.htm"):
            score += 6.0
            reasons.append("HTML entrypoint")
            etype = "html_entrypoint"

        # JS/TS entrypoints
        if basename in ("main.tsx", "main.jsx", "main.js", "main.ts", "index.tsx", "index.jsx", "index.js", "index.ts"):
            score += 5.0
            reasons.append("Frontend bootstrap file")
            etype = "js_entrypoint"

        # App component
        if basename in ("app.tsx", "app.jsx", "app.js", "app.ts"):
            score += 4.0
            reasons.append("Root app component")
            etype = "app_component"

        # Router
        if "router" in path or "routes" in path:
            score += 2.0
            reasons.append("Router file")

        return {"score": score, "type": etype}

    def _score_java_desktop_gui(self, path: str, stem: str, content: str | None, reasons: list) -> dict:
        """Score for java_desktop_gui archetype."""
        score = 0.0
        etype = "gui_entrypoint"

        # Java main method (highest priority)
        if content:
            if re.search(r'public\s+static\s+void\s+main\s*\(\s*string\s*\[\s*\]\s*args', content, re.IGNORECASE):
                score += 8.0
                reasons.append("Java main() method")
                etype = "java_main"

            # GUI launch patterns
            if re.search(r'new\s+(Login|Home|Main|Launcher|Welcome)\s*\(', content, re.IGNORECASE):
                score += 5.0
                reasons.append("GUI screen instantiation")
                etype = "gui_launcher"

            # JFrame/UI root
            if re.search(r'extends\s+JFrame|new\s+JFrame', content, re.IGNORECASE):
                score += 3.0
                reasons.append("JFrame root screen")

        # Class name hints (Login, Home, Main, Launcher)
        if stem.lower() in ("login", "home", "main", "launcher", "welcome", "mainframe", "mainwindow"):
            score += 4.0
            reasons.append(f"GUI entrypoint class name: {stem}")
            etype = "gui_screen"

        # Avoid DB helpers
        if any(kw in stem.lower() for kw in ("mysql", "database", "db", "connection", "query")):
            score -= 5.0
            reasons.append("DB helper — not entrypoint")

        return {"score": score, "type": etype}

    def _score_cli_tool(self, path: str, stem: str, content: str | None, reasons: list) -> dict:
        """Score for cli_tool archetype."""
        score = 0.0
        etype = "cli_entrypoint"

        # __main__ module
        if "__main__" in path:
            score += 6.0
            reasons.append("__main__ module")
            etype = "cli_main"

        # CLI stems
        if stem in ("cli", "main", "run", "command", "cmd"):
            score += 4.0
            reasons.append(f"CLI entrypoint name: {stem}")

        # CLI patterns in content
        if content:
            if re.search(r'if\s+__name__\s*==\s*["\']__main__["\']', content):
                score += 5.0
                reasons.append("Python __main__ guard")

            if re.search(r'@click\.command|@typer\.command|argparse\.ArgumentParser', content, re.IGNORECASE):
                score += 4.0
                reasons.append("CLI framework usage")

        return {"score": score, "type": etype}

    def _score_library_sdk(self, path: str, basename: str, content: str | None, reasons: list) -> dict:
        """Score for library_sdk archetype."""
        score = 0.0
        etype = "library_entrypoint"

        # Package entrypoints
        if basename in ("__init__.py", "index.js", "index.ts", "mod.rs", "lib.rs"):
            score += 5.0
            reasons.append("Package entrypoint")
            etype = "package_entry"

        # Public API modules
        if "api" in path or "public" in path or "exports" in path:
            score += 2.0
            reasons.append("Public API module")

        return {"score": score, "type": etype}

    def _score_ml_ai(self, path: str, stem: str, content: str | None, reasons: list) -> dict:
        """Score for ml_ai_project archetype."""
        score = 0.0
        etype = "ml_entrypoint"

        # ML entry scripts
        if stem in ("train", "inference", "predict", "serve", "pipeline", "run"):
            score += 4.0
            reasons.append(f"ML entrypoint: {stem}")
            etype = "ml_script"

        # Main training/inference
        if "train" in path or "inference" in path or "predict" in path:
            score += 2.0
            reasons.append("ML workflow path")

        return {"score": score, "type": etype}

    def _score_generic(self, path: str, stem: str, content: str | None, reasons: list) -> dict:
        """Generic scoring fallback."""
        score = 0.0
        etype = "generic_entrypoint"

        # High priority stems
        if stem in self.ENTRYPOINT_STEMS["high"]:
            score += 4.0
            reasons.append(f"Entrypoint name: {stem}")

        # Medium priority stems
        elif stem in self.ENTRYPOINT_STEMS["medium"]:
            score += 2.0
            reasons.append(f"Possible entrypoint: {stem}")

        # Low priority stems
        elif stem in self.ENTRYPOINT_STEMS["low"]:
            score += 1.0
            reasons.append(f"Low-priority entrypoint: {stem}")

        return {"score": score, "type": etype}

    def _score_to_confidence(self, score: float) -> str:
        """Convert score to confidence label."""
        if score >= 6.0:
            return "high"
        elif score >= 3.0:
            return "medium"
        else:
            return "low"

    def _empty_result(self) -> dict:
        """Return empty result structure."""
        return {
            "primary_entrypoint": None,
            "candidate_entrypoints": [],
            "analysis_quality": "low",
        }
