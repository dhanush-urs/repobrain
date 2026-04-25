"""
Shared API client utility for RepoBrain 10.0 tests.
Handles timeouts, retries, structured errors, and endpoint detection.
"""

import asyncio
import json
import time
from typing import Dict, Any, Optional, List, Union
from urllib.parse import urljoin
import httpx
from dataclasses import dataclass


@dataclass
class ApiResponse:
    """Structured API response wrapper."""
    status_code: int
    data: Dict[str, Any]
    success: bool
    error: Optional[str] = None
    endpoint: Optional[str] = None
    duration_ms: Optional[int] = None


class RepobrainTestClient:
    """
    Shared API client for RepoBrain tests.
    
    Features:
    - Request timeouts and retries
    - Structured error handling
    - Endpoint availability detection
    - Support for both old and new endpoints
    """
    
    def __init__(self, base_url: str, timeout: int = 30, max_retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.client = httpx.AsyncClient(timeout=timeout)
        self._endpoint_cache = {}  # Cache endpoint availability
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
        
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
        
    def _build_url(self, endpoint: str) -> str:
        """Build full URL from endpoint path."""
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        return urljoin(self.base_url, endpoint)
        
    async def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retries: int = None
    ) -> ApiResponse:
        """Make HTTP request with retries and error handling."""
        if retries is None:
            retries = self.max_retries
            
        url = self._build_url(endpoint)
        start_time = time.time()
        
        for attempt in range(retries + 1):
            try:
                if method.upper() == "GET":
                    response = await self.client.get(url, params=params)
                elif method.upper() == "POST":
                    response = await self.client.post(url, json=data, params=params)
                elif method.upper() == "PUT":
                    response = await self.client.put(url, json=data, params=params)
                elif method.upper() == "DELETE":
                    response = await self.client.delete(url, params=params)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                    
                duration_ms = int((time.time() - start_time) * 1000)
                
                # Parse response
                try:
                    response_data = response.json()
                except json.JSONDecodeError:
                    response_data = {"raw_response": response.text}
                    
                return ApiResponse(
                    status_code=response.status_code,
                    data=response_data,
                    success=200 <= response.status_code < 300,
                    error=None if 200 <= response.status_code < 300 else f"HTTP {response.status_code}",
                    endpoint=endpoint,
                    duration_ms=duration_ms
                )
                
            except httpx.TimeoutException:
                if attempt == retries:
                    return ApiResponse(
                        status_code=0,
                        data={},
                        success=False,
                        error="Request timeout",
                        endpoint=endpoint,
                        duration_ms=int((time.time() - start_time) * 1000)
                    )
                await asyncio.sleep(1 * (attempt + 1))  # Exponential backoff
                
            except Exception as e:
                if attempt == retries:
                    return ApiResponse(
                        status_code=0,
                        data={},
                        success=False,
                        error=f"Request failed: {str(e)}",
                        endpoint=endpoint,
                        duration_ms=int((time.time() - start_time) * 1000)
                    )
                await asyncio.sleep(1 * (attempt + 1))
                
        # Should never reach here
        return ApiResponse(
            status_code=0,
            data={},
            success=False,
            error="Max retries exceeded",
            endpoint=endpoint
        )
        
    async def check_endpoint_availability(self, endpoint: str) -> bool:
        """Check if an endpoint is available (not 404/501)."""
        if endpoint in self._endpoint_cache:
            return self._endpoint_cache[endpoint]
            
        response = await self._make_request("GET", endpoint, retries=1)
        available = response.status_code not in [404, 501, 502, 503]
        self._endpoint_cache[endpoint] = available
        return available
        
    # ========================================================================
    # Repository Management
    # ========================================================================
    
    async def create_repo(self, repo_url: str, branch: str = "main", local_path: str = None) -> ApiResponse:
        """Create a new repository."""
        data = {"repo_url": repo_url, "branch": branch}
        if local_path:
            data["local_path"] = local_path
        return await self._make_request("POST", "/api/v1/repos", data=data)
        
    async def list_repos(self) -> ApiResponse:
        """List all repositories."""
        return await self._make_request("GET", "/api/v1/repos")
        
    async def get_repo(self, repo_id: str) -> ApiResponse:
        """Get repository by ID."""
        return await self._make_request("GET", f"/api/v1/repos/{repo_id}")
        
    async def get_repo_by_url(self, repo_url: str) -> Optional[Dict[str, Any]]:
        """Find repository by URL with robust matching."""
        response = await self.list_repos()
        if not response.success:
            return None
        
        # Normalize the search URL
        normalized_search = self._normalize_repo_url(repo_url)
        
        for repo in response.data.get("items", []):
            stored_url = repo.get("repo_url", "")
            normalized_stored = self._normalize_repo_url(stored_url)
            
            # Try exact normalized match first
            if normalized_search == normalized_stored:
                return repo
        
        # Fallback: try owner/repo extraction for GitHub URLs
        search_owner_repo = self._extract_github_owner_repo(repo_url)
        if search_owner_repo:
            for repo in response.data.get("items", []):
                stored_url = repo.get("repo_url", "")
                stored_owner_repo = self._extract_github_owner_repo(stored_url)
                if search_owner_repo == stored_owner_repo:
                    return repo
        
        return None
    
    def _normalize_repo_url(self, url: str) -> str:
        """Normalize repository URL for comparison."""
        if not url:
            return ""
        
        # Lowercase
        url = url.lower()
        
        # Remove trailing slash
        url = url.rstrip("/")
        
        # Remove .git suffix
        if url.endswith(".git"):
            url = url[:-4]
        
        # Normalize protocol
        url = url.replace("http://", "https://")
        
        # Normalize github.com variants
        url = url.replace("github.com/", "github.com/")
        
        return url
    
    def _extract_github_owner_repo(self, url: str) -> Optional[tuple]:
        """Extract owner/repo pair from GitHub URL."""
        try:
            # Normalize first
            normalized = self._normalize_repo_url(url)
            
            # Extract from github.com URLs
            if "github.com/" in normalized:
                parts = normalized.split("github.com/")
                if len(parts) == 2:
                    path = parts[1].strip("/")
                    path_parts = path.split("/")
                    if len(path_parts) >= 2:
                        owner = path_parts[0]
                        repo = path_parts[1]
                        return (owner, repo)
        except Exception:
            pass
        
        return None
        
    # ========================================================================
    # Analysis Endpoints
    # ========================================================================
    
    async def get_analysis_snapshot(self, repo_id: str) -> ApiResponse:
        """Get comprehensive analysis snapshot."""
        return await self._make_request("GET", f"/api/v1/repos/{repo_id}/analysis-snapshot")
        
    async def get_archetype(self, repo_id: str) -> ApiResponse:
        """Get repository archetype detection."""
        return await self._make_request("GET", f"/api/v1/repos/{repo_id}/archetype")
        
    async def get_entrypoints(self, repo_id: str, archetype: str = "generic_codebase") -> ApiResponse:
        """Get repository entrypoints."""
        params = {"archetype": archetype} if archetype != "generic_codebase" else None
        return await self._make_request("GET", f"/api/v1/repos/{repo_id}/entrypoints", params=params)
        
    async def get_file_intelligence(self, repo_id: str, limit: int = 200) -> ApiResponse:
        """Get per-file intelligence metadata."""
        params = {"limit": limit}
        return await self._make_request("GET", f"/api/v1/repos/{repo_id}/intelligence", params=params)
        
    async def get_file_roles(self, repo_id: str, archetype: str = "generic_codebase", limit: int = 200) -> ApiResponse:
        """Get file role classifications."""
        params = {"archetype": archetype, "limit": limit}
        return await self._make_request("GET", f"/api/v1/repos/{repo_id}/file-roles", params=params)
        
    # ========================================================================
    # Graph Endpoints
    # ========================================================================
    
    async def get_graph(self, repo_id: str, view: str = "clusters", **kwargs) -> ApiResponse:
        """Get repository knowledge graph."""
        params = {"view": view, **kwargs}
        return await self._make_request("GET", f"/api/v1/repos/{repo_id}/graph", params=params)
        
    async def get_graph_health(self, repo_id: str) -> ApiResponse:
        """Get graph health metrics."""
        return await self._make_request("GET", f"/api/v1/repos/{repo_id}/graph-health")
        
    async def get_graph_data(self, repo_id: str, **kwargs) -> ApiResponse:
        """Get legacy graph data (for RepoGraphCanvas)."""
        return await self._make_request("GET", f"/api/v1/repos/{repo_id}/graph/data", params=kwargs)
        
    # ========================================================================
    # Execution Flow Endpoints
    # ========================================================================
    
    async def get_execution_flow(self, repo_id: str, mode: str = "primary", **kwargs) -> ApiResponse:
        """Get execution flow map."""
        params = {"mode": mode, **kwargs}
        return await self._make_request("GET", f"/api/v1/repos/{repo_id}/flows", params=params)
        
    # ========================================================================
    # Ask Repo (Semantic) Endpoints
    # ========================================================================
    
    async def ask_repo(self, repo_id: str, question: str, **kwargs) -> ApiResponse:
        """Ask repository question (semantic search)."""
        # Try multiple possible endpoints for Ask Repo
        endpoints_to_try = [
            f"/api/v1/repos/{repo_id}/chat",
            f"/api/v1/repos/{repo_id}/ask",
            f"/api/v1/semantic/repo/{repo_id}/ask",
            f"/api/v1/repos/{repo_id}/semantic/ask"
        ]
        
        data = {"question": question, **kwargs}
        
        for endpoint in endpoints_to_try:
            if await self.check_endpoint_availability(endpoint):
                return await self._make_request("POST", endpoint, data=data)
                
        # Fallback: return structured error
        return ApiResponse(
            status_code=501,
            data={"error": "Ask Repo endpoint not found"},
            success=False,
            error="Ask Repo endpoint not implemented"
        )
        
    # ========================================================================
    # PR Impact Endpoints
    # ========================================================================
    
    async def analyze_pr_impact(self, repo_id: str, changed_files: List[str] = None, diff: str = None, **kwargs) -> ApiResponse:
        """Analyze PR impact."""
        data = {
            "changed_files": changed_files or [],
            "diff": diff,
            **kwargs
        }
        
        # Try both endpoint variants
        endpoints_to_try = [
            f"/api/v1/repos/{repo_id}/impact",
            f"/api/v1/repos/{repo_id}/impact/analyze"
        ]
        
        for endpoint in endpoints_to_try:
            if await self.check_endpoint_availability(endpoint):
                return await self._make_request("POST", endpoint, data=data)
                
        return ApiResponse(
            status_code=501,
            data={"error": "PR Impact endpoint not found"},
            success=False,
            error="PR Impact endpoint not implemented"
        )
        
    # ========================================================================
    # Files and Search Endpoints
    # ========================================================================
    
    async def get_files(self, repo_id: str, **kwargs) -> ApiResponse:
        """Get repository files."""
        return await self._make_request("GET", f"/api/v1/repos/{repo_id}/files", params=kwargs)
        
    async def get_file_detail(self, repo_id: str, file_id: str) -> ApiResponse:
        """Get file detail."""
        return await self._make_request("GET", f"/api/v1/repos/{repo_id}/files/{file_id}")
        
    async def search_repo(self, repo_id: str, query: str, **kwargs) -> ApiResponse:
        """Search repository."""
        data = {"query": query, "top_k": kwargs.get("top_k", 5)}
        return await self._make_request("POST", f"/api/v1/repos/{repo_id}/search", data=data)
        
    # ========================================================================
    # Job and Status Endpoints
    # ========================================================================
    
    async def get_repo_status(self, repo_id: str) -> ApiResponse:
        """Get repository indexing status."""
        return await self.get_repo(repo_id)  # Status is in repo response
        
    async def trigger_repo_parse(self, repo_id: str) -> ApiResponse:
        """Trigger repository parsing."""
        return await self._make_request("POST", f"/api/v1/repos/{repo_id}/parse")
        
    async def wait_for_indexing(self, repo_id: str, timeout: int = 300, poll_interval: int = 5) -> bool:
        """Wait for repository to finish indexing."""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            response = await self.get_repo_status(repo_id)
            if response.success:
                status = response.data.get("status", "unknown")
                if status in ["indexed", "completed", "ready"]:
                    return True
                elif status in ["failed", "error"]:
                    return False
                    
            await asyncio.sleep(poll_interval)
            
        return False  # Timeout
        
    # ========================================================================
    # Health and System Endpoints
    # ========================================================================
    
    async def health_check(self) -> ApiResponse:
        """Check API health."""
        return await self._make_request("GET", "/api/v1/health")
        
    async def get_root(self) -> ApiResponse:
        """Get API root information."""
        return await self._make_request("GET", "/")