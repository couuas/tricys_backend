#!/bin/bash
# Test runner script for Tricys Backend
# This script ensures the correct PYTHONPATH is set before running tests

cd "$(dirname "$0")/.."
export PYTHONPATH=/home/runner/work/tricys_backend:$PYTHONPATH

# Run pytest with all arguments passed to this script
pytest tricys_backend/tests/ "$@"
