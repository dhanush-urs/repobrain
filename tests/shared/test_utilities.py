"""
Shared test utilities for RepoBrain 10.0 Hybrid Test Suite.
Common functions for validation, scoring, and test data management.
"""

import re
import time
from typing import Dict, Any, List, Optional, Union
from urllib.parse import urlparse


class ValidationUtils:
    """Utilities for validating API responses and data structures."""
    
    @staticmethod
    def is_valid_repo_id(repo_id: str) -> bool:
        """Check if a repository ID is valid (non-empty, not null-like)."""
        if not repo_id or not isinstance(repo_id, str):
            return False
        return repo_id.strip() not in ["", "null", "undefined", "None"]
    
    @staticmethod
    def is_valid_file_path(path: str) -> bool:
        """Check if a file path is valid."""
        if not path or not isinstance(path, str):
            return False
        path = path.strip()
        return path not in ["", "null", "undefined", "None"] and not path.startswith("/null")
    
    @staticmethod
    def is_valid_url(url: str) -> bool:
        """Check if a URL is valid."""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception:
            return False
    
    @staticmethod
    def validate_enum_field(value: Any, valid_values: List[str]) -> bool:
        """Validate that a field value is in the allowed enum values."""
        return value in valid_values
    
    @staticmethod
    def validate_response_schema(data: Dict[str, Any], required_fields: List[str]) -> List[str]:
        """Validate response has required fields. Returns list of missing fields."""
        missing = []
        for field in required_fields:
            if field not in data:
                missing.append(field)
        return missing
    
    @staticmethod
    def detect_null_like_values(data: Any, path: str = "") -> List[str]:
        """Recursively detect null-like values in data structure."""
        issues = []
        
        if isinstance(data, dict):
            for key, value in data.items():
                current_path = f"{path}.{key}" if path else key
                issues.extend(ValidationUtils.detect_null_like_values(value, current_path))
        elif isinstance(data, list):
            for i, item in enumerate(data):
                current_path = f"{path}[{i}]"
                issues.extend(ValidationUtils.detect_null_like_values(item, current_path))
        elif isinstance(data, str):
            if data in ["null", "undefined", "", "None"]:
                issues.append(f"Null-like value at {path}: '{data}'")
        elif data is None:
            issues.append(f"Null value at {path}")
            
        return issues


class ScoringUtils:
    """Utilities for scoring benchmark results."""
    
    @staticmethod
    def score_text_quality(text: str, min_length: int = 50) -> float:
        """Score text quality based on length and content."""
        if not text or not isinstance(text, str):
            return 0.0
            
        text = text.strip()
        if len(text) < min_length:
            return 0.3
            
        # Basic quality indicators
        score = 0.5  # Base score for having text
        
        if len(text) > 100:
            score += 0.2
        if len(text) > 200:
            score += 0.2
            
        # Check for structured content
        if any(indicator in text.lower() for indicator in ["framework", "library", "application", "service"]):
            score += 0.1
            
        return min(score, 1.0)
    
    @staticmethod
    def score_archetype_match(detected: List[str], expected: List[str], not_expected: List[str] = None) -> float:
        """Score archetype detection accuracy."""
        if not expected:
            return 0.5  # Neutral score if no expectations
            
        score = 0.0
        not_expected = not_expected or []
        
        # Check for expected archetypes
        for exp in expected:
            if any(exp.lower() in det.lower() for det in detected):
                score += 1.0 / len(expected)  # Proportional scoring
                
        # Penalty for detecting wrong archetypes
        for wrong in not_expected:
            if any(wrong.lower() in det.lower() for det in detected):
                score -= 0.3
                
        return max(0.0, min(score, 1.0))
    
    @staticmethod
    def score_confidence_appropriateness(confidence: str, context: Dict[str, Any]) -> float:
        """Score whether confidence level is appropriate for the context."""
        if confidence not in ["low", "medium", "high"]:
            return 0.0
            
        # This is a heuristic - in practice would need more sophisticated logic
        evidence_count = context.get("evidence_count", 0)
        
        if confidence == "high" and evidence_count < 3:
            return 0.3  # High confidence with little evidence is suspicious
        elif confidence == "low" and evidence_count > 10:
            return 0.7  # Low confidence with lots of evidence might be overly cautious
        else:
            return 1.0  # Reasonable confidence level
    
    @staticmethod
    def detect_hallucination_indicators(text: str, repo_context: Dict[str, Any]) -> List[str]:
        """Detect potential hallucination indicators in text."""
        indicators = []
        
        if not text or not isinstance(text, str):
            return indicators
            
        text_lower = text.lower()
        repo_url = repo_context.get("repo_url", "").lower()
        
        # Technology mismatches
        if "blockchain" in text_lower and "blockchain" not in repo_url:
            indicators.append("Mentions blockchain without evidence")
            
        if "machine learning" in text_lower and "ml" not in repo_url and "ai" not in repo_url:
            indicators.append("Mentions ML without clear evidence")
            
        if "microservices" in text_lower and "micro" not in repo_url:
            indicators.append("Claims microservices architecture")
            
        # Overly specific claims
        if re.search(r'\d+\s*(users?|customers?|downloads?)', text_lower):
            indicators.append("Makes specific usage claims")
            
        return indicators


