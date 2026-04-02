# slopcheck installer for Windows
# Run: irm https://raw.githubusercontent.com/0xToxSec/slopcheck/main/install.ps1 | iex

Write-Host ""
Write-Host "  +-----------------------------------+" -ForegroundColor Green
Write-Host "  |  slopcheck installer              |" -ForegroundColor Green
Write-Host "  |  Stop AI-hallucinated packages    |" -ForegroundColor Green
Write-Host "  +-----------------------------------+" -ForegroundColor Green
Write-Host ""

# Check for Python
$python = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $python = "python"
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $python = "python3"
} else {
    Write-Host "  [!] Python not found. Install Python 3.9+ first." -ForegroundColor Red
    Write-Host "      https://python.org/downloads"
    exit 1
}

$ver = & $python --version
Write-Host "  [*] Found Python: $ver"

# Install slopcheck
Write-Host "  [*] Installing slopcheck from PyPI..."
& $python -m pip install --upgrade slopcheck --quiet

# Verify
if (Get-Command slopcheck -ErrorAction SilentlyContinue) {
    Write-Host "  [+] slopcheck installed successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Usage:"
    Write-Host "    slopcheck .                              Scan current directory"
    Write-Host "    slopcheck requirements.txt               Scan a specific file"
    Write-Host "    slopcheck flask-gpt-helper --pkg pypi    Check one package"
    Write-Host ""
} elseif (& $python -m slopcheck --help 2>$null) {
    Write-Host "  [+] slopcheck installed! (not on PATH, use: python -m slopcheck)" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Usage:"
    Write-Host "    python -m slopcheck .                              Scan current directory"
    Write-Host "    python -m slopcheck requirements.txt               Scan a specific file"
    Write-Host "    python -m slopcheck flask-gpt-helper --pkg pypi    Check one package"
    Write-Host ""
} else {
    Write-Host "  [!] Something went wrong. Try: pip install slopcheck" -ForegroundColor Red
    exit 1
}
