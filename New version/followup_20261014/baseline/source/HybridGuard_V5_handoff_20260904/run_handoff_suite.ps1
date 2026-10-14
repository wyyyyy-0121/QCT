param(
    [string]$PythonExe = "python",
    [string]$InputDir = "workbooks",
    [string]$OutputDir = "rerun_results"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$inputRoot = Join-Path $projectRoot $InputDir
$outputRoot = Join-Path $projectRoot $OutputDir
$names = @(
    "sparse_seed101", "sparse_seed202", "sparse_seed303",
    "systemic_seed404", "systemic_seed505", "systemic_seed606"
)

Push-Location $projectRoot
try {
    $env:PYTHONPATH = Join-Path $projectRoot "src"
    foreach ($name in $names) {
        $workbook = Join-Path $inputRoot "$name.xlsx"
        $truth = Join-Path $inputRoot "${name}_truth.json"
        if (-not (Test-Path -LiteralPath $workbook)) { throw "Missing workbook: $workbook" }
        if (-not (Test-Path -LiteralPath $truth)) { throw "Missing truth file: $truth" }
        & $PythonExe -m hybridguard.runner_hierarchical $workbook $truth `
            --output-dir (Join-Path $outputRoot $name)
        if ($LASTEXITCODE -ne 0) { throw "Experiment failed: $name" }
    }
    & $PythonExe -m hybridguard.summarize_suite $inputRoot --results-dir $outputRoot
    if ($LASTEXITCODE -ne 0) { throw "Suite summary failed." }
    & $PythonExe -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw "Unit tests failed." }
}
finally {
    Pop-Location
}

Write-Host "Completed. Results: $outputRoot"
