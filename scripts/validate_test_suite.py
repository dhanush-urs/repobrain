#!/usr/bin/env python3
"""
RepoBrain 10.0 Test Suite Validation Script
==========================================

Validates the test suite itself - checks syntax, imports, and basic functionality
without requiring a live RepoBrain API.
"""

import sys
import ast
import importlib.util
from pathlib import Path
from typing import List, Dict, Any


def validate_python_syntax(file_path: Path) -> Dict[str, Any]:
    """Validate Python file syntax."""
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Parse AST to check syntax
        ast.parse(content)
        
        return {
            "file": str(file_path),
            "valid": True,
            "error": None
        }
    except SyntaxError as e:
        return {
            "file": str(file_path),
            "valid": False,
            "error": f"Syntax error: {e}"
        }
    except Exception as e:
        return {
            "file": str(file_path),
            "valid": False,
            "error": f"Error: {e}"
        }


def validate_imports(file_path: Path) -> Dict[str, Any]:
    """Validate that imports can be resolved."""
    try:
        spec = importlib.util.spec_from_file_location("test_module", file_path)
        if spec is None:
            return {
                "file": str(file_path),
                "valid": False,
                "error": "Could not create module spec"
            }
        
        # Try to load the module (this will fail if imports are broken)
        module = importlib.util.module_from_spec(spec)
        
        # Add parent directories to path for relative imports
        sys.path.insert(0, str(file_path.parent))
        sys.path.insert(0, str(file_path.parent.parent))
        
        try:
            spec.loader.exec_module(module)
            return {
                "file": str(file_path),
                "valid": True,
                "error": None
            }
        except ImportError as e:
            # Some imports might fail in validation environment - that's OK
            if "httpx" in str(e) or "pytest" in str(e):
                return {
                    "file": str(file_path),
                    "valid": True,
                    "error": f"Expected import error: {e}"
                }
            return {
                "file": str(file_path),
                "valid": False,
                "error": f"Import error: {e}"
            }
        finally:
            # Clean up path
            if str(file_path.parent) in sys.path:
                sys.path.remove(str(file_path.parent))
            if str(file_path.parent.parent) in sys.path:
                sys.path.remove(str(file_path.parent.parent))
                
    except Exception as e:
        return {
            "file": str(file_path),
            "valid": False,
            "error": f"Module loading error: {e}"
        }


def validate_json_config(file_path: Path) -> Dict[str, Any]:
    """Validate JSON configuration files."""
    try:
        import json
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        # Basic structure validation for benchmark config
        if file_path.name.endswith('benchmark.json'):
            if "repositories" not in data:
                return {
                    "file": str(file_path),
                    "valid": False,
                    "error": "Missing 'repositories' field"
                }
            
            for i, repo in enumerate(data["repositories"]):
                if "repo_url" not in repo:
                    return {
                        "file": str(file_path),
                        "valid": False,
                        "error": f"Repository {i} missing 'repo_url'"
                    }
        
        return {
            "file": str(file_path),
            "valid": True,
            "error": None
        }
    except json.JSONDecodeError as e:
        return {
            "file": str(file_path),
            "valid": False,
            "error": f"JSON syntax error: {e}"
        }
    except Exception as e:
        return {
            "file": str(file_path),
            "valid": False,
            "error": f"Error: {e}"
        }


def validate_test_structure() -> Dict[str, Any]:
    """Validate overall test suite structure."""
    issues = []
    
    # Check required directories
    required_dirs = [
        "tests",
        "tests/e2e", 
        "tests/benchmarks",
        "tests/shared",
        "tests/reports",
        "benchmarks",
        "benchmarks/reports",
        "scripts"
    ]
    
    for dir_path in required_dirs:
        if not Path(dir_path).exists():
            issues.append(f"Missing directory: {dir_path}")
    
    # Check required files
    required_files = [
        "scripts/test_repobrain_hybrid.py",
        "tests/e2e/test_repobrain_contracts.py",
        "tests/benchmarks/test_universal_benchmark.py",
        "tests/shared/test_client.py",
        "tests/shared/report_generator.py",
        "tests/shared/test_utilities.py",
        "benchmarks/universal_benchmark.json",
        "tests/requirements.txt"
    ]
    
    for file_path in required_files:
        if not Path(file_path).exists():
            issues.append(f"Missing file: {file_path}")
    
    return {
        "valid": len(issues) == 0,
        "issues": issues
    }


