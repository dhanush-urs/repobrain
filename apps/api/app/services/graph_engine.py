"""
3-Layer Graph Engine - RepoBrain 10.0

Layered graph construction for universal repository intelligence:

LAYER A: STRUCTURAL GRAPH (runs on almost every repo)
- import/include/require edges
- file_reference, config_reference, env_reference
- manifest_reference, asset_link, script_invocation
- test_target, schema_reference, symbol_reference

LAYER B: SEMANTIC GRAPH (archetype-aware)
- backend_api: route_to_handler, handler_to_service, service_to_model
- frontend_app: html_to_script, component_tree, router_to_page
- java_desktop_gui: main_to_ui, ui_navigation, action_to_handler
- cli_tool: parser_to_command, command_to_service
- library_sdk: export_to_implementation, interface_to_implementation

LAYER C: RUNTIME HEURISTIC GRAPH (best-effort only)
- frontend fetch -> backend route
- button click -> next UI screen
- event listener -> render/update
- CLI command -> output side effect
"""

import logging
import re
from typing import Dict, List, Any, Set, Tuple
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.models import File, Symbol, DependencyEdge
from app.analyzers.analyzer_registry import get_analyzer_registry

logger = logging.getLogger(__name__)


class GraphEngine:
    """3-Layer graph construction engine for universal repository intelligence."""
    
    def __init__(self, db: Session):
        self.db = db
        self.analyzer_registry = get_analyzer_registry()
    
    def build_layered_graph(self, repository_id: str, archetype: str = "generic_codebase") -> Dict[str, Any]:
        """
        Build 3-layer graph for repository.
        
        Returns:
        {
            "layers": {
                "structural": {"edges": [...], "confidence": "high"},
                "semantic": {"edges": [...], "confidence": "medium"},
                "runtime": {"edges": [...], "confidence": "low"}
            },
            "stats": {...},
            "quality": "high" | "medium" | "low",
            "sparse": bool,
            "weak_evidence": bool
        }
        """
        try:
            # Load repository files and existing edges
            files_data = self._load_repository_data(repository_id)
            existing_edges = self._load_existing_edges(repository_id)
            
            # Layer A: Structural Graph
            structural_layer = self._build_structural_layer(repository_id, files_data, existing_edges)
            
            # Layer B: Semantic Graph (archetype-aware)
            semantic_layer = self._build_semantic_layer(repository_id, archetype, files_data, existing_edges)
            
            # Layer C: Runtime Heuristic Graph
            runtime_layer = self._build_runtime_layer(repository_id, archetype, files_data, existing_edges)
            
            # Assess overall graph quality
            quality_assessment = self._assess_graph_quality(structural_layer, semantic_layer, runtime_layer)
            
            return {
                "repository_id": repository_id,
                "archetype": archetype,
                "layers": {
                    "structural": structural_layer,
                    "semantic": semantic_layer,
                    "runtime": runtime_layer,
                },
                "stats": quality_assessment["stats"],
                "quality": quality_assessment["quality"],
                "sparse": quality_assessment["sparse"],
                "weak_evidence": quality_assessment["weak_evidence"],
                "recommendations": quality_assessment["recommendations"],
            }
            
        except Exception as e:
            logger.error(f"Layered graph construction failed for {repository_id}: {e}")
            return self._empty_graph_result(repository_id, archetype, str(e))
    
    def _load_repository_data(self, repository_id: str) -> Dict[str, Any]:
        """Load repository files and metadata for graph construction."""
        try:
            # Load files with content for analysis
            file_rows = list(self.db.execute(
                select(File.id, File.path, File.language, File.content, File.is_test, File.is_generated, File.is_vendor)
                .where(
                    File.repository_id == repository_id,
                    File.is_generated.is_(False),
                    File.is_vendor.is_(False),
                )
                .limit(200)  # Reasonable limit for graph construction
            ).all())
            
            files_by_id = {}
            files_by_path = {}
            
            for fid, path, lang, content, is_test, is_gen, is_vendor in file_rows:
                file_data = {
                    "id": fid,
                    "path": path,
                    "language": lang,
                    "content": content or "",
                    "is_test": is_test,
                    "is_generated": is_gen,
                    "is_vendor": is_vendor,
                }
                files_by_id[fid] = file_data
                files_by_path[path.lower()] = file_data
            
            # Load symbols for reference resolution
            symbol_rows = list(self.db.execute(
                select(Symbol.file_id, Symbol.name, Symbol.symbol_type, Symbol.imports_list)
                .join(File, File.id == Symbol.file_id)
                .where(Symbol.repository_id == repository_id)
                .limit(500)
            ).all())
            
            symbols_by_file = {}
            for fid, name, stype, imports in symbol_rows:
                if fid not in symbols_by_file:
                    symbols_by_file[fid] = {"symbols": [], "imports": []}
                symbols_by_file[fid]["symbols"].append({"name": name, "type": stype})
                if imports:
                    if isinstance(imports, list):
                        symbols_by_file[fid]["imports"].extend(imports)
            
            return {
                "files_by_id": files_by_id,
                "files_by_path": files_by_path,
                "symbols_by_file": symbols_by_file,
                "total_files": len(file_rows),
            }
            
        except Exception as e:
            logger.error(f"Failed to load repository data: {e}")
            return {"files_by_id": {}, "files_by_path": {}, "symbols_by_file": {}, "total_files": 0}
    
    def _load_existing_edges(self, repository_id: str) -> Set[Tuple[str, str, str]]:
        """Load existing edges to avoid duplicates."""
        try:
            edge_rows = list(self.db.execute(
                select(DependencyEdge.source_file_id, DependencyEdge.target_file_id, DependencyEdge.edge_type)
                .where(
                    DependencyEdge.repository_id == repository_id,
                    DependencyEdge.source_file_id.isnot(None),
                    DependencyEdge.target_file_id.isnot(None),
                )
            ).all())
            
            return {(src, tgt, etype) for src, tgt, etype in edge_rows}
            
        except Exception as e:
            logger.error(f"Failed to load existing edges: {e}")
            return set()
    
    def _build_structural_layer(self, repository_id: str, files_data: Dict, existing_edges: Set) -> Dict[str, Any]:
        """Build Layer A: Structural Graph (must run on almost every repo)."""
        edges = []
        confidence_factors = []
        
        try:
            files_by_id = files_data["files_by_id"]
            files_by_path = files_data["files_by_path"]
            symbols_by_file = files_data["symbols_by_file"]
            
            # 1. Import/Include/Require edges (from existing analysis)
            import_edges = self._extract_import_edges(repository_id, existing_edges)
            edges.extend(import_edges)
            if import_edges:
                confidence_factors.append(f"{len(import_edges)} import edges")
            
            # 2. File reference edges (string literals that match file paths)
            file_ref_edges = self._extract_file_reference_edges(files_by_id, files_by_path)
            edges.extend(file_ref_edges)
            if file_ref_edges:
                confidence_factors.append(f"{len(file_ref_edges)} file reference edges")
            
            # 3. Config/Env reference edges
            config_edges = self._extract_config_reference_edges(files_by_id, files_by_path)
            edges.extend(config_edges)
            if config_edges:
                confidence_factors.append(f"{len(config_edges)} config reference edges")
            
            # 4. Manifest reference edges
            manifest_edges = self._extract_manifest_edges(files_by_id, files_by_path)
            edges.extend(manifest_edges)
            if manifest_edges:
                confidence_factors.append(f"{len(manifest_edges)} manifest edges")
            
            # 5. Symbol reference edges (best effort)
            symbol_edges = self._extract_symbol_reference_edges(files_by_id, symbols_by_file)
            edges.extend(symbol_edges)
            if symbol_edges:
                confidence_factors.append(f"{len(symbol_edges)} symbol reference edges")
            
            # Assess structural layer confidence
            total_edges = len(edges)
            if total_edges >= 10:
                confidence = "high"
            elif total_edges >= 3:
                confidence = "medium"
            else:
                confidence = "low"
            
            return {
                "edges": edges,
                "edge_count": total_edges,
                "confidence": confidence,
                "confidence_factors": confidence_factors,
                "limitations": [] if total_edges > 0 else ["No structural relationships detected"],
            }
            
        except Exception as e:
            logger.error(f"Structural layer construction failed: {e}")
            return {
                "edges": [],
                "edge_count": 0,
                "confidence": "low",
                "confidence_factors": [],
                "limitations": [f"Structural analysis failed: {str(e)}"],
            }
    
    def _build_semantic_layer(self, repository_id: str, archetype: str, files_data: Dict, existing_edges: Set) -> Dict[str, Any]:
        """Build Layer B: Semantic Graph (archetype-aware)."""
        edges = []
        confidence_factors = []
        
        try:
            files_by_id = files_data["files_by_id"]
            
            # Branch by archetype for semantic edge extraction
            if archetype == "backend_api":
                edges.extend(self._extract_backend_api_edges(files_by_id))
            elif archetype == "frontend_app":
                edges.extend(self._extract_frontend_app_edges(files_by_id))
            elif archetype == "java_desktop_gui":
                edges.extend(self._extract_java_gui_edges(files_by_id))
            elif archetype == "cli_tool":
                edges.extend(self._extract_cli_tool_edges(files_by_id))
            elif archetype == "library_sdk":
                edges.extend(self._extract_library_sdk_edges(files_by_id))
            elif archetype == "ml_ai_project":
                edges.extend(self._extract_ml_pipeline_edges(files_by_id))
            
            # Add cross-archetype semantic edges
            edges.extend(self._extract_universal_semantic_edges(files_by_id))
            
            # Remove duplicates and existing edges
            unique_edges = []
            for edge in edges:
                edge_tuple = (edge["source_file_id"], edge["target_file_id"], edge["edge_type"])
                if edge_tuple not in existing_edges:
                    unique_edges.append(edge)
            
            # Assess semantic layer confidence
            total_edges = len(unique_edges)
            if total_edges >= 5:
                confidence = "high"
                confidence_factors.append(f"Rich semantic relationships ({total_edges} edges)")
            elif total_edges >= 2:
                confidence = "medium"
                confidence_factors.append(f"Some semantic relationships ({total_edges} edges)")
            else:
                confidence = "low"
                confidence_factors.append("Limited semantic relationships")
            
            return {
                "edges": unique_edges,
                "edge_count": total_edges,
                "confidence": confidence,
                "confidence_factors": confidence_factors,
                "limitations": [] if total_edges > 0 else [f"No {archetype} semantic patterns detected"],
            }
            
        except Exception as e:
            logger.error(f"Semantic layer construction failed: {e}")
            return {
                "edges": [],
                "edge_count": 0,
                "confidence": "low",
                "confidence_factors": [],
                "limitations": [f"Semantic analysis failed: {str(e)}"],
            }
    
    def _build_runtime_layer(self, repository_id: str, archetype: str, files_data: Dict, existing_edges: Set) -> Dict[str, Any]:
        """Build Layer C: Runtime Heuristic Graph (best-effort only)."""
        edges = []
        confidence_factors = []
        
        try:
            files_by_id = files_data["files_by_id"]
            
            # Runtime heuristics by archetype
            if archetype in ("frontend_app", "fullstack_web"):
                edges.extend(self._extract_frontend_runtime_edges(files_by_id))
            elif archetype == "java_desktop_gui":
                edges.extend(self._extract_gui_runtime_edges(files_by_id))
            elif archetype == "cli_tool":
                edges.extend(self._extract_cli_runtime_edges(files_by_id))
            
            # Universal runtime heuristics
            edges.extend(self._extract_universal_runtime_edges(files_by_id))
            
            # Remove duplicates and existing edges
            unique_edges = []
            for edge in edges:
                edge_tuple = (edge["source_file_id"], edge["target_file_id"], edge["edge_type"])
                if edge_tuple not in existing_edges:
                    unique_edges.append(edge)
            
            # Runtime layer is always low confidence (heuristic)
            total_edges = len(unique_edges)
            confidence = "low"  # Runtime heuristics are always uncertain
            
            if total_edges > 0:
                confidence_factors.append(f"Runtime heuristics ({total_edges} inferred edges)")
            
            return {
                "edges": unique_edges,
                "edge_count": total_edges,
                "confidence": confidence,
                "confidence_factors": confidence_factors,
                "limitations": ["Runtime edges are heuristic only", "May include false positives"],
            }
            
        except Exception as e:
            logger.error(f"Runtime layer construction failed: {e}")
            return {
                "edges": [],
                "edge_count": 0,
                "confidence": "low",
                "confidence_factors": [],
                "limitations": [f"Runtime analysis failed: {str(e)}"],
            }
    
    def _extract_import_edges(self, repository_id: str, existing_edges: Set) -> List[Dict]:
        """Extract existing import/require/include edges."""
        try:
            edge_rows = list(self.db.execute(
                select(DependencyEdge.source_file_id, DependencyEdge.target_file_id, 
                       DependencyEdge.edge_type, DependencyEdge.source_ref, DependencyEdge.target_ref)
                .where(
                    DependencyEdge.repository_id == repository_id,
                    DependencyEdge.edge_type.in_(["import", "require", "include", "from_import"]),
                    DependencyEdge.source_file_id.isnot(None),
                    DependencyEdge.target_file_id.isnot(None),
                )
            ).all())
            
            edges = []
            for src, tgt, etype, sref, tref in edge_rows:
                edges.append({
                    "source_file_id": src,
                    "target_file_id": tgt,
                    "edge_type": etype,
                    "edge_family": "structural",
                    "confidence": 0.9,
                    "evidence_source": "import_analysis",
                    "source_ref": sref,
                    "target_ref": tref,
                })
            
            return edges
            
        except Exception as e:
            logger.error(f"Import edge extraction failed: {e}")
            return []
    
    def _extract_file_reference_edges(self, files_by_id: Dict, files_by_path: Dict) -> List[Dict]:
        """Extract file reference edges from string literals."""
        edges = []
        
        try:
            for file_id, file_data in files_by_id.items():
                content = file_data.get("content", "")
                if not content:
                    continue
                
                # Use analyzer to extract file references
                result = self.analyzer_registry.analyze_file(
                    file_id, file_data["path"], content, file_data["language"]
                )
                
                if result and result.file_references:
                    for ref_path in result.file_references:
                        # Try to match against known files
                        target_file = files_by_path.get(ref_path.lower())
                        if target_file and target_file["id"] != file_id:
                            edges.append({
                                "source_file_id": file_id,
                                "target_file_id": target_file["id"],
                                "edge_type": "file_reference",
                                "edge_family": "structural",
                                "confidence": 0.7,
                                "evidence_source": "string_literal",
                                "source_ref": file_data["path"].split("/")[-1],
                                "target_ref": ref_path,
                            })
            
        except Exception as e:
            logger.error(f"File reference extraction failed: {e}")
        
        return edges[:50]  # Limit to prevent explosion
    
    def _extract_config_reference_edges(self, files_by_id: Dict, files_by_path: Dict) -> List[Dict]:
        """Extract config/env file reference edges."""
        edges = []
        
        try:
            # Find config files
            config_files = {
                fid: fdata for fid, fdata in files_by_id.items()
                if any(ext in fdata["path"].lower() for ext in [".env", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".conf"])
            }
            
            if not config_files:
                return edges
            
            # Find files that reference config
            for file_id, file_data in files_by_id.items():
                if file_id in config_files:
                    continue
                
                content = file_data.get("content", "")
                if not content:
                    continue
                
                # Use analyzer to extract config hints
                result = self.analyzer_registry.analyze_file(
                    file_id, file_data["path"], content, file_data["language"]
                )
                
                if result and result.config_hints:
                    # Link to any config file (heuristic)
                    for config_id, config_data in list(config_files.items())[:3]:  # Limit to 3 config files
                        edges.append({
                            "source_file_id": file_id,
                            "target_file_id": config_id,
                            "edge_type": "config_reference",
                            "edge_family": "structural",
                            "confidence": 0.6,
                            "evidence_source": "config_usage",
                            "source_ref": file_data["path"].split("/")[-1],
                            "target_ref": config_data["path"].split("/")[-1],
                        })
                        break  # One config reference per file
            
        except Exception as e:
            logger.error(f"Config reference extraction failed: {e}")
        
        return edges
    
    def _extract_manifest_edges(self, files_by_id: Dict, files_by_path: Dict) -> List[Dict]:
        """Extract manifest to entrypoint edges."""
        edges = []
        
        try:
            # Find manifest files
            manifest_patterns = ["package.json", "pom.xml", "build.gradle", "pyproject.toml", "cargo.toml", "go.mod"]
            manifest_files = {
                fid: fdata for fid, fdata in files_by_id.items()
                if any(pattern in fdata["path"].lower() for pattern in manifest_patterns)
            }
            
            # Find likely entrypoint files
            entrypoint_patterns = ["main", "app", "server", "index", "cli"]
            entrypoint_files = {
                fid: fdata for fid, fdata in files_by_id.items()
                if any(pattern in fdata["path"].lower() for pattern in entrypoint_patterns)
                and len(fdata["path"].split("/")) <= 3  # Root level
            }
            
            # Connect manifests to entrypoints
            for manifest_id, manifest_data in manifest_files.items():
                for entry_id, entry_data in list(entrypoint_files.items())[:2]:  # Max 2 entrypoints per manifest
                    if manifest_id != entry_id:
                        edges.append({
                            "source_file_id": manifest_id,
                            "target_file_id": entry_id,
                            "edge_type": "manifest_to_entry",
                            "edge_family": "structural",
                            "confidence": 0.5,
                            "evidence_source": "manifest_heuristic",
                            "source_ref": manifest_data["path"].split("/")[-1],
                            "target_ref": entry_data["path"].split("/")[-1],
                        })
            
        except Exception as e:
            logger.error(f"Manifest edge extraction failed: {e}")
        
        return edges
    
    def _extract_symbol_reference_edges(self, files_by_id: Dict, symbols_by_file: Dict) -> List[Dict]:
        """Extract symbol reference edges (best effort)."""
        edges = []
        
        try:
            # Build symbol index: symbol_name -> file_id
            symbol_index = {}
            for file_id, symbol_data in symbols_by_file.items():
                for symbol in symbol_data.get("symbols", []):
                    symbol_name = symbol["name"].lower()
                    if len(symbol_name) >= 3:  # Avoid short/common names
                        symbol_index[symbol_name] = file_id
            
            # Find symbol references in file content
            for file_id, file_data in files_by_id.items():
                content = file_data.get("content", "")
                if not content or len(content) > 10000:  # Skip very large files
                    continue
                
                content_lower = content.lower()
                
                # Look for symbol references
                for symbol_name, defining_file_id in symbol_index.items():
                    if defining_file_id != file_id and symbol_name in content_lower:
                        # Simple heuristic: symbol name appears in content
                        edges.append({
                            "source_file_id": file_id,
                            "target_file_id": defining_file_id,
                            "edge_type": "symbol_reference",
                            "edge_family": "structural",
                            "confidence": 0.4,  # Low confidence for simple text matching
                            "evidence_source": "symbol_usage",
                            "source_ref": file_data["path"].split("/")[-1],
                            "target_ref": symbol_name,
                        })
            
        except Exception as e:
            logger.error(f"Symbol reference extraction failed: {e}")
        
        return edges[:30]  # Limit to prevent explosion
    
    # Placeholder methods for semantic and runtime edge extraction
    # These would be implemented based on the existing archetype-specific logic
    
    def _extract_backend_api_edges(self, files_by_id: Dict) -> List[Dict]:
        """Extract backend API semantic edges."""
        edges = []
        
        try:
            # Find route files and service files
            route_files = {}
            service_files = {}
            model_files = {}
            
            for file_id, file_data in files_by_id.items():
                path_lower = file_data["path"].lower()
                content = file_data.get("content", "")
                
                # Classify files by patterns
                if any(pattern in path_lower for pattern in ["route", "endpoint", "controller", "handler"]):
                    route_files[file_id] = file_data
                elif any(pattern in path_lower for pattern in ["service", "business", "logic"]):
                    service_files[file_id] = file_data
                elif any(pattern in path_lower for pattern in ["model", "entity", "schema", "dto"]):
                    model_files[file_id] = file_data
                
                # Also classify by content patterns
                if "@app.route" in content or "@router." in content or "app.get(" in content:
                    route_files[file_id] = file_data
                elif "class.*Service" in content or "def.*_service" in content:
                    service_files[file_id] = file_data
                elif "class.*Model" in content or "Base.metadata" in content:
                    model_files[file_id] = file_data
            
            # Extract route -> service edges
            for route_id, route_data in route_files.items():
                content = route_data.get("content", "")
                
                # Look for service calls in route handlers
                for service_id, service_data in service_files.items():
                    service_name = service_data["path"].split("/")[-1].replace(".py", "").replace(".js", "")
                    
                    if service_name.lower() in content.lower():
                        edges.append({
                            "source_file_id": route_id,
                            "target_file_id": service_id,
                            "edge_type": "route_to_service",
                            "edge_family": "semantic",
                            "confidence": 0.7,
                            "evidence_source": "service_usage",
                            "source_ref": route_data["path"].split("/")[-1],
                            "target_ref": service_name,
                        })
            
            # Extract service -> model edges
            for service_id, service_data in service_files.items():
                content = service_data.get("content", "")
                
                # Look for model usage in services
                for model_id, model_data in model_files.items():
                    model_name = model_data["path"].split("/")[-1].replace(".py", "").replace(".js", "")
                    
                    if model_name.lower() in content.lower():
                        edges.append({
                            "source_file_id": service_id,
                            "target_file_id": model_id,
                            "edge_type": "service_to_model",
                            "edge_family": "semantic",
                            "confidence": 0.6,
                            "evidence_source": "model_usage",
                            "source_ref": service_data["path"].split("/")[-1],
                            "target_ref": model_name,
                        })
            
        except Exception as e:
            logger.error(f"Backend API edge extraction failed: {e}")
        
        return edges
    
    def _extract_frontend_app_edges(self, files_by_id: Dict) -> List[Dict]:
        """Extract frontend app semantic edges."""
        edges = []
        
        try:
            # Find component files, page files, and HTML files
            component_files = {}
            page_files = {}
            html_files = {}
            
            for file_id, file_data in files_by_id.items():
                path_lower = file_data["path"].lower()
                content = file_data.get("content", "")
                
                # Classify files
                if path_lower.endswith(".html"):
                    html_files[file_id] = file_data
                elif any(pattern in path_lower for pattern in ["component", "widget", "ui"]):
                    component_files[file_id] = file_data
                elif any(pattern in path_lower for pattern in ["page", "view", "screen", "route"]):
                    page_files[file_id] = file_data
                
                # Also classify by content patterns
                if "React.Component" in content or "function.*Component" in content or "export.*Component" in content:
                    component_files[file_id] = file_data
                elif "export default" in content and any(pattern in path_lower for pattern in ["page", "index"]):
                    page_files[file_id] = file_data
            
            # Extract HTML -> script edges
            for html_id, html_data in html_files.items():
                content = html_data.get("content", "")
                
                # Look for script references
                script_refs = re.findall(r'<script[^>]*src=["\']([^"\']+)["\']', content)
                for script_ref in script_refs:
                    # Try to match to actual files
                    for file_id, file_data in files_by_id.items():
                        if script_ref.lower() in file_data["path"].lower():
                            edges.append({
                                "source_file_id": html_id,
                                "target_file_id": file_id,
                                "edge_type": "html_loads_script",
                                "edge_family": "semantic",
                                "confidence": 0.8,
                                "evidence_source": "script_tag",
                                "source_ref": html_data["path"].split("/")[-1],
                                "target_ref": script_ref,
                            })
                            break
            
            # Extract component tree edges (parent -> child components)
            for comp_id, comp_data in component_files.items():
                content = comp_data.get("content", "")
                
                # Look for component imports/usage
                for other_id, other_data in component_files.items():
                    if comp_id == other_id:
                        continue
                    
                    other_name = other_data["path"].split("/")[-1].replace(".jsx", "").replace(".tsx", "").replace(".js", "").replace(".ts", "")
                    
                    # Check if component is imported/used
                    if (f"import.*{other_name}" in content or 
                        f"<{other_name}" in content or 
                        f"{other_name}(" in content):
                        edges.append({
                            "source_file_id": comp_id,
                            "target_file_id": other_id,
                            "edge_type": "component_tree",
                            "edge_family": "semantic",
                            "confidence": 0.7,
                            "evidence_source": "component_usage",
                            "source_ref": comp_data["path"].split("/")[-1],
                            "target_ref": other_name,
                        })
            
            # Extract router -> page edges
            for page_id, page_data in page_files.items():
                # Look for routing patterns
                for comp_id, comp_data in component_files.items():
                    comp_content = comp_data.get("content", "")
                    page_name = page_data["path"].split("/")[-1].replace(".jsx", "").replace(".tsx", "")
                    
                    if ("Route" in comp_content and page_name in comp_content) or \
                       ("router" in comp_data["path"].lower() and page_name.lower() in comp_content.lower()):
                        edges.append({
                            "source_file_id": comp_id,
                            "target_file_id": page_id,
                            "edge_type": "router_to_page",
                            "edge_family": "semantic",
                            "confidence": 0.6,
                            "evidence_source": "routing_config",
                            "source_ref": comp_data["path"].split("/")[-1],
                            "target_ref": page_name,
                        })
            
        except Exception as e:
            logger.error(f"Frontend app edge extraction failed: {e}")
        
        return edges
    
    def _extract_java_gui_edges(self, files_by_id: Dict) -> List[Dict]:
        """Extract Java GUI semantic edges."""
        edges = []
        
        try:
            # Find GUI-related files
            main_files = {}
            ui_files = {}
            handler_files = {}
            
            for file_id, file_data in files_by_id.items():
                path_lower = file_data["path"].lower()
                content = file_data.get("content", "")
                
                # Classify Java GUI files
                if "main(" in content and "public static void main" in content:
                    main_files[file_id] = file_data
                elif any(pattern in content for pattern in ["JFrame", "JPanel", "JButton", "JLabel", "extends JFrame"]):
                    ui_files[file_id] = file_data
                elif any(pattern in content for pattern in ["ActionListener", "MouseListener", "KeyListener", "implements.*Listener"]):
                    handler_files[file_id] = file_data
                elif any(pattern in path_lower for pattern in ["ui", "gui", "view", "screen", "dialog", "frame"]):
                    ui_files[file_id] = file_data
            
            # Extract main -> UI edges
            for main_id, main_data in main_files.items():
                content = main_data.get("content", "")
                
                # Look for UI class instantiation in main
                for ui_id, ui_data in ui_files.items():
                    ui_class_name = ui_data["path"].split("/")[-1].replace(".java", "")
                    
                    if f"new {ui_class_name}" in content or f"{ui_class_name}(" in content:
                        edges.append({
                            "source_file_id": main_id,
                            "target_file_id": ui_id,
                            "edge_type": "main_to_ui",
                            "edge_family": "semantic",
                            "confidence": 0.8,
                            "evidence_source": "ui_instantiation",
                            "source_ref": main_data["path"].split("/")[-1],
                            "target_ref": ui_class_name,
                        })
            
            # Extract UI navigation edges (screen -> screen)
            for ui_id, ui_data in ui_files.items():
                content = ui_data.get("content", "")
                
                # Look for navigation to other UI screens
                for other_ui_id, other_ui_data in ui_files.items():
                    if ui_id == other_ui_id:
                        continue
                    
                    other_class_name = other_ui_data["path"].split("/")[-1].replace(".java", "")
                    
                    if (f"new {other_class_name}" in content or 
                        f"{other_class_name}(" in content or
                        f"setVisible" in content and other_class_name.lower() in content.lower()):
                        edges.append({
                            "source_file_id": ui_id,
                            "target_file_id": other_ui_id,
                            "edge_type": "gui_navigation",
                            "edge_family": "semantic",
                            "confidence": 0.6,
                            "evidence_source": "screen_transition",
                            "source_ref": ui_data["path"].split("/")[-1],
                            "target_ref": other_class_name,
                        })
            
            # Extract action -> handler edges
            for ui_id, ui_data in ui_files.items():
                content = ui_data.get("content", "")
                
                # Look for action listener registration
                for handler_id, handler_data in handler_files.items():
                    handler_class_name = handler_data["path"].split("/")[-1].replace(".java", "")
                    
                    if (f"addActionListener" in content and handler_class_name in content) or \
                       (f"new {handler_class_name}" in content):
                        edges.append({
                            "source_file_id": ui_id,
                            "target_file_id": handler_id,
                            "edge_type": "action_to_handler",
                            "edge_family": "semantic",
                            "confidence": 0.7,
                            "evidence_source": "listener_registration",
                            "source_ref": ui_data["path"].split("/")[-1],
                            "target_ref": handler_class_name,
                        })
            
        except Exception as e:
            logger.error(f"Java GUI edge extraction failed: {e}")
        
        return edges
    
    def _extract_cli_tool_edges(self, files_by_id: Dict) -> List[Dict]:
        """Extract CLI tool semantic edges."""
        edges = []
        
        try:
            # Find CLI-related files
            parser_files = {}
            command_files = {}
            service_files = {}
            
            for file_id, file_data in files_by_id.items():
                path_lower = file_data["path"].lower()
                content = file_data.get("content", "")
                
                # Classify CLI files
                if any(pattern in content for pattern in ["argparse", "click", "typer", "ArgumentParser", "@click.command"]):
                    parser_files[file_id] = file_data
                elif any(pattern in path_lower for pattern in ["command", "cmd", "cli"]) or \
                     any(pattern in content for pattern in ["def.*command", "class.*Command"]):
                    command_files[file_id] = file_data
                elif any(pattern in path_lower for pattern in ["service", "handler", "processor"]):
                    service_files[file_id] = file_data
            
            # Extract parser -> command edges
            for parser_id, parser_data in parser_files.items():
                content = parser_data.get("content", "")
                
                # Look for command function calls
                for cmd_id, cmd_data in command_files.items():
                    cmd_name = cmd_data["path"].split("/")[-1].replace(".py", "").replace(".js", "")
                    
                    if (f"def {cmd_name}" in content or 
                        f"{cmd_name}(" in content or
                        f"@click.command" in content and cmd_name.lower() in content.lower()):
                        edges.append({
                            "source_file_id": parser_id,
                            "target_file_id": cmd_id,
                            "edge_type": "parser_to_command",
                            "edge_family": "semantic",
                            "confidence": 0.7,
                            "evidence_source": "command_registration",
                            "source_ref": parser_data["path"].split("/")[-1],
                            "target_ref": cmd_name,
                        })
            
            # Extract command -> service edges
            for cmd_id, cmd_data in command_files.items():
                content = cmd_data.get("content", "")
                
                # Look for service calls in commands
                for service_id, service_data in service_files.items():
                    service_name = service_data["path"].split("/")[-1].replace(".py", "").replace(".js", "")
                    
                    if (f"{service_name}(" in content or 
                        f"import.*{service_name}" in content or
                        service_name.lower() in content.lower()):
                        edges.append({
                            "source_file_id": cmd_id,
                            "target_file_id": service_id,
                            "edge_type": "command_to_service",
                            "edge_family": "semantic",
                            "confidence": 0.6,
                            "evidence_source": "service_usage",
                            "source_ref": cmd_data["path"].split("/")[-1],
                            "target_ref": service_name,
                        })
            
        except Exception as e:
            logger.error(f"CLI tool edge extraction failed: {e}")
        
        return edges
    
    def _extract_library_sdk_edges(self, files_by_id: Dict) -> List[Dict]:
        """Extract library SDK semantic edges."""
        edges = []
        
        try:
            # Find library-related files
            export_files = {}
            impl_files = {}
            interface_files = {}
            
            for file_id, file_data in files_by_id.items():
                path_lower = file_data["path"].lower()
                content = file_data.get("content", "")
                
                # Classify library files
                if any(pattern in path_lower for pattern in ["__init__", "index", "main", "lib", "api"]) and \
                   any(pattern in content for pattern in ["export", "__all__", "module.exports"]):
                    export_files[file_id] = file_data
                elif any(pattern in path_lower for pattern in ["impl", "implementation", "core"]):
                    impl_files[file_id] = file_data
                elif any(pattern in content for pattern in ["interface", "abstract", "Protocol", "ABC"]) or \
                     any(pattern in path_lower for pattern in ["interface", "protocol", "types"]):
                    interface_files[file_id] = file_data
            
            # Extract export -> implementation edges
            for export_id, export_data in export_files.items():
                content = export_data.get("content", "")
                
                # Look for implementation imports/references
                for impl_id, impl_data in impl_files.items():
                    impl_name = impl_data["path"].split("/")[-1].replace(".py", "").replace(".js", "").replace(".ts", "")
                    
                    if (f"from.*{impl_name}" in content or 
                        f"import.*{impl_name}" in content or
                        f"require.*{impl_name}" in content):
                        edges.append({
                            "source_file_id": export_id,
                            "target_file_id": impl_id,
                            "edge_type": "export_to_implementation",
                            "edge_family": "semantic",
                            "confidence": 0.7,
                            "evidence_source": "implementation_import",
                            "source_ref": export_data["path"].split("/")[-1],
                            "target_ref": impl_name,
                        })
            
            # Extract interface -> implementation edges
            for interface_id, interface_data in interface_files.items():
                interface_name = interface_data["path"].split("/")[-1].replace(".py", "").replace(".java", "").replace(".ts", "")
                
                # Look for implementations of the interface
                for impl_id, impl_data in impl_files.items():
                    content = impl_data.get("content", "")
                    
                    if (f"implements {interface_name}" in content or 
                        f"extends {interface_name}" in content or
                        f"class.*({interface_name})" in content):
                        edges.append({
                            "source_file_id": interface_id,
                            "target_file_id": impl_id,
                            "edge_type": "interface_to_implementation",
                            "edge_family": "semantic",
                            "confidence": 0.8,
                            "evidence_source": "interface_implementation",
                            "source_ref": interface_name,
                            "target_ref": impl_data["path"].split("/")[-1],
                        })
            
        except Exception as e:
            logger.error(f"Library SDK edge extraction failed: {e}")
        
        return edges
    
    def _extract_ml_pipeline_edges(self, files_by_id: Dict) -> List[Dict]:
        """Extract ML pipeline semantic edges."""
        edges = []
        
        try:
            # Find ML-related files
            pipeline_files = {}
            training_files = {}
            model_files = {}
            data_files = {}
            
            for file_id, file_data in files_by_id.items():
                path_lower = file_data["path"].lower()
                content = file_data.get("content", "")
                
                # Classify ML files
                if any(pattern in path_lower for pattern in ["pipeline", "workflow", "orchestr"]):
                    pipeline_files[file_id] = file_data
                elif any(pattern in path_lower for pattern in ["train", "fit", "learn"]) or \
                     any(pattern in content for pattern in [".fit(", ".train(", "train_model"]):
                    training_files[file_id] = file_data
                elif any(pattern in path_lower for pattern in ["model", "network", "arch"]) or \
                     any(pattern in content for pattern in ["torch.nn", "tensorflow", "sklearn", "model.save"]):
                    model_files[file_id] = file_data
                elif any(pattern in path_lower for pattern in ["data", "dataset", "preprocess", "feature"]):
                    data_files[file_id] = file_data
            
            # Extract pipeline -> training edges
            for pipeline_id, pipeline_data in pipeline_files.items():
                content = pipeline_data.get("content", "")
                
                # Look for training script calls
                for train_id, train_data in training_files.items():
                    train_name = train_data["path"].split("/")[-1].replace(".py", "")
                    
                    if (f"{train_name}(" in content or 
                        f"import.*{train_name}" in content or
                        "subprocess" in content and train_name in content):
                        edges.append({
                            "source_file_id": pipeline_id,
                            "target_file_id": train_id,
                            "edge_type": "pipeline_to_training",
                            "edge_family": "semantic",
                            "confidence": 0.7,
                            "evidence_source": "training_invocation",
                            "source_ref": pipeline_data["path"].split("/")[-1],
                            "target_ref": train_name,
                        })
            
            # Extract training -> model edges
            for train_id, train_data in training_files.items():
                content = train_data.get("content", "")
                
                # Look for model usage/creation
                for model_id, model_data in model_files.items():
                    model_name = model_data["path"].split("/")[-1].replace(".py", "")
                    
                    if (f"from.*{model_name}" in content or 
                        f"import.*{model_name}" in content or
                        model_name.lower() in content.lower()):
                        edges.append({
                            "source_file_id": train_id,
                            "target_file_id": model_id,
                            "edge_type": "training_to_model",
                            "edge_family": "semantic",
                            "confidence": 0.6,
                            "evidence_source": "model_usage",
                            "source_ref": train_data["path"].split("/")[-1],
                            "target_ref": model_name,
                        })
            
            # Extract data -> training edges
            for data_id, data_data in data_files.items():
                data_name = data_data["path"].split("/")[-1].replace(".py", "")
                
                # Look for data usage in training
                for train_id, train_data in training_files.items():
                    content = train_data.get("content", "")
                    
                    if (f"from.*{data_name}" in content or 
                        f"import.*{data_name}" in content or
                        data_name.lower() in content.lower()):
                        edges.append({
                            "source_file_id": data_id,
                            "target_file_id": train_id,
                            "edge_type": "data_to_training",
                            "edge_family": "semantic",
                            "confidence": 0.6,
                            "evidence_source": "data_usage",
                            "source_ref": data_name,
                            "target_ref": train_data["path"].split("/")[-1],
                        })
            
        except Exception as e:
            logger.error(f"ML pipeline edge extraction failed: {e}")
        
        return edges
    
    def _extract_universal_semantic_edges(self, files_by_id: Dict) -> List[Dict]:
        """Extract universal semantic edges that apply to all archetypes."""
        edges = []
        
        try:
            # Find test files and config files
            test_files = {}
            config_files = {}
            
            for file_id, file_data in files_by_id.items():
                path_lower = file_data["path"].lower()
                content = file_data.get("content", "")
                
                # Classify universal files
                if (file_data.get("is_test") or 
                    any(pattern in path_lower for pattern in ["test", "spec", "__test__"]) or
                    any(pattern in content for pattern in ["import.*test", "describe(", "it(", "def test_"])):
                    test_files[file_id] = file_data
                elif any(pattern in path_lower for pattern in [".env", ".toml", ".yaml", ".yml", ".json", ".ini", ".cfg"]):
                    config_files[file_id] = file_data
            
            # Extract test -> target edges
            for test_id, test_data in test_files.items():
                content = test_data.get("content", "")
                test_path = test_data["path"]
                
                # Try to find the target file being tested
                for file_id, file_data in files_by_id.items():
                    if file_id == test_id or file_data.get("is_test"):
                        continue
                    
                    file_name = file_data["path"].split("/")[-1].replace(".py", "").replace(".js", "").replace(".ts", "")
                    
                    # Check if test imports or references the file
                    if (f"from.*{file_name}" in content or 
                        f"import.*{file_name}" in content or
                        f"require.*{file_name}" in content or
                        # Test file naming convention (test_user.py tests user.py)
                        file_name.lower() in test_path.lower()):
                        edges.append({
                            "source_file_id": test_id,
                            "target_file_id": file_id,
                            "edge_type": "test_target",
                            "edge_family": "semantic",
                            "confidence": 0.8,
                            "evidence_source": "test_import",
                            "source_ref": test_data["path"].split("/")[-1],
                            "target_ref": file_name,
                        })
                        break  # One target per test file
            
            # Extract config -> usage edges (files that read config)
            for config_id, config_data in config_files.items():
                config_name = config_data["path"].split("/")[-1]
                
                # Look for files that reference this config
                for file_id, file_data in files_by_id.items():
                    if file_id == config_id:
                        continue
                    
                    content = file_data.get("content", "")
                    
                    if (config_name in content or 
                        any(pattern in content for pattern in ["load_dotenv", "configparser", "yaml.load", "json.load"]) and
                        any(pattern in content.lower() for pattern in ["env", "config", "settings"])):
                        edges.append({
                            "source_file_id": config_id,
                            "target_file_id": file_id,
                            "edge_type": "config_usage",
                            "edge_family": "semantic",
                            "confidence": 0.5,
                            "evidence_source": "config_reference",
                            "source_ref": config_name,
                            "target_ref": file_data["path"].split("/")[-1],
                        })
            
        except Exception as e:
            logger.error(f"Universal semantic edge extraction failed: {e}")
        
        return edges
    
    def _extract_frontend_runtime_edges(self, files_by_id: Dict) -> List[Dict]:
        """Extract frontend runtime heuristic edges."""
        edges = []
        
        try:
            # Find frontend files
            js_files = {}
            html_files = {}
            
            for file_id, file_data in files_by_id.items():
                path_lower = file_data["path"].lower()
                
                if path_lower.endswith((".js", ".jsx", ".ts", ".tsx")):
                    js_files[file_id] = file_data
                elif path_lower.endswith(".html"):
                    html_files[file_id] = file_data
            
            # Extract fetch -> API edges (heuristic)
            for js_id, js_data in js_files.items():
                content = js_data.get("content", "")
                
                # Look for API calls
                api_patterns = [
                    r'fetch\(["\']([^"\']+)["\']',
                    r'axios\.(?:get|post|put|delete)\(["\']([^"\']+)["\']',
                    r'\.(?:get|post|put|delete)\(["\']([^"\']+)["\']',
                ]
                
                for pattern in api_patterns:
                    matches = re.findall(pattern, content)
                    for api_path in matches:
                        if api_path.startswith(("/api", "/v1", "/graphql")):
                            # Try to find backend files that might handle this route
                            for other_id, other_data in files_by_id.items():
                                other_content = other_data.get("content", "")
                                if (api_path in other_content or 
                                    any(route_part in other_content for route_part in api_path.split("/") if len(route_part) > 2)):
                                    edges.append({
                                        "source_file_id": js_id,
                                        "target_file_id": other_id,
                                        "edge_type": "inferred_api_call",
                                        "edge_family": "runtime",
                                        "confidence": 0.3,
                                        "evidence_source": "api_heuristic",
                                        "source_ref": js_data["path"].split("/")[-1],
                                        "target_ref": api_path,
                                    })
                                    break
            
            # Extract event -> handler edges (heuristic)
            for js_id, js_data in js_files.items():
                content = js_data.get("content", "")
                
                # Look for event listeners
                event_patterns = [
                    r'addEventListener\(["\'](\w+)["\']',
                    r'on(\w+)\s*=',
                    r'onClick\s*=',
                    r'onChange\s*=',
                ]
                
                events_found = []
                for pattern in event_patterns:
                    matches = re.findall(pattern, content)
                    events_found.extend(matches)
                
                if events_found:
                    # Look for handler functions in the same or other files
                    for other_id, other_data in js_files.items():
                        other_content = other_data.get("content", "")
                        
                        if any(f"handle{event.capitalize()}" in other_content or 
                               f"on{event.capitalize()}" in other_content 
                               for event in events_found):
                            edges.append({
                                "source_file_id": js_id,
                                "target_file_id": other_id,
                                "edge_type": "event_to_handler",
                                "edge_family": "runtime",
                                "confidence": 0.4,
                                "evidence_source": "event_heuristic",
                                "source_ref": js_data["path"].split("/")[-1],
                                "target_ref": f"event_handlers",
                            })
            
        except Exception as e:
            logger.error(f"Frontend runtime edge extraction failed: {e}")
        
        return edges
    
    def _extract_gui_runtime_edges(self, files_by_id: Dict) -> List[Dict]:
        """Extract GUI runtime heuristic edges."""
        edges = []
        
        try:
            # Find Java GUI files
            java_files = {fid: fdata for fid, fdata in files_by_id.items() 
                         if fdata["path"].lower().endswith(".java")}
            
            # Extract button -> action edges (heuristic)
            for java_id, java_data in java_files.items():
                content = java_data.get("content", "")
                
                # Look for button click handlers
                if "JButton" in content and "ActionListener" in content:
                    # Look for screen transitions
                    for other_id, other_data in java_files.items():
                        if java_id == other_id:
                            continue
                        
                        other_class = other_data["path"].split("/")[-1].replace(".java", "")
                        
                        # Heuristic: if button handler mentions another screen class
                        if (f"new {other_class}" in content or 
                            f"{other_class}(" in content or
                            "setVisible(false)" in content and other_class.lower() in content.lower()):
                            edges.append({
                                "source_file_id": java_id,
                                "target_file_id": other_id,
                                "edge_type": "gui_action_transition",
                                "edge_family": "runtime",
                                "confidence": 0.4,
                                "evidence_source": "gui_heuristic",
                                "source_ref": java_data["path"].split("/")[-1],
                                "target_ref": other_class,
                            })
            
            # Extract menu -> screen edges (heuristic)
            for java_id, java_data in java_files.items():
                content = java_data.get("content", "")
                
                if "JMenu" in content or "JMenuItem" in content:
                    # Look for menu item actions that open screens
                    for other_id, other_data in java_files.items():
                        if java_id == other_id:
                            continue
                        
                        other_class = other_data["path"].split("/")[-1].replace(".java", "")
                        
                        if (other_class in content and 
                            any(pattern in content for pattern in ["actionPerformed", "addActionListener"])):
                            edges.append({
                                "source_file_id": java_id,
                                "target_file_id": other_id,
                                "edge_type": "menu_to_screen",
                                "edge_family": "runtime",
                                "confidence": 0.3,
                                "evidence_source": "menu_heuristic",
                                "source_ref": java_data["path"].split("/")[-1],
                                "target_ref": other_class,
                            })
            
        except Exception as e:
            logger.error(f"GUI runtime edge extraction failed: {e}")
        
        return edges
    
    def _extract_cli_runtime_edges(self, files_by_id: Dict) -> List[Dict]:
        """Extract CLI runtime heuristic edges."""
        edges = []
        
        try:
            # Find CLI-related files
            cli_files = {}
            output_files = {}
            
            for file_id, file_data in files_by_id.items():
                path_lower = file_data["path"].lower()
                content = file_data.get("content", "")
                
                if (any(pattern in content for pattern in ["argparse", "click", "typer", "sys.argv"]) or
                    any(pattern in path_lower for pattern in ["cli", "command", "cmd"])):
                    cli_files[file_id] = file_data
                elif (any(pattern in content for pattern in ["print(", "console.log", "System.out"]) or
                      any(pattern in path_lower for pattern in ["output", "report", "log"])):
                    output_files[file_id] = file_data
            
            # Extract command -> output edges (heuristic)
            for cli_id, cli_data in cli_files.items():
                content = cli_data.get("content", "")
                
                # Look for output generation
                for output_id, output_data in output_files.items():
                    if cli_id == output_id:
                        continue
                    
                    output_name = output_data["path"].split("/")[-1].replace(".py", "").replace(".js", "")
                    
                    # Heuristic: CLI calls output functions
                    if (f"{output_name}(" in content or 
                        f"import.*{output_name}" in content or
                        any(pattern in content for pattern in ["generate_report", "create_output", "write_file"])):
                        edges.append({
                            "source_file_id": cli_id,
                            "target_file_id": output_id,
                            "edge_type": "command_to_output",
                            "edge_family": "runtime",
                            "confidence": 0.4,
                            "evidence_source": "cli_heuristic",
                            "source_ref": cli_data["path"].split("/")[-1],
                            "target_ref": output_name,
                        })
            
            # Extract subprocess -> script edges (heuristic)
            for file_id, file_data in files_by_id.items():
                content = file_data.get("content", "")
                
                if "subprocess" in content or "os.system" in content or "exec(" in content:
                    # Look for script invocations
                    script_patterns = [
                        r'subprocess\.call\(["\']([^"\']+)["\']',
                        r'os\.system\(["\']([^"\']+)["\']',
                        r'exec\(["\']([^"\']+)["\']',
                    ]
                    
                    for pattern in script_patterns:
                        matches = re.findall(pattern, content)
                        for script_ref in matches:
                            # Try to find the referenced script
                            for other_id, other_data in files_by_id.items():
                                if script_ref in other_data["path"]:
                                    edges.append({
                                        "source_file_id": file_id,
                                        "target_file_id": other_id,
                                        "edge_type": "subprocess_invocation",
                                        "edge_family": "runtime",
                                        "confidence": 0.5,
                                        "evidence_source": "subprocess_heuristic",
                                        "source_ref": file_data["path"].split("/")[-1],
                                        "target_ref": script_ref,
                                    })
                                    break
            
        except Exception as e:
            logger.error(f"CLI runtime edge extraction failed: {e}")
        
        return edges
    
    def _extract_universal_runtime_edges(self, files_by_id: Dict) -> List[Dict]:
        """Extract universal runtime heuristic edges."""
        edges = []
        
        try:
            # Extract script -> subprocess edges (any language)
            for file_id, file_data in files_by_id.items():
                content = file_data.get("content", "")
                
                # Look for script execution patterns
                execution_patterns = [
                    r'subprocess\.(?:run|call|Popen)\(["\']([^"\']+)["\']',
                    r'os\.system\(["\']([^"\']+)["\']',
                    r'exec\(["\']([^"\']+)["\']',
                    r'Runtime\.getRuntime\(\)\.exec\(["\']([^"\']+)["\']',
                    r'child_process\.exec\(["\']([^"\']+)["\']',
                ]
                
                for pattern in execution_patterns:
                    matches = re.findall(pattern, content)
                    for script_cmd in matches:
                        # Try to find files that match the command
                        for other_id, other_data in files_by_id.items():
                            if file_id == other_id:
                                continue
                            
                            other_name = other_data["path"].split("/")[-1]
                            if (other_name in script_cmd or 
                                any(part in script_cmd for part in other_name.split(".")[:-1] if len(part) > 2)):
                                edges.append({
                                    "source_file_id": file_id,
                                    "target_file_id": other_id,
                                    "edge_type": "script_execution",
                                    "edge_family": "runtime",
                                    "confidence": 0.4,
                                    "evidence_source": "execution_heuristic",
                                    "source_ref": file_data["path"].split("/")[-1],
                                    "target_ref": script_cmd,
                                })
                                break
            
            # Extract config -> runtime usage edges (heuristic)
            config_files = {fid: fdata for fid, fdata in files_by_id.items() 
                           if any(ext in fdata["path"].lower() for ext in [".env", ".toml", ".yaml", ".json", ".ini"])}
            
            for config_id, config_data in config_files.items():
                config_name = config_data["path"].split("/")[-1]
                
                # Look for runtime config loading
                for file_id, file_data in files_by_id.items():
                    if file_id == config_id:
                        continue
                    
                    content = file_data.get("content", "")
                    
                    # Heuristic: file loads config at runtime
                    if (config_name in content or 
                        any(pattern in content for pattern in [
                            "load_dotenv", "configparser", "yaml.load", "json.load", 
                            "Properties.load", "config.read", "process.env"
                        ])):
                        edges.append({
                            "source_file_id": config_id,
                            "target_file_id": file_id,
                            "edge_type": "runtime_config_load",
                            "edge_family": "runtime",
                            "confidence": 0.3,
                            "evidence_source": "config_heuristic",
                            "source_ref": config_name,
                            "target_ref": file_data["path"].split("/")[-1],
                        })
            
            # Extract database -> query edges (heuristic)
            for file_id, file_data in files_by_id.items():
                content = file_data.get("content", "")
                
                # Look for database operations
                if any(pattern in content.lower() for pattern in [
                    "select ", "insert ", "update ", "delete ", "create table",
                    ".query(", ".execute(", "cursor.", "session."
                ]):
                    # Try to find database/model files
                    for other_id, other_data in files_by_id.items():
                        if file_id == other_id:
                            continue
                        
                        other_path = other_data["path"].lower()
                        if (any(pattern in other_path for pattern in ["model", "schema", "db", "database"]) or
                            any(pattern in other_data.get("content", "") for pattern in ["CREATE TABLE", "class.*Model"])):
                            edges.append({
                                "source_file_id": file_id,
                                "target_file_id": other_id,
                                "edge_type": "runtime_db_query",
                                "edge_family": "runtime",
                                "confidence": 0.3,
                                "evidence_source": "db_heuristic",
                                "source_ref": file_data["path"].split("/")[-1],
                                "target_ref": other_data["path"].split("/")[-1],
                            })
                            break
            
        except Exception as e:
            logger.error(f"Universal runtime edge extraction failed: {e}")
        
        return edges
    
    def _assess_graph_quality(self, structural: Dict, semantic: Dict, runtime: Dict) -> Dict[str, Any]:
        """Assess overall graph quality across all layers."""
        total_edges = structural["edge_count"] + semantic["edge_count"] + runtime["edge_count"]
        
        # Quality assessment
        if total_edges >= 15 and structural["edge_count"] >= 5 and semantic["edge_count"] >= 3:
            quality = "high"
        elif total_edges >= 5 and structural["edge_count"] >= 2:
            quality = "medium"
        else:
            quality = "low"
        
        # Sparsity detection
        sparse = total_edges < 3
        weak_evidence = structural["edge_count"] < 2 and semantic["edge_count"] < 1
        
        # Recommendations
        recommendations = []
        if sparse:
            recommendations.append("Graph is sparse - consider re-indexing with updated parsers")
        if weak_evidence:
            recommendations.append("Weak structural evidence - may need language-specific analysis")
        if semantic["edge_count"] == 0:
            recommendations.append("No semantic relationships detected - check archetype classification")
        
        return {
            "stats": {
                "total_edges": total_edges,
                "structural_edges": structural["edge_count"],
                "semantic_edges": semantic["edge_count"],
                "runtime_edges": runtime["edge_count"],
            },
            "quality": quality,
            "sparse": sparse,
            "weak_evidence": weak_evidence,
            "recommendations": recommendations,
        }
    
    def _empty_graph_result(self, repository_id: str, archetype: str, error: str) -> Dict[str, Any]:
        """Return empty graph result on failure."""
        return {
            "repository_id": repository_id,
            "archetype": archetype,
            "layers": {
                "structural": {"edges": [], "edge_count": 0, "confidence": "low", "limitations": [error]},
                "semantic": {"edges": [], "edge_count": 0, "confidence": "low", "limitations": [error]},
                "runtime": {"edges": [], "edge_count": 0, "confidence": "low", "limitations": [error]},
            },
            "stats": {"total_edges": 0, "structural_edges": 0, "semantic_edges": 0, "runtime_edges": 0},
            "quality": "low",
            "sparse": True,
            "weak_evidence": True,
            "recommendations": ["Graph construction failed - check repository indexing"],
        }