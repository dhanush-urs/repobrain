#!/bin/bash

# RepoBrain 10.0 Hybrid Test Suite Setup Script
# ==============================================

set -e

echo "🚀 Setting up RepoBrain 10.0 Hybrid Test Suite..."

# Check Python version
echo "🐍 Checking Python version..."
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "❌ Python not found. Please install Python 3.7+ and try again."
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1-2)
echo "✅ Found Python $PYTHON_VERSION"

# Check if we're in the right directory
if [ ! -f "scripts/test_repobrain_hybrid.py" ]; then
    echo "❌ Please run this script from the repository root directory"
    exit 1
fi

# Create virtual environment (optional but recommended)
echo "🔧 Setting up virtual environment..."
if [ ! -d ".venv" ]; then
    $PYTHON_CMD -m venv .venv
    echo "✅ Created virtual environment"
else
    echo "✅ Virtual environment already exists"
fi

# Activate virtual environment
echo "🔌 Activating virtual environment..."
source .venv/bin/activate

# Install dependencies
echo "📦 Installing test suite dependencies..."
pip install -r tests/requirements.txt

# Validate test suite
echo "🔍 Validating test suite..."
$PYTHON_CMD scripts/validate_test_suite.py

if [ $? -eq 0 ]; then
    echo ""
    echo "🎉 RepoBrain 10.0 Hybrid Test Suite setup complete!"
    echo ""
    echo "📋 Next steps:"
    echo "   1. Start your RepoBrain API server (default: http://localhost:8000)"
    echo "   2. Run smoke test: python scripts/test_repobrain_hybrid.py --smoke"
    echo "   3. Run full test suite: python scripts/test_repobrain_hybrid.py --hybrid"
    echo ""
    echo "📚 Documentation:"
    echo "   - Test suite overview: tests/README.md"
    echo "   - Implementation summary: REPOBRAIN_10_HYBRID_TEST_SUITE_SUMMARY.md"
    echo ""
    echo "🔧 Available commands:"
    echo "   python scripts/test_repobrain_hybrid.py --help"
    echo ""
else
    echo "❌ Test suite validation failed. Please check the errors above."
    exit 1
fi