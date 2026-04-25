"""
RepoBrain 10.0 Universal Cross-Repo Intelligence Benchmark
=========================================================

LAYER B: Universal benchmark suite testing cross-repo behavior on multiple repository archetypes.
Tests plausibility and anti-hallucination behavior, not exact wording.
"""

import asyncio
import json
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from pathlib import Path

from tests.shared.test_client import RepobrainTestClient, ApiResponse


@dataclass
class BenchmarkRepoConfig:
    """Configuration for a single repository in the benchmark."""
    repo_url: str
    expected_archetypes: List[str]
    expected_not_archetypes: List[str] = None
    expected_entry_hints: List[str] = None
    notes: str = ""
    allow_weak_evidence: bool = False
    
    def __post_init__(self):
        if self.expected_not_archetypes is None:
            self.expected_not_archetypes = []
        if self.expected_entry_hints is None:
            self.expected_entry_hints = []


@dataclass
class BenchmarkResult:
    """Result of benchmarking a single repository."""
    repo_url: str
    repo_id: str
    scores: Dict[str, float]  # Category -> score (0-10)
    total_score: float
    penalties: List[str]
    details: Dict[str, Any]
    error: Optional[str] = None


class UniversalBenchmarkSuite:
    """
    Universal cross-repo intelligence benchmark suite.
    
    Tests RepoBrain's ability to correctly analyze different repository archetypes
    without hardcoding for specific repos. Focuses on plausibility and anti-hallucination.
    """
    
    def __init__(self, client: RepobrainTestClient):
        self.client = client
        self.default_config = self._load_default_config()
        
    async def run_benchmark(self, config_path: str = None, indexed_only: bool = False) -> Dict[str, Any]:
        """Run full universal benchmark."""
        print("🎯 Starting RepoBrain 10.0 Universal Benchmark...")
        
        config = self._load_config(config_path) if config_path else self.default_config
        results = []
        
        for repo_config in config:
            print(f"📊 Benchmarking {repo_config.repo_url}...")
            result = await self._benchmark_single_repo(repo_config, indexed_only)
            results.append(result)
            
        return self._compile_benchmark_results(results)
        
    async def run_smoke_benchmark(self) -> Dict[str, Any]:
        """Run fast smoke benchmark on 3 repos max."""
        print("💨 Starting RepoBrain 10.0 Smoke Benchmark...")
        
        # Use first 3 repos from default config
        smoke_config = self.default_config[:3]
        results = []
        
        for repo_config in smoke_config:
            print(f"📊 Smoke benchmarking {repo_config.repo_url}...")
            result = await self._benchmark_single_repo(repo_config, indexed_only=True)
            results.append(result)
            
        return self._compile_benchmark_results(results)
        
    async def _benchmark_single_repo(self, config: BenchmarkRepoConfig, indexed_only: bool = False) -> BenchmarkResult:
        """Benchmark a single repository across all dimensions."""
        try:
            # Get or create repo
            repo_id = await self._ensure_repo_available(config.repo_url, indexed_only)
            if not repo_id:
                return BenchmarkResult(
                    repo_url=config.repo_url,
                    repo_id="",
                    scores={},
                    total_score=0.0,
                    penalties=["Repository not available"],
                    details={},
                    error="Repository not available or not indexed"
                )
                
            # Run all benchmark dimensions
            scores = {}
            details = {}
            penalties = []
            
            # 1. Ask Repo purpose + architecture credibility (3.0 points)
            ask_score, ask_details, ask_penalties = await self._benchmark_ask_repo(repo_id, config)
            scores["ask_repo_credibility"] = ask_score
            details["ask_repo"] = ask_details
            penalties.extend(ask_penalties)
            
            # 2. Archetype correctness (1.0 point)
            archetype_score, archetype_details, archetype_penalties = await self._benchmark_archetype(repo_id, config)
            scores["archetype_correctness"] = archetype_score
            details["archetype"] = archetype_details
            penalties.extend(archetype_penalties)
            
            # 3. Entrypoint plausibility (1.0 point)
            entry_score, entry_details, entry_penalties = await self._benchmark_entrypoints(repo_id, config)
            scores["entrypoint_plausibility"] = entry_score
            details["entrypoints"] = entry_details
            penalties.extend(entry_penalties)
            
            # 4. Knowledge Graph usefulness OR sparse honesty (2.0 points)
            graph_score, graph_details, graph_penalties = await self._benchmark_graph(repo_id, config)
            scores["graph_usefulness"] = graph_score
            details["graph"] = graph_details
            penalties.extend(graph_penalties)
            
            # 5. Execution Map plausibility (2.0 points)
            flow_score, flow_details, flow_penalties = await self._benchmark_execution_flow(repo_id, config)
            scores["execution_flow_plausibility"] = flow_score
            details["execution_flow"] = flow_details
            penalties.extend(flow_penalties)
            
            # 6. PR Impact usefulness + confidence sanity (1.0 point)
            impact_score, impact_details, impact_penalties = await self._benchmark_pr_impact(repo_id, config)
            scores["pr_impact_usefulness"] = impact_score
            details["pr_impact"] = impact_details
            penalties.extend(impact_penalties)
            
            # Calculate total score
            total_score = sum(scores.values())
            
            # Apply hallucination penalties (max 2.0 deduction)
            hallucination_penalty = min(len([p for p in penalties if "hallucination" in p.lower()]) * 0.5, 2.0)
            total_score = max(0, total_score - hallucination_penalty)
            
            return BenchmarkResult(
                repo_url=config.repo_url,
                repo_id=repo_id,
                scores=scores,
                total_score=round(total_score, 2),
                penalties=penalties,
                details=details
            )
            
        except Exception as e:
            return BenchmarkResult(
                repo_url=config.repo_url,
                repo_id="",
                scores={},
                total_score=0.0,
                penalties=[f"Benchmark failed: {str(e)}"],
                details={},
                error=str(e)
            )
            
    async def _ensure_repo_available(self, repo_url: str, indexed_only: bool = False) -> Optional[str]:
        """Ensure repository is available and indexed."""
        # First check if repo already exists
        existing_repo = await self.client.get_repo_by_url(repo_url)
        if existing_repo:
            repo_id = existing_repo["id"]
            status = existing_repo.get("status", "unknown")
            
            if status in ["indexed", "completed", "ready"]:
                return repo_id
            elif indexed_only:
                return None  # Don't wait for indexing in indexed-only mode
            else:
                # Wait for indexing to complete
                if await self.client.wait_for_indexing(repo_id, timeout=300):
                    return repo_id
                return None
                
        if indexed_only:
            return None  # Don't create new repos in indexed-only mode
            
        # Create new repo
        response = await self.client.create_repo(repo_url)
        if not response.success:
            return None
            
        repo_id = response.data["id"]
        
        # Wait for indexing
        if await self.client.wait_for_indexing(repo_id, timeout=600):
            return repo_id
            
        return None
        
    # ========================================================================
    # Benchmark Dimensions
    # ========================================================================
    
    async def _benchmark_ask_repo(self, repo_id: str, config: BenchmarkRepoConfig) -> tuple[float, Dict, List[str]]:
        """Benchmark Ask Repo purpose + architecture credibility (3.0 points)."""
        score = 0.0
        details = {}
        penalties = []
        
        try:
            # Test purpose question
            purpose_response = await self.client.ask_repo(repo_id, "What is the main purpose of this repository?")
            if purpose_response.success:
                purpose_answer = purpose_response.data.get("answer", "")
                details["purpose_answer"] = purpose_answer
                
                # Score based on answer quality
                if len(purpose_answer) > 50:
                    score += 1.0  # Has substantial answer
                    
                if any(arch.lower() in purpose_answer.lower() for arch in config.expected_archetypes):
                    score += 0.5  # Mentions expected archetype
                    
                # Penalty for obvious hallucinations
                if "blockchain" in purpose_answer.lower() and "blockchain" not in config.repo_url.lower():
                    penalties.append("Possible hallucination: mentions blockchain")
                    
            # Test architecture question
            arch_response = await self.client.ask_repo(repo_id, "What is the architecture of this codebase?")
            if arch_response.success:
                arch_answer = arch_response.data.get("answer", "")
                details["architecture_answer"] = arch_answer
                
                if len(arch_answer) > 50:
                    score += 1.0  # Has substantial answer
                    
                # Check for confidence indicators
                confidence = arch_response.data.get("answer_confidence", "low")
                details["confidence"] = confidence
                if confidence in ["medium", "high"]:
                    score += 0.5
                    
        except Exception as e:
            details["error"] = str(e)
            penalties.append(f"Ask Repo failed: {str(e)}")
            
        return min(score, 3.0), details, penalties
        
    async def _benchmark_archetype(self, repo_id: str, config: BenchmarkRepoConfig) -> tuple[float, Dict, List[str]]:
        """Benchmark archetype correctness (1.0 point)."""
        score = 0.0
        details = {}
        penalties = []
        
        try:
            response = await self.client.get_archetype(repo_id)
            if response.success:
                data = response.data
                detected_archetypes = data.get("archetypes", [])
                primary_archetype = data.get("primary_archetype", "")
                
                details["detected_archetypes"] = detected_archetypes
                details["primary_archetype"] = primary_archetype
                
                # Check if any expected archetype is detected
                detected_names = [arch.get("name", "") for arch in detected_archetypes if isinstance(arch, dict)]
                detected_names.append(primary_archetype)
                
                for expected in config.expected_archetypes:
                    if any(expected.lower() in detected.lower() for detected in detected_names):
                        score += 0.5
                        break
                        
                # Penalty for detecting explicitly wrong archetypes
                for wrong_arch in config.expected_not_archetypes:
                    if any(wrong_arch.lower() in detected.lower() for detected in detected_names):
                        penalties.append(f"Incorrectly detected archetype: {wrong_arch}")
                        
                # Bonus for confidence
                if isinstance(detected_archetypes, list) and detected_archetypes:
                    first_arch = detected_archetypes[0]
                    if isinstance(first_arch, dict) and first_arch.get("confidence") in ["medium", "high"]:
                        score += 0.5
                        
        except Exception as e:
            details["error"] = str(e)
            
        return min(score, 1.0), details, penalties
        
    async def _benchmark_entrypoints(self, repo_id: str, config: BenchmarkRepoConfig) -> tuple[float, Dict, List[str]]:
        """Benchmark entrypoint plausibility (1.0 point)."""
        score = 0.0
        details = {}
        penalties = []
        
        try:
            response = await self.client.get_entrypoints(repo_id)
            if response.success:
                data = response.data
                primary_entry = data.get("primary_entrypoint")
                candidates = data.get("candidate_entrypoints", [])
                
                details["primary_entrypoint"] = primary_entry
                details["candidates"] = candidates
                
                # Score for having a primary entrypoint
                if primary_entry and isinstance(primary_entry, dict):
                    entry_path = primary_entry.get("path", "")
                    if entry_path and entry_path not in ["null", "undefined", ""]:
                        score += 0.5
                        
                        # Check against expected hints
                        if config.expected_entry_hints:
                            for hint in config.expected_entry_hints:
                                if hint.lower() in entry_path.lower():
                                    score += 0.3
                                    break
                                    
                        # Penalty for obviously wrong entrypoints
                        if any(bad in entry_path.lower() for bad in ["test", "spec", "config", "readme"]):
                            penalties.append(f"Questionable entrypoint: {entry_path}")
                            
                # Score for having reasonable candidates
                if len(candidates) > 0:
                    score += 0.2
                    
        except Exception as e:
            details["error"] = str(e)
            
        return min(score, 1.0), details, penalties
        
    async def _benchmark_graph(self, repo_id: str, config: BenchmarkRepoConfig) -> tuple[float, Dict, List[str]]:
        """Benchmark Knowledge Graph usefulness OR sparse honesty (2.0 points)."""
        score = 0.0
        details = {}
        penalties = []
        
        try:
            # Get graph health first
            health_response = await self.client.get_graph_health(repo_id)
            if health_response.success:
                health_data = health_response.data
                details["graph_health"] = health_data
                
                is_sparse = health_data.get("is_sparse", True)
                edge_count = health_data.get("total_edges", 0)
                
                if is_sparse and edge_count < 10:
                    # Sparse graph - score for honesty
                    if health_data.get("quality") == "low" or "sparse" in str(health_data).lower():
                        score += 1.5  # Honest about sparsity
                else:
                    # Dense graph - score for usefulness
                    score += 1.0
                    
            # Get actual graph
            graph_response = await self.client.get_graph(repo_id, view="files", max_nodes=50)
            if graph_response.success:
                graph_data = graph_response.data
                nodes = graph_data.get("nodes", [])
                edges = graph_data.get("edges", [])
                
                details["node_count"] = len(nodes)
                details["edge_count"] = len(edges)
                
                # Score for reasonable graph structure
                if len(nodes) > 0:
                    score += 0.3
                    
                if len(edges) > 0:
                    score += 0.2
                    
                # Check for broken node IDs
                for node in nodes:
                    if isinstance(node, dict):
                        node_id = node.get("id")
                        if not node_id or node_id in ["null", "undefined", ""]:
                            penalties.append("Graph has null node IDs")
                            break
                            
        except Exception as e:
            details["error"] = str(e)
            
        return min(score, 2.0), details, penalties
        
    async def _benchmark_execution_flow(self, repo_id: str, config: BenchmarkRepoConfig) -> tuple[float, Dict, List[str]]:
        """Benchmark Execution Map plausibility (2.0 points)."""
        score = 0.0
        details = {}
        penalties = []
        
        try:
            response = await self.client.get_execution_flow(repo_id, mode="primary")
            if response.success:
                data = response.data
                details["flow_data"] = data
                
                # Extract primary path from response
                paths = data.get("paths", [])
                primary_path = paths[0] if paths else None
                
                # Score for having flow structure
                if primary_path:
                    nodes = primary_path.get("nodes", [])
                    edges = primary_path.get("edges", [])
                    
                    if nodes:
                        score += 0.5
                        
                    if edges:
                        score += 0.5
                    
                    # Check for reasonable primary flow
                    selected_entry = data.get("selected_entrypoint")
                    if selected_entry:
                        score += 0.5
                        
                        # Penalty for obviously wrong primary entries
                        if any(bad in selected_entry.lower() for bad in ["test", "config", "db", "util"]):
                            penalties.append(f"Questionable flow root: {selected_entry}")
                            
                    # Score for confidence indicators
                    summary = data.get("summary", {})
                    confidence = summary.get("estimated_confidence", 0)
                    if confidence > 0.5:
                        score += 0.5
                    
        except Exception as e:
            details["error"] = str(e)
            
        return min(score, 2.0), details, penalties
        
    async def _benchmark_pr_impact(self, repo_id: str, config: BenchmarkRepoConfig) -> tuple[float, Dict, List[str]]:
        """Benchmark PR Impact usefulness + confidence sanity (1.0 point)."""
        score = 0.0
        details = {}
        penalties = []
        
        try:
            # Test with a trivial change
            trivial_response = await self.client.analyze_pr_impact(repo_id, changed_files=["README.md"])
            if trivial_response.success:
                trivial_data = trivial_response.data
                trivial_risk = trivial_data.get("risk_level", "unknown")
                
                details["trivial_change_risk"] = trivial_risk
                
                # Score for reasonable trivial change assessment
                if trivial_risk in ["low", "medium"]:
                    score += 0.5
                elif trivial_risk == "critical":
                    penalties.append("README change marked as critical risk")
                    
            # Test with a code change
            code_response = await self.client.analyze_pr_impact(repo_id, changed_files=["src/main.py", "app/core.js"])
            if code_response.success:
                code_data = code_response.data
                code_risk = code_data.get("risk_level", "unknown")
                impacted_count = code_data.get("impacted_count", 0)
                
                details["code_change_risk"] = code_risk
                details["impacted_count"] = impacted_count
                
                # Score for having impact analysis
                if impacted_count > 0:
                    score += 0.3
                    
                # Score for reasonable risk assessment
                if code_risk in ["medium", "high"]:
                    score += 0.2
                    
        except Exception as e:
            details["error"] = str(e)
            
        return min(score, 1.0), details, penalties
        
    # ========================================================================
    # Configuration and Results
    # ========================================================================
    
    def _load_default_config(self) -> List[BenchmarkRepoConfig]:
        """Load default 10-repo benchmark configuration."""
        return [
            BenchmarkRepoConfig(
                repo_url="https://github.com/fastapi/full-stack-fastapi-template",
                expected_archetypes=["fullstack_web", "backend_api"],
                expected_not_archetypes=["cli_tool", "java_desktop_gui"],
                expected_entry_hints=["main", "app", "server"],
                notes="Full-stack FastAPI template with frontend and backend"
            ),
            BenchmarkRepoConfig(
                repo_url="https://github.com/vitejs/vite",
                expected_archetypes=["frontend_build_tool", "cli_tool"],
                expected_not_archetypes=["backend_api", "java_desktop_gui"],
                expected_entry_hints=["cli", "bin", "index"],
                notes="Frontend build tool and dev server"
            ),
            BenchmarkRepoConfig(
                repo_url="https://github.com/dhanush-urs/airline_reservation",
                expected_archetypes=["java_desktop_gui", "swing_app"],
                expected_not_archetypes=["backend_api", "cli_tool"],
                expected_entry_hints=["main", "gui", "app"],
                notes="Java Swing desktop application"
            ),
            BenchmarkRepoConfig(
                repo_url="https://github.com/fastapi/typer",
                expected_archetypes=["cli_tool", "python_library"],
                expected_not_archetypes=["fullstack_web", "java_desktop_gui"],
                expected_entry_hints=["cli", "main", "__main__"],
                notes="Python CLI framework library"
            ),
            BenchmarkRepoConfig(
                repo_url="https://github.com/psf/requests",
                expected_archetypes=["python_library", "http_client"],
                expected_not_archetypes=["fullstack_web", "cli_tool"],
                notes="Python HTTP library"
            ),
            BenchmarkRepoConfig(
                repo_url="https://github.com/scikit-learn/scikit-learn",
                expected_archetypes=["python_library", "machine_learning"],
                expected_not_archetypes=["fullstack_web", "java_desktop_gui"],
                notes="Machine learning library"
            ),
            BenchmarkRepoConfig(
                repo_url="https://github.com/h5bp/html5-boilerplate",
                expected_archetypes=["frontend_template", "static_site"],
                expected_not_archetypes=["backend_api", "cli_tool"],
                notes="HTML5 frontend boilerplate"
            ),
            BenchmarkRepoConfig(
                repo_url="https://github.com/vercel/turborepo",
                expected_archetypes=["monorepo_tool", "build_tool"],
                expected_not_archetypes=["java_desktop_gui", "static_site"],
                notes="Monorepo build system"
            ),
            BenchmarkRepoConfig(
                repo_url="https://github.com/docker/awesome-compose",
                expected_archetypes=["docker_examples", "infrastructure"],
                expected_not_archetypes=["java_desktop_gui", "python_library"],
                notes="Docker Compose examples collection",
                allow_weak_evidence=True
            ),
            BenchmarkRepoConfig(
                repo_url="https://github.com/microsoft/vscode",
                expected_archetypes=["electron_app", "desktop_editor"],
                expected_not_archetypes=["cli_tool", "static_site"],
                notes="VS Code editor (large codebase)"
            )
        ]
        
    def _load_config(self, config_path: str) -> List[BenchmarkRepoConfig]:
        """Load benchmark configuration from file."""
        try:
            with open(config_path, 'r') as f:
                data = json.load(f)
                
            configs = []
            for item in data.get("repositories", []):
                config = BenchmarkRepoConfig(
                    repo_url=item["repo_url"],
                    expected_archetypes=item.get("expected_archetypes", []),
                    expected_not_archetypes=item.get("expected_not_archetypes", []),
                    expected_entry_hints=item.get("expected_entry_hints", []),
                    notes=item.get("notes", ""),
                    allow_weak_evidence=item.get("allow_weak_evidence", False)
                )
                configs.append(config)
                
            return configs
            
        except Exception as e:
            print(f"Failed to load config from {config_path}: {e}")
            return self.default_config
            
    def _compile_benchmark_results(self, results: List[BenchmarkResult]) -> Dict[str, Any]:
        """Compile benchmark results into summary format."""
        if not results:
            return {
                "timestamp": time.time(),
                "version": "10.0",
                "test_type": "benchmark",
                "overall_score": 0.0,
                "results": []
            }
            
        # Calculate overall metrics
        total_possible = len(results) * 10.0  # 10 points per repo
        total_actual = sum(r.total_score for r in results)
        overall_score = total_actual / total_possible if total_possible > 0 else 0
        
        # Category averages
        category_scores = {}
        for category in ["ask_repo_credibility", "archetype_correctness", "entrypoint_plausibility", 
                        "graph_usefulness", "execution_flow_plausibility", "pr_impact_usefulness"]:
            scores = [r.scores.get(category, 0) for r in results if category in r.scores]
            category_scores[category] = sum(scores) / len(scores) if scores else 0
            
        # Pass/fail counts
        excellent_count = sum(1 for r in results if r.total_score >= 8.0)
        good_count = sum(1 for r in results if 6.0 <= r.total_score < 8.0)
        acceptable_count = sum(1 for r in results if 4.0 <= r.total_score < 6.0)
        poor_count = sum(1 for r in results if r.total_score < 4.0)
        
        # Collect all penalties
        all_penalties = []
        for result in results:
            for penalty in result.penalties:
                all_penalties.append(f"{result.repo_url}: {penalty}")
                
        return {
            "timestamp": time.time(),
            "version": "10.0",
            "test_type": "benchmark",
            "overall_score": round(overall_score * 10, 2),  # Scale to 0-10
            "total_repos_tested": len(results),
            "category_averages": {k: round(v, 2) for k, v in category_scores.items()},
            "performance_distribution": {
                "excellent": excellent_count,  # 8.0+
                "good": good_count,           # 6.0-7.9
                "acceptable": acceptable_count, # 4.0-5.9
                "poor": poor_count            # <4.0
            },
            "total_penalties": len(all_penalties),
            "penalty_summary": all_penalties[:10],  # Top 10 penalties
            "results": [
                {
                    "repo_url": r.repo_url,
                    "repo_id": r.repo_id,
                    "total_score": r.total_score,
                    "scores": r.scores,
                    "penalties": r.penalties,
                    "error": r.error
                }
                for r in results
            ],
            "summary": f"Universal Benchmark: {round(overall_score * 10, 1)}/10.0 average across {len(results)} repos"
        }