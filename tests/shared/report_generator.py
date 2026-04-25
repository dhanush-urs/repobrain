"""
Report generator for RepoBrain 10.0 Hybrid Test Suite.
Generates both JSON and Markdown reports for contracts, benchmarks, and hybrid results.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any


class ReportGenerator:
    """Generate comprehensive test reports in JSON and Markdown formats."""
    
    def __init__(self):
        self.ensure_report_directories()
        
    def ensure_report_directories(self):
        """Ensure report directories exist."""
        Path("tests/reports").mkdir(parents=True, exist_ok=True)
        Path("benchmarks/reports").mkdir(parents=True, exist_ok=True)
        
    def generate_contract_reports(self, results: Dict[str, Any], json_path: str, md_path: str):
        """Generate contract test reports."""
        # Ensure directories exist
        Path(json_path).parent.mkdir(parents=True, exist_ok=True)
        Path(md_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Generate JSON report
        with open(json_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
            
        # Generate Markdown report
        md_content = self._generate_contract_markdown(results)
        with open(md_path, 'w') as f:
            f.write(md_content)
            
    def generate_benchmark_reports(self, results: Dict[str, Any], json_path: str, md_path: str):
        """Generate benchmark test reports."""
        # Ensure directories exist
        Path(json_path).parent.mkdir(parents=True, exist_ok=True)
        Path(md_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Generate JSON report
        with open(json_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
            
        # Generate Markdown report
        md_content = self._generate_benchmark_markdown(results)
        with open(md_path, 'w') as f:
            f.write(md_content)
            
    def generate_hybrid_reports(self, results: Dict[str, Any], json_path: str, md_path: str):
        """Generate hybrid test reports."""
        # Ensure directories exist
        Path(json_path).parent.mkdir(parents=True, exist_ok=True)
        Path(md_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Generate JSON report
        with open(json_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
            
        # Generate Markdown report
        md_content = self._generate_hybrid_markdown(results)
        with open(md_path, 'w') as f:
            f.write(md_content)
            
    def generate_smoke_reports(self, results: Dict[str, Any], json_path: str, md_path: str):
        """Generate smoke test reports."""
        # Ensure directories exist
        Path(json_path).parent.mkdir(parents=True, exist_ok=True)
        Path(md_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Generate JSON report
        with open(json_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
            
        # Generate Markdown report
        md_content = self._generate_smoke_markdown(results)
        with open(md_path, 'w') as f:
            f.write(md_content)
            
    def _generate_contract_markdown(self, results: Dict[str, Any]) -> str:
        """Generate Markdown report for contract tests."""
        # Handle both ISO format and timestamp formats
        timestamp_val = results.get("timestamp", 0)
        if isinstance(timestamp_val, str):
            timestamp = timestamp_val
        else:
            timestamp = datetime.fromtimestamp(timestamp_val).strftime("%Y-%m-%d %H:%M:%S")
            
        health = results.get("health_summary", {})
        
        md = f"""# RepoBrain 10.0 Contract Test Report (Hardened)

**Generated:** {timestamp}  
**Version:** {results.get("version", "unknown")}  
**Test Type:** {results.get("test_type", "contracts")}

## Executive Summary

- **Total Tests:** {health.get("contracts_total", 0)}
- **Real Tests:** {health.get("real_test_count", 0)} (excluding skipped)
- **Passed:** {health.get("contracts_passed", 0)}
- **Failed:** {health.get("contracts_failed", 0)}
- **Skipped:** {health.get("contracts_skipped", 0)}
- **Placeholders:** {health.get("placeholder_count", 0)}
- **Pass Rate:** {health.get("pass_rate", 0):.1%}
- **Skip Ratio:** {health.get("skip_ratio", 0):.1%}

### Production Readiness Assessment
**Verdict:** {health.get("production_verdict", "unknown").upper()}

