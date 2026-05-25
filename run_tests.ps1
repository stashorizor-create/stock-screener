# Run the test suite (no database required)
# Usage: .\run_tests.ps1

.\.venv\Scripts\Activate.ps1
python -m pytest tests/ -v
