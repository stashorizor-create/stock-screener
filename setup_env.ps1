# Run once to create the virtual environment and install dependencies
# Usage: .\setup_env.ps1

Write-Host "Creating virtual environment..."
python -m venv .venv

Write-Host "Activating virtual environment..."
.\.venv\Scripts\Activate.ps1

Write-Host "Upgrading pip..."
python -m pip install --upgrade pip

Write-Host "Installing dependencies..."
pip install -r requirements.txt

Write-Host ""
Write-Host "Setup complete."
Write-Host "To activate in future sessions: .\.venv\Scripts\Activate.ps1"
Write-Host "Copy .env.example to .env and fill in your credentials."
