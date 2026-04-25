#!/usr/bin/env python3
"""
RepoBrain 10.0 Hybrid Test Suite CLI
====================================

Comprehensive validation system combining:
1. DETERMINISTIC E2E CONTRACT + REGRESSION TESTS
2. UNIVERSAL CROSS-REPO INTELLIGENCE BENCHMARK TESTS

Usage:
    python scripts/test_repobrain_hybrid.py --contracts
    python scripts/test_repobrain_hybrid.py --benchmark
    python scripts/test_repobrain_hybrid.py --hybrid
    python scripts/test_repobrain_hybrid.py --smoke
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

# Add the API app to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "api"))

# Add parent directory to path for relative imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.e2e.test_repobrain_contracts import ContractTestSuite
from tests.benchmarks.test_universal_benchmark import UniversalBenchmarkSuite
from tests.shared.test_client import RepobrainTestClient
from tests.shared.report_generator import ReportGenerator


class HybridTestRunner:
    """Main test runner for RepoBrain 10.0 hybrid validation."""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.client = RepobrainTestClient(base_url)
        self.report_gen = ReportGenerator()
        
    async def run_contracts_only(self, repo_id: str = None) -> Dict[str, Any]:
        """Run deterministic E2E contract and regression tests only."""
        print("🔧 Running RepoBrain 10.0 Contract Tests...")
        
        contract_suite = ContractTestSuite(self.client)
        results = await contract_suite.run_all_tests(target_repo_id=repo_id)
        
        # Generate reports
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = f"tests/reports/contracts_{timestamp}.json"
        md_path = f"tests/reports/contracts_{timestamp}.md"
        
        self.report_gen.generate_contract_reports(results, json_path, md_path)
        
        print(f"📊 Contract test results saved to {json_path} and {md_path}")
        return results
        
    async def run_benchmark_only(self, config_path: str = None, indexed_only: bool = False) -> Dict[str, Any]:
        """Run universal cross-repo benchmark tests only."""
        print("🎯 Running RepoBrain 10.0 Universal Benchmark...")
        
        benchmark_suite = UniversalBenchmarkSuite(self.client)
        results = await benchmark_suite.run_benchmark(
            config_path=config_path,
            indexed_only=indexed_only
        )
        
        # Generate reports
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = f"benchmarks/reports/universal_benchmark_{timestamp}.json"
        md_path = f"benchmarks/reports/universal_benchmark_{timestamp}.md"
        
        self.report_gen.generate_benchmark_reports(results, json_path, md_path)
        
        print(f"📊 Benchmark results saved to {json_path} and {md_path}")
        return results
        
    async def run_hybrid(self, repo_id: str = None, config_path: str = None, indexed_only: bool = False) -> Dict[str, Any]:
        """Run both contract tests and universal benchmark."""
        print("🚀 Running RepoBrain 10.0 Hybrid Test Suite...")
        
        # Run both test layers
        contract_results = await self.run_contracts_only(repo_id)
        benchmark_results = await self.run_benchmark_only(config_path, indexed_only)
        
        # Combine results
        hybrid_results = {
            "timestamp": datetime.now().isoformat(),
            "version": "10.0",
            "test_mode": "hybrid",
            "contract_results": contract_results,
            "benchmark_results": benchmark_results,
            "overall_health": self._compute_overall_health(contract_results, benchmark_results)
        }
        
        # Generate hybrid report
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = f"tests/reports/hybrid_{timestamp}.json"
        md_path = f"tests/reports/hybrid_{timestamp}.md"
        
        self.report_gen.generate_hybrid_reports(hybrid_results, json_path, md_path)
        
        print(f"📊 Hybrid test results saved to {json_path} and {md_path}")
        return hybrid_results
        
    async def run_smoke(self) -> Dict[str, Any]:
        """Run fast smoke tests - contracts on 1-2 repos, benchmark on 3 repos max."""
        print("💨 Running RepoBrain 10.0 Smoke Tests...")
        
        # Fast contract tests
        contract_suite = ContractTestSuite(self.client)
        contract_results = await contract_suite.run_smoke_tests()
        
        # Fast benchmark tests
        benchmark_suite = UniversalBenchmarkSuite(self.client)
        benchmark_results = await benchmark_suite.run_smoke_benchmark()
        
        # Combine results
        smoke_results = {
            "timestamp": datetime.now().isoformat(),
            "version": "10.0",
            "test_mode": "smoke",
            "contract_results": contract_results,
            "benchmark_results": benchmark_results,
            "overall_health": self._compute_overall_health(contract_results, benchmark_results)
        }
        
        # Generate and save smoke reports
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = f"tests/reports/smoke_{timestamp}.json"
        md_path = f"tests/reports/smoke_{timestamp}.md"
        
        self.report_gen.generate_smoke_reports(smoke_results, json_path, md_path)
        
        print(f"📊 Smoke test results saved to {json_path} and {md_path}")
        print("✅ Smoke tests completed")
        return smoke_results
        
    def _compute_overall_health(self, contract_results: Dict, benchmark_results: Dict) -> Dict[str, Any]:
        """Compute overall system health from both test layers."""
        contract_health = contract_results.get("health_summary", {})
        benchmark_health = benchmark_results.get("overall_score", 0) / 10.0  # normalize to 0-1
        
        contracts_passed = contract_health.get("contracts_passed", 0)
        contracts_total = contract_health.get("contracts_total", 1)
        contract_pass_rate = contracts_passed / contracts_total if contracts_total > 0 else 0
        
        overall_score = (contract_pass_rate * 0.6) + (benchmark_health * 0.4)
        
        if overall_score >= 0.9:
            status = "excellent"
        elif overall_score >= 0.75:
            status = "good"
        elif overall_score >= 0.6:
            status = "acceptable"
        elif overall_score >= 0.4:
            status = "concerning"
        else:
            status = "critical"
            
        return {
            "overall_score": round(overall_score, 3),
            "status": status,
            "contract_pass_rate": round(contract_pass_rate, 3),
            "benchmark_score": round(benchmark_health, 3),
            "recommendation": self._get_health_recommendation(status, contract_results, benchmark_results)
        }
        
    def _get_health_recommendation(self, status: str, contract_results: Dict, benchmark_results: Dict) -> str:
        """Generate actionable recommendations based on test results."""
        if status == "excellent":
            return "System is performing well. Ready for production deployment."
        elif status == "good":
            return "System is stable with minor issues. Safe for demo and staging."
        elif status == "acceptable":
            return "System has some issues but core functionality works. Address failing tests before production."
        elif status == "concerning":
            return "System has significant issues. Fix contract failures and improve benchmark scores before deployment."
        else:
            return "System is unstable. Critical contract failures detected. Do not deploy."


async def main():
    parser = argparse.ArgumentParser(description="RepoBrain 10.0 Hybrid Test Suite")
    parser.add_argument("--contracts", action="store_true", help="Run deterministic contract tests only")
    parser.add_argument("--benchmark", action="store_true", help="Run universal benchmark only")
    parser.add_argument("--hybrid", action="store_true", help="Run both contract and benchmark tests")
    parser.add_argument("--smoke", action="store_true", help="Run fast smoke tests")
    parser.add_argument("--indexed-only", action="store_true", help="Use already indexed repos only")
    parser.add_argument("--repo-id", help="Target specific repo for contract tests")
    parser.add_argument("--config", help="Custom benchmark config path")
    parser.add_argument("--base-url", default="http://localhost:8000", help="RepoBrain API base URL")
    
    args = parser.parse_args()
    
    # Default to hybrid if no specific mode selected
    if not any([args.contracts, args.benchmark, args.hybrid, args.smoke]):
        args.hybrid = True
    
    runner = HybridTestRunner(args.base_url)
    
    try:
        if args.smoke:
            results = await runner.run_smoke()
        elif args.contracts:
            results = await runner.run_contracts_only(args.repo_id)
        elif args.benchmark:
            results = await runner.run_benchmark_only(args.config, args.indexed_only)
        elif args.hybrid:
            results = await runner.run_hybrid(args.repo_id, args.config, args.indexed_only)
            
        # Print summary
        if "overall_health" in results:
            health = results["overall_health"]
            print(f"\n🎯 Overall Health: {health['status'].upper()} (Score: {health['overall_score']})")
            print(f"💡 Recommendation: {health['recommendation']}")
            
        return 0 if results.get("overall_health", {}).get("status") in ["excellent", "good"] else 1
        
    except Exception as e:
        print(f"❌ Test suite failed: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)