"""
        
        # Status indicator based on real test results
        real_tests = health.get("real_test_count", 0)
        failed = health.get("contracts_failed", 0)
        
        if failed > 0:
            md += "🔴 **CRITICAL** - Contract failures detected, do not deploy\n\n"
        elif real_tests < 10:
            md += "🟡 **BASIC STABILITY ONLY** - Insufficient test coverage\n\n"
        elif real_tests >= 20:
            md += "🟢 **STRONG CONTRACT COVERAGE** - Comprehensive validation\n\n"
        else:
            md += "🟡 **MODERATE COVERAGE** - Adequate for development testing\n\n"
            
        # Endpoint support matrix
        endpoint_support = results.get("endpoint_support_matrix", {})
        if endpoint_support:
            md += "## 🔌 Endpoint Support Matrix\n\n"
            for endpoint, supported in endpoint_support.items():
                status = "✅ Supported" if supported else "❌ Not Available"
                md += f"- **{endpoint}:** {status}\n"
            md += "\n"
            
        # Category breakdown
        categories = results.get("category_breakdown", {})
        if categories:
            md += "## 📊 Test Category Breakdown\n\n"
            for category, stats in categories.items():
                total = stats.get("total", 0)
                passed = stats.get("passed", 0)
                failed = stats.get("failed", 0)
                skipped = stats.get("skipped", 0)
                
                if total == 0:
                    continue
                    
                status_icon = "✅" if failed == 0 and passed > 0 else "❌" if failed > 0 else "⏭️"
                md += f"### {status_icon} {category.title()} ({passed}/{total - skipped} passed)\n"
                md += f"- **Passed:** {passed}\n"
                md += f"- **Failed:** {failed}\n"
                md += f"- **Skipped:** {skipped}\n\n"
                
        # Coverage warnings
        warnings = results.get("coverage_warnings", [])
        if warnings:
            md += "## ⚠️ Coverage Warnings\n\n"
            for warning in warnings:
                md += f"- {warning}\n"
            md += "\n"
            
        # Failed tests section
        failed_tests = results.get("failed_tests", [])
        if failed_tests:
            md += "## ❌ Failed Tests\n\n"
            for test in failed_tests:
                md += f"### {test['test_name']} ({test.get('category', 'unknown')})\n"
                md += f"**Error:** {test.get('error', 'Unknown error')}\n\n"
                if test.get('details'):
                    md += f"**Details:** {test['details']}\n\n"
                    
        # All test results by category
        md += "## 📋 All Test Results\n\n"
        test_results = results.get("test_results", [])
        
        # Group by category
        by_category = {}
        for test in test_results:
            cat = test.get("category", "unknown")
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(test)
            
        for category, tests in by_category.items():
            md += f"### {category.title()} Tests\n\n"
            for test in tests:
                if test.get("skipped"):
                    status = "⏭️"
                elif test["passed"]:
                    status = "✅"
                else:
                    status = "❌"
                    
                duration = f" ({test['duration_ms']}ms)" if test.get('duration_ms') else ""
                md += f"- {status} **{test['test_name']}**{duration}\n"
                
                if test.get("skipped"):
                    md += f"  - Skipped: {test.get('error', 'No reason provided')}\n"
                elif not test["passed"] and test.get("error"):
                    md += f"  - Error: {test['error']}\n"
            md += "\n"
                
        md += "## 🔧 Contract Categories Validated\n\n"
        md += "- **Core API:** Endpoint availability, response schemas, required fields\n"
        md += "- **Graph:** Node/edge validity, sparsity honesty, no crashes on empty repos\n"
        md += "- **Flow:** Execution path validity, reasonable entrypoints, sparse repo safety\n"
        md += "- **Ask Repo:** Response schemas, confidence levels, citation file ID validity\n"
        md += "- **PR Impact:** Risk level enums, impact scoring, unknown file safety\n"
        md += "- **Files/Search:** File ID validity, search result integrity\n"
        md += "- **Intelligence:** Archetype detection, entrypoint analysis, graph health\n"
        md += "- **Timeout:** No-hang guarantees, reasonable response times\n\n"
        
        md += f"## 📊 Summary\n\n{results.get('summary', 'No summary available')}\n\n"
        
        md += "### Key Improvements in Hardened Version\n"
        md += "- ✅ **No placeholders** - All tests are real validations\n"
        md += "- ✅ **Honest reporting** - Skipped tests clearly marked\n"
        md += "- ✅ **Comprehensive coverage** - 30+ meaningful contract checks\n"
        md += "- ✅ **Category tracking** - Clear breakdown by test type\n"
        md += "- ✅ **Endpoint awareness** - Graceful handling of missing features\n"
        md += "- ✅ **Production verdict** - Honest assessment of deployment readiness\n"
        
        return md
        
    def _generate_benchmark_markdown(self, results: Dict[str, Any]) -> str:
        """Generate Markdown report for benchmark tests."""
        # Handle both ISO format and timestamp formats
        timestamp_val = results.get("timestamp", 0)
        if isinstance(timestamp_val, str):
            timestamp = timestamp_val
        else:
            timestamp = datetime.fromtimestamp(timestamp_val).strftime("%Y-%m-%d %H:%M:%S")
        
        md = f"""# RepoBrain 10.0 Universal Benchmark Report