class TestDataUtils:
    """Utilities for managing test data and fixtures."""
    
    @staticmethod
    def create_test_repo_config(repo_url: str, **kwargs) -> Dict[str, Any]:
        """Create a test repository configuration."""
        return {
            "repo_url": repo_url,
            "expected_archetypes": kwargs.get("expected_archetypes", []),
            "expected_not_archetypes": kwargs.get("expected_not_archetypes", []),
            "expected_entry_hints": kwargs.get("expected_entry_hints", []),
            "notes": kwargs.get("notes", ""),
            "allow_weak_evidence": kwargs.get("allow_weak_evidence", False)
        }
    
    @staticmethod
    def generate_test_pr_changes() -> List[Dict[str, Any]]:
        """Generate test PR change scenarios."""
        return [
            {
                "name": "trivial_readme",
                "changed_files": ["README.md"],
                "expected_risk": ["low", "medium"],
                "description": "Trivial documentation change"
            },
            {
                "name": "core_logic",
                "changed_files": ["src/main.py", "app/core.js"],
                "expected_risk": ["medium", "high"],
                "description": "Core application logic changes"
            },
            {
                "name": "config_only",
                "changed_files": ["config.json", "settings.py"],
                "expected_risk": ["low", "medium"],
                "description": "Configuration-only changes"
            },
            {
                "name": "test_files",
                "changed_files": ["tests/test_main.py", "spec/core_spec.js"],
                "expected_risk": ["low"],
                "description": "Test file changes only"
            }
        ]
    
    @staticmethod
    def create_mock_api_response(status_code: int = 200, data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create a mock API response for testing."""
        return {
            "status_code": status_code,
            "data": data or {},
            "success": 200 <= status_code < 300,
            "error": None if 200 <= status_code < 300 else f"HTTP {status_code}",
            "duration_ms": 100
        }


class PerformanceUtils:
    """Utilities for performance measurement and timeout handling."""
    
    @staticmethod
    def measure_duration(func):
        """Decorator to measure function execution duration."""
        def wrapper(*args, **kwargs):
            start_time = time.time()
            result = func(*args, **kwargs)
            duration_ms = int((time.time() - start_time) * 1000)
            
            if hasattr(result, '__dict__'):
                result.duration_ms = duration_ms
            elif isinstance(result, dict):
                result['duration_ms'] = duration_ms
                
            return result
        return wrapper
    
    @staticmethod
    def is_timeout_reasonable(duration_ms: int, operation_type: str) -> bool:
        """Check if operation duration is reasonable."""
        thresholds = {
            "api_call": 5000,      # 5 seconds
            "repo_creation": 10000, # 10 seconds
            "graph_query": 15000,   # 15 seconds
            "ask_repo": 30000,      # 30 seconds
            "pr_impact": 20000,     # 20 seconds
        }
        
        threshold = thresholds.get(operation_type, 10000)
        return duration_ms <= threshold
    
    @staticmethod
    def calculate_performance_score(durations: List[int]) -> float:
        """Calculate performance score based on operation durations."""
        if not durations:
            return 0.0
            
        avg_duration = sum(durations) / len(durations)
        
        # Score based on average duration (lower is better)
        if avg_duration < 1000:    # < 1 second
            return 1.0
        elif avg_duration < 5000:  # < 5 seconds
            return 0.8
        elif avg_duration < 10000: # < 10 seconds
            return 0.6
        elif avg_duration < 30000: # < 30 seconds
            return 0.4
        else:
            return 0.2