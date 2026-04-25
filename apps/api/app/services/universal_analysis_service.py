"""
Universal Analysis Service - RepoBrain 10.0 Core Intelligence Engine

Provides canonical repository intelligence snapshot that powers all product surfaces:
- Overview, Ask Repo, Knowledge Graph, Execution Map, PR Impact, Search, Files

Single source of truth for:
- Repository archetypes with evidence
- Multi-language analysis
- Entrypoint detection with confidence
- File role classification
- 3-layer graph intelligence (structural → semantic → runtime)
- Graph health assessment
- Execution flow strategies
- Weak repo mode detection

Architecture: GitHub-grade universal platform, not one-repo demo.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.models import File, Symbol, DependencyEdge, Repository
from app.services.archetype_service import ArchetypeService
from app.services.entrypoint_service import EntrypointService
from app.services.file_role_service import FileRoleService
from app.services.graph_service import GraphService
from app.services.graph_engine import GraphEngine

logger = logging.getLogger(__name__)


class UniversalAnalysisService:
    """
    GitHub-grade universal repository intelligence engine.
    
    Provides canonical analysis snapshot consumed by all product surfaces.
    Handles graceful degradation for sparse/weak repositories.
    """

    def __init__(self, db: Session):
        self.db = db
        self.archetype_svc = ArchetypeService(db)
        self.entrypoint_svc = EntrypointService(db)
        self.file_role_svc = FileRoleService(db)
        self.graph_svc = GraphService(db)
        self.graph_engine = GraphEngine(db)

    def get_analysis_snapshot(self, repository_id: str) -> Dict[str, Any]:
        """
        Generate canonical universal analysis snapshot for repository.
        
        This is the single source of truth consumed by:
        - Overview, Ask Repo, Knowledge Graph, Execution Map
        - PR Impact, Search, Files pages
        
        Returns comprehensive intelligence with graceful degradation.
        Never raises - returns partial data with limitations on failure.
        """
        snapshot = {
            "repository_id": repository_id,
            "timestamp": datetime.utcnow().isoformat(),
            "version": "10.0",
            
            # Core Intelligence
            "languages_detected": [],
            "frameworks_detected": [],
            "integrations_detected": [],
            "repo_archetypes": [],
            "primary_archetype": "generic_codebase",
            
            # Graph Intelligence
            "graph_health": {},
            "graph_stats": {},
            "edge_type_counts": {},
            "sparse_graph": True,
            "weak_evidence": True,
            
            # Entrypoint Intelligence
            "entrypoints": {
                "primary_entrypoint": None,
                "candidate_entrypoints": [],
                "confidence": "low",
                "reasons": [],
            },
            
            # File Intelligence
            "file_role_summary": {},
            "file_intelligence_summary": {},
            "important_files": [],
            
            # Execution Intelligence
            "dominant_subsystems": [],
            "execution_hints": {},
            "flow_strategy": "generic",
            
            # Quality Metrics
            "analysis_coverage": {},
            "overall_confidence": "low",
            "limitations": [],
            "weak_repo_mode": False,
            "monorepo_detected": False,
        }

        try:
            # Load repository metadata
            repo = self.db.scalar(select(Repository).where(Repository.id == repository_id))
            if not repo:
                snapshot["limitations"].append("Repository not found")
                return snapshot

            # Phase 1: Multi-Language Analysis
            language_analysis = self._analyze_languages(repository_id)
            snapshot.update({
                "languages_detected": language_analysis["languages"],
                "frameworks_detected": language_analysis["frameworks"],
                "integrations_detected": language_analysis["integrations"],
                "analysis_coverage": language_analysis["coverage"],
            })

            # Phase 2: Repository Archetype Detection
            archetype_analysis = self._analyze_archetypes(repository_id)
            snapshot.update({
                "repo_archetypes": archetype_analysis["archetypes"],
                "primary_archetype": archetype_analysis["primary_archetype"],
                "monorepo_detected": archetype_analysis.get("monorepo_detected", False),
            })

            # Phase 3: Entrypoint Intelligence
            entrypoint_analysis = self._analyze_entrypoints(
                repository_id, 
                snapshot["primary_archetype"]
            )
            snapshot["entrypoints"] = entrypoint_analysis

            # Phase 4: File Role Intelligence
            file_analysis = self._analyze_file_roles(
                repository_id,
                snapshot["primary_archetype"]
            )
            snapshot.update({
                "file_role_summary": file_analysis["role_summary"],
                "file_intelligence_summary": file_analysis["intelligence_summary"],
                "important_files": file_analysis["important_files"],
            })

            # Phase 5: Graph Intelligence (3-Layer)
            graph_analysis = self._analyze_graph_intelligence(repository_id)
            snapshot.update({
                "graph_health": graph_analysis["health"],
                "graph_stats": graph_analysis["stats"],
                "edge_type_counts": graph_analysis["edge_counts"],
                "sparse_graph": graph_analysis["sparse"],
                "weak_evidence": graph_analysis["weak_evidence"],
            })

            # Phase 6: Execution Strategy Selection
            execution_analysis = self._analyze_execution_strategy(
                snapshot["primary_archetype"],
                snapshot["entrypoints"],
                graph_analysis
            )
            snapshot.update({
                "dominant_subsystems": execution_analysis["subsystems"],
                "execution_hints": execution_analysis["hints"],
                "flow_strategy": execution_analysis["strategy"],
            })

            # Phase 7: Overall Quality Assessment
            quality_analysis = self._assess_overall_quality(snapshot)
            snapshot.update({
                "overall_confidence": quality_analysis["confidence"],
                "limitations": quality_analysis["limitations"],
                "weak_repo_mode": quality_analysis["weak_repo_mode"],
            })

            logger.info(
                f"Universal analysis complete for {repository_id}: "
                f"archetype={snapshot['primary_archetype']}, "
                f"confidence={snapshot['overall_confidence']}, "
                f"weak_mode={snapshot['weak_repo_mode']}"
            )

        except Exception as e:
            logger.error(f"Universal analysis failed for {repository_id}: {e}", exc_info=True)
            snapshot["limitations"].append(f"Analysis failed: {str(e)}")
            snapshot["overall_confidence"] = "low"
            snapshot["weak_repo_mode"] = True

        return snapshot

    def _analyze_languages(self, repository_id: str) -> Dict[str, Any]:
        """Analyze languages, frameworks, and integrations using multi-language registry."""
        try:
            # Load file language distribution
            lang_rows = list(self.db.execute(
                select(File.language, func.count(File.id))
                .where(
                    File.repository_id == repository_id,
                    File.language.isnot(None),
                    File.is_generated.is_(False),
                    File.is_vendor.is_(False),
                )
                .group_by(File.language)
                .order_by(func.count(File.id).desc())
            ).all())

            languages = [lang for lang, count in lang_rows if lang and count >= 1]

            # Load imports for framework detection
            framework_signals = set()
            integration_signals = set()

            try:
                import_rows = list(self.db.execute(
                    select(Symbol.imports_list)
                    .join(File, Symbol.file_id == File.id)
                    .where(
                        File.repository_id == repository_id,
                        Symbol.imports_list.isnot(None),
                    )
                    .limit(100)
                ).all())

                for (imports_json,) in import_rows:
                    if isinstance(imports_json, list):
                        imports = [str(x).lower() for x in imports_json]
                    elif isinstance(imports_json, str):
                        try:
                            import json
                            parsed = json.loads(imports_json)
                            imports = [str(x).lower() for x in parsed] if isinstance(parsed, list) else []
                        except Exception:
                            imports = []
                    else:
                        imports = []

                    # Classify imports into frameworks and integrations
                    for imp in imports:
                        # Web frameworks
                        if any(fw in imp for fw in ["fastapi", "flask", "django", "express", "nest", "spring"]):
                            framework_signals.add("web_framework")
                        # Frontend frameworks
                        elif any(fw in imp for fw in ["react", "vue", "angular", "svelte", "next", "nuxt"]):
                            framework_signals.add("frontend_framework")
                        # CLI frameworks
                        elif any(fw in imp for fw in ["click", "typer", "argparse", "commander", "cobra", "clap"]):
                            framework_signals.add("cli_framework")
                        # ML frameworks
                        elif any(fw in imp for fw in ["torch", "tensorflow", "sklearn", "transformers", "keras"]):
                            framework_signals.add("ml_framework")
                        # Data frameworks
                        elif any(fw in imp for fw in ["pandas", "numpy", "polars", "dask", "airflow", "prefect"]):
                            framework_signals.add("data_framework")
                        # UI toolkits
                        elif any(ui in imp for ui in ["swing", "javafx", "tkinter", "pyqt", "electron"]):
                            framework_signals.add("ui_toolkit")
                        
                        # Integrations
                        if any(svc in imp for svc in ["openai", "anthropic", "gemini", "langchain"]):
                            integration_signals.add("llm_service")
                        elif any(svc in imp for svc in ["stripe", "paypal", "braintree"]):
                            integration_signals.add("payment_service")
                        elif any(svc in imp for svc in ["firebase", "supabase", "aws", "gcp", "azure"]):
                            integration_signals.add("cloud_service")
                        elif any(db in imp for db in ["mysql", "postgres", "mongodb", "redis", "sqlite"]):
                            integration_signals.add("database")

            except Exception as e:
                logger.debug(f"Import analysis failed: {e}")

            # Calculate coverage
            total_files = self.db.scalar(
                select(func.count(File.id)).where(
                    File.repository_id == repository_id,
                    File.is_generated.is_(False),
                    File.is_vendor.is_(False),
                )
            ) or 0

            analyzed_files = sum(count for _, count in lang_rows)
            coverage_pct = (analyzed_files / max(total_files, 1)) * 100

            return {
                "languages": languages[:10],  # Top 10 languages
                "frameworks": list(framework_signals),
                "integrations": list(integration_signals),
                "coverage": {
                    "total_files": total_files,
                    "analyzed_files": analyzed_files,
                    "coverage_percent": round(coverage_pct, 1),
                    "quality": "high" if coverage_pct >= 80 else "medium" if coverage_pct >= 50 else "low"
                }
            }

        except Exception as e:
            logger.error(f"Language analysis failed: {e}")
            return {
                "languages": [],
                "frameworks": [],
                "integrations": [],
                "coverage": {"total_files": 0, "analyzed_files": 0, "coverage_percent": 0, "quality": "low"}
            }

    def _analyze_archetypes(self, repository_id: str) -> Dict[str, Any]:
        """Analyze repository archetypes with monorepo detection."""
        try:
            archetype_data = self.archetype_svc.detect_archetypes(repository_id)
            
            # Enhanced monorepo detection
            monorepo_detected = False
            try:
                # Check for multiple package manifests
                manifest_patterns = [
                    "package.json", "pom.xml", "build.gradle", "Cargo.toml", 
                    "pyproject.toml", "setup.py", "go.mod"
                ]
                
                manifest_count = 0
                for pattern in manifest_patterns:
                    count = self.db.scalar(
                        select(func.count(File.id)).where(
                            File.repository_id == repository_id,
                            File.path.like(f"%{pattern}")
                        )
                    ) or 0
                    manifest_count += count

                # Check for workspace indicators
                workspace_indicators = self.db.scalar(
                    select(func.count(File.id)).where(
                        File.repository_id == repository_id,
                        File.path.regexp_match(r".*(apps|packages|services|libs|workspaces)/.*")
                    )
                ) or 0

                monorepo_detected = manifest_count >= 3 or workspace_indicators >= 5

            except Exception as e:
                logger.debug(f"Monorepo detection failed: {e}")

            return {
                "archetypes": archetype_data.get("archetypes", []),
                "primary_archetype": archetype_data.get("primary_archetype", "generic_codebase"),
                "monorepo_detected": monorepo_detected,
            }

        except Exception as e:
            logger.error(f"Archetype analysis failed: {e}")
            return {
                "archetypes": [{"name": "generic_codebase", "score": 1.0, "confidence": "low", "evidence": ["Analysis failed"]}],
                "primary_archetype": "generic_codebase",
                "monorepo_detected": False,
            }

    def _analyze_entrypoints(self, repository_id: str, archetype: str) -> Dict[str, Any]:
        """Analyze entrypoints with archetype-aware logic."""
        try:
            entrypoint_data = self.entrypoint_svc.detect_entrypoints(repository_id, archetype=archetype)
            return {
                "primary_entrypoint": entrypoint_data.get("primary_entrypoint"),
                "candidate_entrypoints": entrypoint_data.get("candidate_entrypoints", []),
                "confidence": entrypoint_data.get("analysis_quality", "low"),
                "reasons": self._extract_entrypoint_reasons(entrypoint_data),
            }
        except Exception as e:
            logger.error(f"Entrypoint analysis failed: {e}")
            return {
                "primary_entrypoint": None,
                "candidate_entrypoints": [],
                "confidence": "low",
                "reasons": ["Entrypoint analysis failed"],
            }

    def _analyze_file_roles(self, repository_id: str, archetype: str) -> Dict[str, Any]:
        """Analyze file roles and importance."""
        try:
            file_roles = self.file_role_svc.classify_file_roles(repository_id, archetype=archetype)
            
            # Build role summary
            role_counts = {}
            important_files = []
            
            for file_id, role_data in file_roles.items():
                role = role_data.get("role", "unknown")
                confidence = role_data.get("confidence", "low")
                
                role_counts[role] = role_counts.get(role, 0) + 1
                
                # Collect important files (high confidence, important roles)
                if confidence in ("high", "medium") and role in (
                    "entrypoint", "route", "service", "model", "ui_screen", "component", "cli_command"
                ):
                    # Get file path
                    try:
                        file_path = self.db.scalar(
                            select(File.path).where(File.id == file_id)
                        )
                        if file_path:
                            important_files.append({
                                "file_id": file_id,
                                "path": file_path,
                                "role": role,
                                "confidence": confidence,
                                "reasons": role_data.get("reasons", [])[:2],
                            })
                    except Exception:
                        pass

            # Sort important files by role priority
            role_priority = {
                "entrypoint": 10, "route": 9, "ui_screen": 8, "service": 7, "component": 6,
                "model": 5, "cli_command": 8, "handler": 7, "controller": 7
            }
            important_files.sort(key=lambda x: -role_priority.get(x["role"], 0))

            return {
                "role_summary": role_counts,
                "intelligence_summary": {
                    "total_classified": len(file_roles),
                    "high_confidence": sum(1 for r in file_roles.values() if r.get("confidence") == "high"),
                    "unknown_files": role_counts.get("unknown", 0),
                },
                "important_files": important_files[:20],  # Top 20 important files
            }

        except Exception as e:
            logger.error(f"File role analysis failed: {e}")
            return {
                "role_summary": {},
                "intelligence_summary": {"total_classified": 0, "high_confidence": 0, "unknown_files": 0},
                "important_files": [],
            }

    def _analyze_graph_intelligence(self, repository_id: str) -> Dict[str, Any]:
        """Analyze 3-layer graph intelligence with health assessment."""
        try:
            # Get primary archetype for graph engine
            archetype_data = self.archetype_svc.detect_archetypes(repository_id)
            primary_archetype = archetype_data.get("primary_archetype", "generic_codebase")
            
            # Use 3-layer graph engine for comprehensive analysis
            graph_result = self.graph_engine.build_layered_graph(repository_id, primary_archetype)
            
            # Get traditional graph health from GraphService for compatibility
            health_data = self.graph_svc.get_graph_health(repository_id)
            
            # Combine results
            return {
                "health": {
                    "quality": graph_result["quality"],
                    "recommendations": graph_result["recommendations"],
                    "is_sparse": graph_result["sparse"],
                    "edges_per_file": health_data.get("edges_per_file", 0),
                },
                "stats": graph_result["stats"],
                "edge_counts": {
                    "structural_edges": graph_result["layers"]["structural"]["edge_count"],
                    "semantic_edges": graph_result["layers"]["semantic"]["edge_count"],
                    "runtime_edges": graph_result["layers"]["runtime"]["edge_count"],
                },
                "sparse": graph_result["sparse"],
                "weak_evidence": graph_result["weak_evidence"],
                "layer_confidence": {
                    "structural": graph_result["layers"]["structural"]["confidence"],
                    "semantic": graph_result["layers"]["semantic"]["confidence"],
                    "runtime": graph_result["layers"]["runtime"]["confidence"],
                },
            }

        except Exception as e:
            logger.error(f"Graph analysis failed: {e}")
            return {
                "health": {"quality": "low", "recommendations": ["Graph analysis failed"]},
                "stats": {"total_edges": 0, "structural_edges": 0, "semantic_edges": 0, "runtime_edges": 0},
                "edge_counts": {},
                "sparse": True,
                "weak_evidence": True,
                "layer_confidence": {"structural": "low", "semantic": "low", "runtime": "low"},
            }

    def _analyze_execution_strategy(
        self, 
        archetype: str, 
        entrypoints: Dict[str, Any], 
        graph_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Determine execution flow strategy based on archetype and graph quality."""
        
        # Map archetype to flow strategy
        strategy_map = {
            "backend_api": "backend_request_flow",
            "fullstack_web": "fullstack_request_flow", 
            "frontend_app": "frontend_render_flow",
            "static_site": "static_asset_flow",
            "java_desktop_gui": "desktop_gui_event_flow",
            "cli_tool": "cli_invocation_flow",
            "library_sdk": "library_usage_flow",
            "ml_ai_project": "ml_pipeline_flow",
            "data_pipeline": "data_pipeline_flow",
            "monorepo": "monorepo_multi_flow",
            "generic_codebase": "generic_traversal_flow",
        }

        strategy = strategy_map.get(archetype, "generic_traversal_flow")
        
        # Detect dominant subsystems
        subsystems = []
        edge_counts = graph_data.get("edge_counts", {})
        
        if edge_counts.get("route_to_service", 0) >= 2:
            subsystems.append("api_layer")
        if edge_counts.get("service_to_model", 0) >= 2:
            subsystems.append("data_layer")
        if edge_counts.get("component_tree", 0) >= 3:
            subsystems.append("ui_layer")
        if edge_counts.get("gui_navigation", 0) >= 2:
            subsystems.append("desktop_ui")
        if edge_counts.get("cli_command", 0) >= 2:
            subsystems.append("command_interface")

        # Generate execution hints
        hints = {
            "strategy": strategy,
            "confidence": "high" if not graph_data.get("weak_evidence") else "medium" if not graph_data.get("sparse") else "low",
            "primary_entrypoint": entrypoints.get("primary_entrypoint", {}).get("path"),
            "flow_complexity": "complex" if len(subsystems) >= 3 else "moderate" if len(subsystems) >= 2 else "simple",
        }

        return {
            "subsystems": subsystems,
            "hints": hints,
            "strategy": strategy,
        }

    def _assess_overall_quality(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """Assess overall analysis quality and determine weak repo mode."""
        
        limitations = []
        confidence_factors = []
        
        # Language coverage
        coverage = snapshot.get("analysis_coverage", {})
        if coverage.get("coverage_percent", 0) < 50:
            limitations.append("Low language analysis coverage")
        else:
            confidence_factors.append("Good language coverage")

        # Archetype confidence
        archetypes = snapshot.get("repo_archetypes", [])
        if archetypes and archetypes[0].get("confidence") == "high":
            confidence_factors.append("Strong archetype detection")
        elif not archetypes:
            limitations.append("No clear repository archetype")

        # Entrypoint confidence
        entrypoint_conf = snapshot.get("entrypoints", {}).get("confidence", "low")
        if entrypoint_conf == "high":
            confidence_factors.append("Clear entrypoint detection")
        elif entrypoint_conf == "low":
            limitations.append("Unclear entrypoints")

        # Graph quality
        if snapshot.get("sparse_graph"):
            limitations.append("Sparse dependency graph")
        if snapshot.get("weak_evidence"):
            limitations.append("Weak structural evidence")
        
        graph_stats = snapshot.get("graph_stats", {})
        if graph_stats.get("total_edges", 0) >= 10:
            confidence_factors.append("Rich dependency graph")

        # File intelligence
        file_summary = snapshot.get("file_intelligence_summary", {})
        if file_summary.get("high_confidence", 0) >= 5:
            confidence_factors.append("Good file role classification")

        # Overall confidence assessment
        if len(confidence_factors) >= 4 and len(limitations) <= 1:
            overall_confidence = "high"
        elif len(confidence_factors) >= 2 and len(limitations) <= 3:
            overall_confidence = "medium"
        else:
            overall_confidence = "low"

        # Weak repo mode detection
        weak_repo_mode = (
            overall_confidence == "low" or
            len(limitations) >= 4 or
            (snapshot.get("sparse_graph") and snapshot.get("weak_evidence"))
        )

        return {
            "confidence": overall_confidence,
            "limitations": limitations,
            "weak_repo_mode": weak_repo_mode,
            "confidence_factors": confidence_factors,
        }

    def _extract_entrypoint_reasons(self, entrypoint_data: Dict[str, Any]) -> List[str]:
        """Extract human-readable reasons from entrypoint analysis."""
        reasons = []
        
        primary = entrypoint_data.get("primary_entrypoint")
        if primary:
            reasons.extend(primary.get("reasons", [])[:3])
        
        candidates = entrypoint_data.get("candidate_entrypoints", [])
        if len(candidates) > 1:
            reasons.append(f"{len(candidates)} candidate entrypoints found")
        
        quality = entrypoint_data.get("analysis_quality", "low")
        if quality == "low":
            reasons.append("Low confidence - multiple possibilities")
        
        return reasons[:5]  # Limit to top 5 reasons