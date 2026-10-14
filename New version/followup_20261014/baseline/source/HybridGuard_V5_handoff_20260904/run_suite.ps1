param(
    [string]$PythonExe = "python",
    [string]$NodeExe = "node",
    [string]$OutputDir = "multi_suite"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$suiteDir = Join-Path $projectRoot $OutputDir
$names = @(
    "sparse_seed101", "sparse_seed202", "sparse_seed303",
    "systemic_seed404", "systemic_seed505", "systemic_seed606"
)

Push-Location $projectRoot
try {
    & $NodeExe "scripts/build_large_error_workbook.mjs" $suiteDir
    if ($LASTEXITCODE -ne 0) { throw "Workbook suite generation failed." }
    $env:PYTHONPATH = Join-Path $projectRoot "src"
    foreach ($name in $names) {
        & $PythonExe -m hybridguard.runner_hierarchical `
            (Join-Path $suiteDir "$name.xlsx") `
            (Join-Path $suiteDir "${name}_truth.json") `
            --output-dir (Join-Path $suiteDir "results_v5\$name")
        if ($LASTEXITCODE -ne 0) { throw "Experiment failed: $name" }
    }
    & $PythonExe -m hybridguard.summarize_suite $suiteDir
    if ($LASTEXITCODE -ne 0) { throw "Suite summary failed." }
    & $PythonExe -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw "Unit tests failed." }
}
finally {
    Pop-Location
}

Write-Host "Completed. Results: $(Join-Path $suiteDir 'results_v5')"
