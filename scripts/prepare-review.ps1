# Run from the repository root in Windows PowerShell 5.1 or later.
param([switch]$SetModelConfiguration)
$ErrorActionPreference = 'Stop'
$env:OMP_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Create the root virtual environment first: py -3.13 -m venv .venv' }
& $python -c 'import sys; assert sys.version_info[:2] == (3,13), "FALCON requires Python 3.13"'
if ($LASTEXITCODE -ne 0) { throw 'Use the Python 3.13 virtual environment.' }
& $python -m pip install -e 'backend[dev,forecasting,ml,optimization]'
if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
if (-not (Test-Path '.\data\synthetic\review_2026_3\classification.jsonl')) {
    & $python '.\scripts\build_review_datasets.py' --materialize-missing
    if ($LASTEXITCODE -ne 0) { throw 'Dataset generation failed.' }
}
if (-not (Test-Path '.\ml\artifacts\classification\classification_2026_3_review.1\manifest.json')) {
    & $python '.\scripts\package_classification_model.py'
    if ($LASTEXITCODE -ne 0) { throw 'Classifier packaging failed.' }
}
& $python '.\scripts\check_classifier_integration.py'
if ($LASTEXITCODE -ne 0) { throw 'Classifier integration verification failed.' }
if ($SetModelConfiguration) {
    if (-not (Test-Path '.\.env')) { throw 'Your existing private root .env is required; this script does not generate authentication secrets.' }
    $envPath = Join-Path $repoRoot '.env'
    $content = [System.IO.File]::ReadAllText($envPath)
    $values = @{
        FALCON_CLASSIFICATION_ARTIFACT_ROOT = 'ml/artifacts/classification'
        FALCON_CLASSIFICATION_MODEL_VERSION = 'classification_2026_3_review.1'
    }
    foreach ($name in $values.Keys) {
        $line = "$name=$($values[$name])"
        $pattern = "(?m)^$name=.*$"
        if ([regex]::IsMatch($content, $pattern)) { $content = [regex]::Replace($content, $pattern, $line) }
        else { $content = $content.TrimEnd() + "`r`n$line`r`n" }
    }
    [System.IO.File]::WriteAllText($envPath, $content, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host 'Updated only the classifier root and version in your private .env.'
}
Write-Host 'Review datasets and classifier are ready. Start PostgreSQL, apply migrations, then start the API and frontend using docs/testing/FINAL_REVIEW.md.'
