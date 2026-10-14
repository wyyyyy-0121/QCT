param(
    [string]$PythonExe = "python",
    [string]$NodeExe = "node",
    [int]$CandidateLimit = 24,
    [switch]$RunFullFormulaGuard,
    [string]$OutputDir = "output"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$resolvedOutput = Join-Path $projectRoot $OutputDir
$workbookPath = Join-Path $resolvedOutput "sparse_seed101.xlsx"
$truthPath = Join-Path $resolvedOutput "sparse_seed101_truth.json"
$resultsPath = Join-Path $resolvedOutput "results"

New-Item -ItemType Directory -Force -Path $resolvedOutput | Out-Null
Push-Location $projectRoot
try {
    & $NodeExe "scripts/build_large_error_workbook.mjs" $resolvedOutput
    if ($LASTEXITCODE -ne 0) { throw "Workbook generation failed." }

    $env:PYTHONPATH = Join-Path $projectRoot "src"
    & $PythonExe -m hybridguard.runner_hierarchical $workbookPath $truthPath `
        --output-dir $resultsPath
    if ($LASTEXITCODE -ne 0) { throw "Model comparison failed." }

    if ($RunFullFormulaGuard) {
        $fullResultsPath = Join-Path $resolvedOutput "full-formulaguard-results"
        & $PythonExe -m hybridguard.runner $workbookPath $truthPath `
            --output-dir $fullResultsPath `
            --candidate-limit $CandidateLimit
        if ($LASTEXITCODE -ne 0) { throw "Full FormulaGuard comparison failed." }
    }

    & $PythonExe -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw "Unit tests failed." }
}
finally {
    Pop-Location
}

Write-Host "Completed. Results: $resultsPath"
