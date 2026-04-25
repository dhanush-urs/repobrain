# RepoBrain 10.0 Hybrid Test Suite

A comprehensive validation system that combines deterministic E2E contract tests with universal cross-repo intelligence benchmarks.

## Overview

The RepoBrain 10.0 Hybrid Test Suite validates both:

### Layer A: Deterministic E2E Contract + Regression Tests
- **API Contract Tests:** Endpoint availability, response schemas, required fields
- **Timeout Tests:** No-hang guarantees, reasonable response times  
- **Graph Invariant Tests:** Valid node/edge IDs, sparsity honesty, no crashes
- **Execution Flow Tests:** Valid execution paths, reasonable entrypoints
- **Ask Repo Contract Tests:** Response schemas, confidence levels, citation validity
- **PR Impact Contract Tests:** Risk level enums, impact scoring, file ID validity
- **Regression Fixtures:** Known historical bugs and failure patterns

### Layer B: Universal Cross-Repo Intelligence Benchmark
- **Ask Repo Credibility (3.0 pts):** Purpose and architecture understanding
- **Archetype Correctness (1.0 pt):** Repository type classification  
- **Entrypoint Plausibility (1.0 pt):** Application entry point detection
- **Graph Usefulness (2.0 pts):** Knowledge graph quality or sparse honesty
- **Execution Flow Plausibility (2.0 pts):** Code execution path mapping
- **PR Impact Usefulness (1.0 pt):** Change impact analysis quality

## Quick Start

### Prerequisites

```bash
# Install dependencies
pip install -r tests/requirements.txt

# Ensure RepoBrain API is running
# Default: http://localhost:8000
```

### Run Tests

```bash
# Run all tests (hybrid mode)
python scripts/test_repobrain_hybrid.py

# Run only contract tests
python scripts/test_repobrain_hybrid.py --contracts

# Run only benchmark tests  
python scripts/test_repobrain_hybrid.py --benchmark

# Run fast smoke tests
python scripts/test_repobrain_hybrid.py --smoke

# Use existing repos only (no new imports)
python scripts/test_repobrain_hybrid.py --indexed-only

# Target specific repo for contracts
python scripts/test_repobrain_hybrid.py --contracts --repo-id <repo_id>

# Use custom benchmark config
python scripts/test_repobrain_hybrid.py --benchmark --config benchmarks/custom_config.json

# Use different API URL
python scripts/test_repobrain_hybrid.py --base-url http://staging.repobrain.com
```

## Test Modes

### Hybrid Mode (Default)
Runs both contract tests and universal benchmark. Provides comprehensive validation of system stability and intelligence quality.

**Use when:** Full validation before releases, demos, or production deployment.

### Contracts Only
Runs deterministic E2E tests that validate API stability, schemas, and regression patterns.

**Use when:** Quick validation during development, CI/CD pipelines, or debugging API issues.

### Benchmark Only  
Runs universal cross-repo intelligence tests on multiple repository archetypes.

**Use when:** Evaluating AI/ML model performance, testing cross-repo adaptability, or measuring intelligence quality.

### Smoke Mode
Runs fast subset of tests for quick validation.

**Use when:** Rapid iteration, pre-commit hooks, or initial sanity checks.

## Configuration

### Default Benchmark Repositories

The suite tests against 10 diverse repositories by default:

1. **fastapi/full-stack-fastapi-template** - Full-stack web application
2. **vitejs/vite** - Frontend build tool  
3. **dhanush-urs/airline_reservation** - Java desktop GUI
4. **fastapi/typer** - CLI tool library
5. **psf/requests** - Python HTTP library
6. **scikit-learn/scikit-learn** - Machine learning library
7. **h5bp/html5-boilerplate** - Frontend template
8. **vercel/turborepo** - Monorepo build tool
9. **docker/awesome-compose** - Infrastructure examples
10. **microsoft/vscode** - Large Electron application

### Custom Configuration

Create a custom benchmark configuration:

```json
{
  "repositories": [
    {
      "repo_url": "https://github.com/your-org/your-repo",
      "expected_archetypes": ["backend_api", "microservice"],
      "expected_not_archetypes": ["cli_tool", "static_site"],
      "expected_entry_hints": ["main", "app", "server"],
      "notes": "Your custom repository description",
      "allow_weak_evidence": false
    }
  ]
}
```

## Reports