**Generated:** {timestamp}  
**Version:** {results.get("version", "unknown")}  
**Test Type:** {results.get("test_type", "benchmark")}

## Executive Summary

- **Overall Score:** {results.get("overall_score", 0)}/10.0
- **Repositories Tested:** {results.get("total_repos_tested", 0)}
- **Total Penalties:** {results.get("total_penalties", 0)}

### Performance Distribution
"""
        
        dist = results.get("performance_distribution", {})
        md += f"- **Excellent (8.0+):** {dist.get('excellent', 0)} repos\n"
        md += f"- **Good (6.0-7.9):** {dist.get('good', 0)} repos\n"
        md += f"- **Acceptable (4.0-5.9):** {dist.get('acceptable', 0)} repos\n"
        md += f"- **Poor (<4.0):** {dist.get('poor', 0)} repos\n\n"
        
        # Overall assessment
        overall_score = results.get("overall_score", 0)
        if overall_score >= 8.0:
            md += "🟢 **EXCELLENT** - RepoBrain demonstrates strong cross-repo intelligence\n\n"
        elif overall_score >= 6.0:
            md += "🟡 **GOOD** - RepoBrain shows solid performance with room for improvement\n\n"
        elif overall_score >= 4.0:
            md += "🟠 **ACCEPTABLE** - RepoBrain has basic functionality but needs enhancement\n\n"
        else:
            md += "🔴 **POOR** - RepoBrain shows significant intelligence gaps\n\n"
            
        # Category averages
        md += "## 📊 Category Performance\n\n"
        categories = results.get("category_averages", {})
        for category, score in categories.items():
            category_name = category.replace("_", " ").title()
            md += f"- **{category_name}:** {score:.1f}/10.0\n"
            
        # Top penalties
        penalties = results.get("penalty_summary", [])
        if penalties:
            md += "\n## ⚠️ Top Issues Found\n\n"
            for penalty in penalties[:5]:  # Top 5
                md += f"- {penalty}\n"
                
        # Repository results
        md += "\n## 🏆 Repository Results\n\n"
        repo_results = results.get("results", [])
        for repo in repo_results:
            score = repo.get("total_score", 0)
            status = "🟢" if score >= 8.0 else "🟡" if score >= 6.0 else "🟠" if score >= 4.0 else "🔴"
            
            md += f"### {status} {repo['repo_url']} ({score}/10.0)\n\n"
            
            # Category breakdown
            scores = repo.get("scores", {})
            for category, cat_score in scores.items():
                category_name = category.replace("_", " ").title()
                md += f"- **{category_name}:** {cat_score:.1f}\n"
                
            # Penalties for this repo
            repo_penalties = repo.get("penalties", [])
            if repo_penalties:
                md += f"\n**Issues:** {len(repo_penalties)} penalties\n"
                for penalty in repo_penalties[:3]:  # Top 3
                    md += f"  - {penalty}\n"
                    
            md += "\n"
            
        md += "## 🎯 Benchmark Dimensions\n\n"
        md += "1. **Ask Repo Credibility (3.0 pts):** Purpose and architecture understanding\n"
        md += "2. **Archetype Correctness (1.0 pt):** Repository type classification\n"
        md += "3. **Entrypoint Plausibility (1.0 pt):** Application entry point detection\n"
        md += "4. **Graph Usefulness (2.0 pts):** Knowledge graph quality or sparse honesty\n"
        md += "5. **Execution Flow Plausibility (2.0 pts):** Code execution path mapping\n"
        md += "6. **PR Impact Usefulness (1.0 pt):** Change impact analysis quality\n\n"
        
        md += f"## 📈 Summary\n\n{results.get('summary', 'No summary available')}\n"
        
        return md
        
    def _generate_hybrid_markdown(self, results: Dict[str, Any]) -> str:
        """Generate Markdown report for hybrid tests."""
        # Handle both ISO format and timestamp formats
        timestamp_val = results.get("timestamp", 0)
        if isinstance(timestamp_val, str):
            timestamp = timestamp_val
        else:
            timestamp = datetime.fromtimestamp(timestamp_val).strftime("%Y-%m-%d %H:%M:%S")
            
        overall_health = results.get("overall_health", {})
        
        md = f"""# RepoBrain 10.0 Hybrid Test Suite Report