def main():
    """Main validation function."""
    print("🔍 Validating RepoBrain 10.0 Test Suite...")
    
    all_results = []
    
    # 1. Validate test suite structure
    print("\n📁 Checking test suite structure...")
    structure_result = validate_test_structure()
    if structure_result["valid"]:
        print("✅ Test suite structure is valid")
    else:
        print("❌ Test suite structure issues:")
        for issue in structure_result["issues"]:
            print(f"   - {issue}")
    
    # 2. Validate Python files
    print("\n🐍 Validating Python syntax...")
    python_files = [
        Path("scripts/test_repobrain_hybrid.py"),
        Path("tests/e2e/test_repobrain_contracts.py"),
        Path("tests/benchmarks/test_universal_benchmark.py"),
        Path("tests/shared/test_client.py"),
        Path("tests/shared/report_generator.py"),
        Path("tests/shared/test_utilities.py")
    ]
    
    syntax_valid = True
    for file_path in python_files:
        if file_path.exists():
            result = validate_python_syntax(file_path)
            all_results.append(result)
            
            if result["valid"]:
                print(f"✅ {file_path.name}")
            else:
                print(f"❌ {file_path.name}: {result['error']}")
                syntax_valid = False
        else:
            print(f"⚠️  {file_path.name}: File not found")
            syntax_valid = False
    
    # 3. Validate imports (only if syntax is valid)
    if syntax_valid:
        print("\n📦 Validating imports...")
        import_valid = True
        for file_path in python_files:
            if file_path.exists():
                result = validate_imports(file_path)
                
                if result["valid"]:
                    print(f"✅ {file_path.name}")
                else:
                    print(f"❌ {file_path.name}: {result['error']}")
                    import_valid = False
    else:
        print("\n⏭️  Skipping import validation due to syntax errors")
        import_valid = False
    
    # 4. Validate JSON configuration
    print("\n📄 Validating JSON configuration...")
    json_files = [
        Path("benchmarks/universal_benchmark.json")
    ]
    
    json_valid = True
    for file_path in json_files:
        if file_path.exists():
            result = validate_json_config(file_path)
            
            if result["valid"]:
                print(f"✅ {file_path.name}")
            else:
                print(f"❌ {file_path.name}: {result['error']}")
                json_valid = False
        else:
            print(f"⚠️  {file_path.name}: File not found")
            json_valid = False
    
    # 5. Summary
    print("\n📊 Validation Summary")
    print("=" * 50)
    
    overall_valid = (
        structure_result["valid"] and 
        syntax_valid and 
        import_valid and 
        json_valid
    )
    
    if overall_valid:
        print("🎉 RepoBrain 10.0 Test Suite validation PASSED")
        print("\n✅ All components are valid and ready to use")
        print("\n🚀 Next steps:")
        print("   1. Install dependencies: pip install -r tests/requirements.txt")
        print("   2. Start RepoBrain API server")
        print("   3. Run smoke test: python scripts/test_repobrain_hybrid.py --smoke")
        return 0
    else:
        print("❌ RepoBrain 10.0 Test Suite validation FAILED")
        print("\n🔧 Issues found:")
        
        if not structure_result["valid"]:
            print("   - Test suite structure issues")
        if not syntax_valid:
            print("   - Python syntax errors")
        if not import_valid:
            print("   - Import resolution errors")
        if not json_valid:
            print("   - JSON configuration errors")
            
        print("\n💡 Fix the issues above and re-run validation")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)