The test suite generates comprehensive reports in both JSON and Markdown formats:

### Contract Reports
- `tests/reports/contracts_YYYYMMDD_HHMMSS.json`
- `tests/reports/contracts_YYYYMMDD_HHMMSS.md`

### Benchmark Reports  
- `benchmarks/reports/universal_benchmark_YYYYMMDD_HHMMSS.json`
- `benchmarks/reports/universal_benchmark_YYYYMMDD_HHMMSS.md`

### Hybrid Reports
- `tests/reports/hybrid_YYYYMMDD_HHMMSS.json`
- `tests/reports/hybrid_YYYYMMDD_HHMMSS.md`

## Scoring System

### Contract Tests
- **Pass/Fail:** Binary scoring for deterministic tests
- **Health Score:** Overall system stability percentage
- **Categories:** API, Timeout, Graph, Flow, Ask Repo, PR Impact, Regressions

### Benchmark Tests  
- **0-10 Scale:** Each repository scored out of 10 points
- **Category Breakdown:** Individual scores per intelligence dimension
- **Penalties:** Deductions for hallucinations and obvious errors
- **Overall Average:** Mean score across all tested repositories

### Hybrid Health
- **Overall Score:** Weighted combination of contract pass rate (60%) and benchmark score (40%)
- **Status Levels:** Excellent (90%+), Good (75%+), Acceptable (60%+), Concerning (40%+), Critical (<40%)
- **Recommendations:** Actionable next steps based on results

## Architecture

```
tests/
├── e2e/                          # Contract tests (Layer A)
│   └── test_repobrain_contracts.py
├── benchmarks/                   # Benchmark tests (Layer B)  
│   └── test_universal_benchmark.py
├── shared/                       # Common utilities
│   ├── test_client.py           # API client with retries/timeouts
│   ├── test_utilities.py        # Validation and scoring utils
│   └── report_generator.py      # JSON/Markdown report generation
└── reports/                      # Generated test reports

benchmarks/
├── universal_benchmark.json      # Default 10-repo configuration
└── reports/                      # Benchmark-specific reports

scripts/
└── test_repobrain_hybrid.py     # Main CLI entry point
```

## Best Practices

### For Development
1. Run `--smoke` tests frequently during development
2. Use `--contracts` for API stability validation  
3. Run full `--hybrid` before major releases

### For CI/CD
1. Include contract tests in pull request validation
2. Run benchmark tests on staging environments
3. Require hybrid test passage for production deployment

### For Debugging
1. Use `--repo-id` to focus on specific repositories
2. Check JSON reports for detailed error information
3. Review Markdown reports for human-readable summaries

## Extending the Suite

### Adding New Contract Tests
1. Add test methods to `ContractTestSuite` class
2. Follow naming convention: `_test_<category>_<specific_test>`
3. Return `ContractTestResult` objects with clear error messages

### Adding New Benchmark Dimensions
1. Add scoring method to `UniversalBenchmarkSuite` class
2. Update scoring model in benchmark configuration
3. Ensure graceful degradation for unsupported endpoints

### Custom Repository Sets
1. Create custom JSON configuration file
2. Include diverse repository archetypes  
3. Set realistic expectations and allow weak evidence where appropriate

## Troubleshooting

### Common Issues

**"Repository not available"**
- Ensure repositories are publicly accessible
- Use `--indexed-only` to skip repo creation
- Check network connectivity and GitHub API limits

**"Timeout errors"**  
- Increase timeout values in test client
- Check RepoBrain API performance
- Verify database and indexing status

**"Low benchmark scores"**
- Review penalty details in reports
- Check for hallucination indicators
- Validate archetype expectations are realistic

**"Contract test failures"**
- Check API endpoint availability
- Verify response schema compatibility  
- Review regression test assumptions

### Getting Help

1. Check the generated Markdown reports for detailed explanations
2. Review JSON reports for programmatic analysis
3. Run tests with `--smoke` first to isolate issues
4. Verify RepoBrain API health independently

## Contributing

When adding new tests or modifying existing ones:

1. **Maintain backward compatibility** with existing API contracts
2. **Add graceful degradation** for optional or new endpoints  
3. **Include clear error messages** that help diagnose issues
4. **Update documentation** and configuration examples
5. **Test against diverse repositories** to avoid overfitting

The goal is a robust, reusable test suite that validates both system stability and intelligence quality across diverse repository types.