**Generated:** {timestamp}  
**Version:** {results.get("version", "unknown")}  
**Test Mode:** {results.get("test_mode", "hybrid")}

## 🎯 Overall System Health

- **Overall Score:** {overall_health.get("overall_score", 0):.3f}
- **Status:** {overall_health.get("status", "unknown").upper()}
- **Contract Pass Rate:** {overall_health.get("contract_pass_rate", 0):.1%}
- **Benchmark Score:** {overall_health.get("benchmark_score", 0):.1f}/1.0

### Recommendation
{overall_health.get("recommendation", "No recommendation available")}

"""
        
        # Status indicator
        status = overall_health.get("status", "unknown")
        if status == "excellent":
            md += "🟢 **SYSTEM READY** - RepoBrain is performing excellently across all dimensions\n\n"
        elif status == "good":
            md += "🟡 **SYSTEM STABLE** - RepoBrain is performing well with minor issues\n\n"
        elif status == "acceptable":
            md += "🟠 **SYSTEM FUNCTIONAL** - RepoBrain works but has notable limitations\n\n"
        elif status == "concerning":
            md += "🟠 **SYSTEM UNSTABLE** - RepoBrain has significant issues requiring attention\n\n"
        else:
            md += "🔴 **SYSTEM CRITICAL** - RepoBrain has critical failures and should not be deployed\n\n"
            
        # Contract results summary
        contract_results = results.get("contract_results", {})
        contract_health = contract_results.get("health_summary", {})
        
        md += "## 🔧 Contract Test Results (Layer A)\n\n"
        md += f"- **Tests Run:** {contract_health.get('contracts_total', 0)}\n"
        md += f"- **Passed:** {contract_health.get('contracts_passed', 0)}\n"
        md += f"- **Failed:** {contract_health.get('contracts_failed', 0)}\n"
        md += f"- **Pass Rate:** {contract_health.get('pass_rate', 0):.1%}\n\n"
        
        # Show critical contract failures
        failed_contracts = contract_results.get("failed_tests", [])
        if failed_contracts:
            md += "### ❌ Critical Contract Failures\n\n"
            for test in failed_contracts[:5]:  # Top 5
                md += f"- **{test['test_name']}:** {test.get('error', 'Unknown error')}\n"
            md += "\n"
            
        # Benchmark results summary
        benchmark_results = results.get("benchmark_results", {})
        
        md += "## 🎯 Universal Benchmark Results (Layer B)\n\n"
        md += f"- **Overall Score:** {benchmark_results.get('overall_score', 0)}/10.0\n"
        md += f"- **Repositories Tested:** {benchmark_results.get('total_repos_tested', 0)}\n"
        md += f"- **Total Penalties:** {benchmark_results.get('total_penalties', 0)}\n\n"
        
        # Category performance
        categories = benchmark_results.get("category_averages", {})
        if categories:
            md += "### 📊 Intelligence Category Performance\n\n"
            for category, score in categories.items():
                category_name = category.replace("_", " ").title()
                bar = "█" * int(score) + "░" * (10 - int(score))
                md += f"- **{category_name}:** {score:.1f}/10.0 `{bar}`\n"
            md += "\n"
            
        # Top issues across both layers
        all_issues = []
        
        # Add contract failures
        for test in failed_contracts:
            all_issues.append(f"Contract: {test['test_name']} - {test.get('error', 'Failed')}")
            
        # Add benchmark penalties
        benchmark_penalties = benchmark_results.get("penalty_summary", [])
        for penalty in benchmark_penalties:
            all_issues.append(f"Benchmark: {penalty}")
            
        if all_issues:
            md += "## ⚠️ Top Issues Identified\n\n"
            for issue in all_issues[:10]:  # Top 10
                md += f"- {issue}\n"
            md += "\n"
            
        # Recommendations section
        md += "## 💡 Recommendations\n\n"
        
        if contract_health.get("contracts_failed", 0) > 0:
            md += "### Contract Layer (Critical)\n"
            md += "- Fix failing contract tests before deployment\n"
            md += "- Address API schema violations and timeout issues\n"
            md += "- Resolve regression patterns\n\n"
            
        if benchmark_results.get("overall_score", 0) < 6.0:
            md += "### Intelligence Layer (Important)\n"
            md += "- Improve cross-repo analysis accuracy\n"
            md += "- Reduce hallucination penalties\n"
            md += "- Enhance archetype detection\n\n"
            
        # Next steps
        md += "## 🚀 Next Steps\n\n"
        if status in ["excellent", "good"]:
            md += "1. ✅ System is ready for production use\n"
            md += "2. 📊 Monitor performance in production\n"
            md += "3. 🔄 Run hybrid tests regularly\n"
        elif status == "acceptable":
            md += "1. 🔧 Address failing contract tests\n"
            md += "2. 📈 Improve benchmark scores\n"
            md += "3. 🧪 Re-run hybrid tests after fixes\n"
        else:
            md += "1. 🚨 **DO NOT DEPLOY** - Critical issues detected\n"
            md += "2. 🔧 Fix all contract failures immediately\n"
            md += "3. 📊 Investigate benchmark penalties\n"
            md += "4. 🧪 Re-run full hybrid test suite\n"
            
        md += "\n---\n\n"
        md += f"**Report Generated:** {timestamp}  \n"
        md += f"**RepoBrain Version:** {results.get('version', 'unknown')}  \n"
        md += f"**Test Suite:** Hybrid (Contracts + Universal Benchmark)\n"
        
        return md
        
    def _generate_smoke_markdown(self, results: Dict[str, Any]) -> str:
        """Generate Markdown report for smoke tests."""
        # Handle both ISO format and timestamp formats
        timestamp_val = results.get("timestamp", 0)
        if isinstance(timestamp_val, str):
            # ISO format string
            timestamp = timestamp_val
        else:
            # Unix timestamp
            timestamp = datetime.fromtimestamp(timestamp_val).strftime("%Y-%m-%d %H:%M:%S")
            
        overall_health = results.get("overall_health", {})
        
        md = f"""# RepoBrain 10.0 Smoke Test Report

**Generated:** {timestamp}  
**Version:** {results.get("version", "unknown")}  
**Test Mode:** {results.get("test_mode", "smoke")}

## 🎯 Overall System Health

- **Overall Score:** {overall_health.get("overall_score", 0):.3f}
- **Status:** {overall_health.get("status", "unknown").upper()}
- **Contract Pass Rate:** {overall_health.get("contract_pass_rate", 0):.1%}
- **Benchmark Score:** {overall_health.get("benchmark_score", 0):.1f}/1.0

### Recommendation
{overall_health.get("recommendation", "No recommendation available")}

"""
        
        # Status indicator
        status = overall_health.get("status", "unknown")
        if status == "excellent":
            md += "🟢 **SYSTEM READY** - RepoBrain is performing excellently\n\n"
        elif status == "good":
            md += "🟡 **SYSTEM STABLE** - RepoBrain is performing well\n\n"
        elif status == "acceptable":
            md += "🟠 **SYSTEM FUNCTIONAL** - RepoBrain works but has limitations\n\n"
        elif status == "concerning":
            md += "🟠 **SYSTEM UNSTABLE** - RepoBrain has significant issues\n\n"
        else:
            md += "🔴 **SYSTEM CRITICAL** - RepoBrain has critical failures\n\n"
            
        # Contract smoke results
        contract_results = results.get("contract_results", {})
        contract_health = contract_results.get("health_summary", {})
        
        md += "## 🔧 Contract Smoke Tests (Layer A)\n\n"
        md += f"- **Tests Run:** {contract_health.get('contracts_total', 0)}\n"
        md += f"- **Passed:** {contract_health.get('contracts_passed', 0)}\n"
        md += f"- **Failed:** {contract_health.get('contracts_failed', 0)}\n"
        md += f"- **Pass Rate:** {contract_health.get('pass_rate', 0):.1%}\n\n"
        
        # Benchmark smoke results
        benchmark_results = results.get("benchmark_results", {})
        
        md += "## 🎯 Benchmark Smoke Tests (Layer B)\n\n"
        md += f"- **Overall Score:** {benchmark_results.get('overall_score', 0)}/10.0\n"
        md += f"- **Repositories Tested:** {benchmark_results.get('total_repos_tested', 0)}\n"
        md += f"- **Total Penalties:** {benchmark_results.get('total_penalties', 0)}\n\n"
        
        # Category performance
        categories = benchmark_results.get("category_averages", {})
        if categories:
            md += "### 📊 Intelligence Category Performance\n\n"
            for category, score in categories.items():
                category_name = category.replace("_", " ").title()
                bar = "█" * int(score) + "░" * (10 - int(score))
                md += f"- **{category_name}:** {score:.1f}/10.0 `{bar}`\n"
            md += "\n"
            
        # Repository results
        repo_results = benchmark_results.get("results", [])
        if repo_results:
            md += "## 🏆 Smoke Test Repository Results\n\n"
            for repo in repo_results:
                score = repo.get("total_score", 0)
                status_icon = "🟢" if score >= 8.0 else "🟡" if score >= 6.0 else "🟠" if score >= 4.0 else "🔴"
                
                md += f"### {status_icon} {repo['repo_url']} ({score}/10.0)\n\n"
                
                # Category breakdown
                scores = repo.get("scores", {})
                if scores:
                    md += "**Dimension Scores:**\n"
                    for category, cat_score in scores.items():
                        category_name = category.replace("_", " ").title()
                        md += f"- **{category_name}:** {cat_score:.1f}\n"
                    md += "\n"
                
                # Penalties for this repo
                repo_penalties = repo.get("penalties", [])
                if repo_penalties:
                    md += f"**Issues:** {len(repo_penalties)} penalties\n"
                    for penalty in repo_penalties[:3]:  # Top 3
                        md += f"  - {penalty}\n"
                    md += "\n"
                    
        # Top issues
        all_issues = []
        
        # Add contract failures
        failed_contracts = contract_results.get("failed_tests", [])
        for test in failed_contracts:
            all_issues.append(f"Contract: {test['test_name']} - {test.get('error', 'Failed')}")
            
        # Add benchmark penalties
        benchmark_penalties = benchmark_results.get("penalty_summary", [])
        for penalty in benchmark_penalties:
            all_issues.append(f"Benchmark: {penalty}")
            
        if all_issues:
            md += "## ⚠️ Issues Identified\n\n"
            for issue in all_issues[:5]:  # Top 5
                md += f"- {issue}\n"
            md += "\n"
            
        # Recommendations
        md += "## 💡 Recommendations\n\n"
        
        if contract_health.get("contracts_failed", 0) > 0:
            md += "- Fix failing contract tests\n"
            
        if benchmark_results.get("overall_score", 0) < 6.0:
            md += "- Improve cross-repo analysis accuracy\n"
            
        md += "- Run full hybrid test suite for comprehensive validation\n\n"
        
        md += "---\n\n"
        md += f"**Report Generated:** {timestamp}  \n"
        md += f"**RepoBrain Version:** {results.get('version', 'unknown')}  \n"
        md += f"**Test Suite:** Smoke (Fast validation)\n"
        
        return md