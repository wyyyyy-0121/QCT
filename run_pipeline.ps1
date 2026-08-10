param(
    [ValidateSet("smoke", "quick", "full")]
    [string]$Mode = "quick",
    [switch]$Ablations,
    [switch]$WithSensitivity,
    [switch]$WithPerformance,
    [switch]$WithLibreOffice,
    [int]$CandidateLimit = 15,
    [int]$BootstrapSamples = 1000
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$RuntimeRoot = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies"
$BundledPython = Join-Path $RuntimeRoot "python\python.exe"
$BundledNode = Join-Path $RuntimeRoot "node\bin\node.exe"
$BundledGit = Join-Path $RuntimeRoot "native\git\cmd\git.exe"
$BundledModules = Join-Path $RuntimeRoot "node\node_modules"

function Resolve-Executable([string]$Bundled, [string[]]$Names) {
    if (Test-Path -LiteralPath $Bundled) { return $Bundled }
    foreach ($Name in $Names) {
        $Command = Get-Command $Name -ErrorAction SilentlyContinue
        if ($Command) { return $Command.Source }
    }
    throw "Required executable not found: $($Names -join ', ')"
}

function Invoke-Checked([string]$Executable, [string[]]$Arguments) {
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Executable @Arguments
        $ExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($ExitCode -ne 0) {
        throw "Command failed with exit code ${ExitCode}: $Executable $($Arguments -join ' ')"
    }
}

$script:TranscriptActive = $false
trap {
    $FailureMessage = $_.Exception.Message
    if ($script:TranscriptActive) {
        Stop-Transcript | Out-Null
        $script:TranscriptActive = $false
    }
    Write-Host "FormulaGuard pipeline failed: $FailureMessage" -ForegroundColor Red
    exit 1
}

$Python = Resolve-Executable $BundledPython @("python", "py")
$Node = Resolve-Executable $BundledNode @("node")
$Git = Resolve-Executable $BundledGit @("git")

if (-not (Test-Path -LiteralPath "node_modules\@oai\artifact-tool")) {
    if (-not (Test-Path -LiteralPath $BundledModules)) {
        throw "@oai/artifact-tool is unavailable. Open this project in Codex Desktop once, or install the required Node package."
    }
    if (Test-Path -LiteralPath "node_modules") {
        throw "node_modules exists but does not contain @oai/artifact-tool. Move that folder aside before rerunning."
    }
    New-Item -ItemType Junction -Path "node_modules" -Target $BundledModules | Out-Null
}

$Benchmark = Join-Path $ProjectRoot "data\propagationbench_$Mode"
$Validation = Join-Path $Benchmark "validation"
$Results = Join-Path $ProjectRoot "results\$Mode"
$WorkbookOutput = Join-Path $ProjectRoot "outputs\FormulaGuard_${Mode}_experiment_results.xlsx"
$FrozenConfig = Join-Path $ProjectRoot "results\quick\frozen_config.json"
if ($Mode -eq "full" -and -not (Test-Path -LiteralPath $FrozenConfig)) {
    throw "Full mode requires results\quick\frozen_config.json. Quick must pass the freeze assessment first."
}
New-Item -ItemType Directory -Force -Path $Results | Out-Null
Start-Transcript -Path (Join-Path $Results "pipeline.log") -Force | Out-Null
$script:TranscriptActive = $true

Write-Host "[1/11] Generating $Mode benchmark..."
Invoke-Checked -Executable $Node -Arguments @("scripts\build_benchmarks.mjs", "--mode", $Mode, "--output", $Benchmark)

Write-Host "[2/11] Validating silent-error labels and propagation depth..."
Invoke-Checked -Executable $Python -Arguments @("scripts\validate_benchmark.py", "--benchmark", $Benchmark, "--output", $Validation)

Write-Host "[3/11] Recording environment and source hashes..."
Invoke-Checked -Executable $Python -Arguments @("scripts\record_environment.py", "--root", $ProjectRoot, "--output", (Join-Path $Results "environment.json"), "--node", $Node, "--git", $Git)
if ($Mode -eq "full") {
    Invoke-Checked -Executable $Python -Arguments @(
        "scripts\verify_frozen_config.py",
        "--config", $FrozenConfig,
        "--environment", (Join-Path $Results "environment.json"),
        "--root", $ProjectRoot,
        "--git", $Git
    )
}

Write-Host "[4/11] Running localization comparisons..."
$ExperimentArgs = @(
    "scripts\run_experiments.py",
    "--benchmark", $Benchmark,
    "--validation", (Join-Path $Validation "validated_instances.jsonl"),
    "--output", $Results,
    "--candidate-limit", $CandidateLimit,
    "--bootstrap-samples", $BootstrapSamples
)
if ($Ablations) { $ExperimentArgs += "--ablations" }
if ($Mode -eq "full") { $ExperimentArgs += @("--config", $FrozenConfig) }
Invoke-Checked -Executable $Python -Arguments $ExperimentArgs

Write-Host "[5/11] Estimating alarms on clean synthetic workbooks..."
$CalibrationResults = $Results
if ($Mode -eq "full") {
    $QuickCalibration = Join-Path $ProjectRoot "results\quick\raw_results.csv"
    if (-not (Test-Path -LiteralPath $QuickCalibration)) {
        throw "Full mode requires frozen quick calibration results. Run: run_pipeline.cmd quick -Ablations -WithSensitivity"
    }
    $CalibrationResults = Join-Path $ProjectRoot "results\quick"
    Invoke-Checked -Executable $Python -Arguments @("scripts\verify_calibration.py", "--calibration", (Join-Path $CalibrationResults "environment.json"), "--current", (Join-Path $Results "environment.json"))
}
$CleanArgs = @("scripts\run_clean_evaluation.py", "--benchmark", $Benchmark, "--mutant-results", $CalibrationResults, "--output", $Results, "--candidate-limit", "$CandidateLimit")
if ($Mode -eq "full") { $CleanArgs += @("--config", $FrozenConfig) }
Invoke-Checked -Executable $Python -Arguments $CleanArgs

Write-Host "[6/11] Exporting failure cases..."
Invoke-Checked -Executable $Python -Arguments @("scripts\analyze_failures.py", "--results", $Results)

Write-Host "[7/11] Generating measured Markdown report..."
Invoke-Checked -Executable $Python -Arguments @("scripts\make_report.py", "--results", $Results, "--validation", $Validation, "--output", (Join-Path $Results "REPORT.md"))

Write-Host "[8/11] Generating paper figures..."
Invoke-Checked -Executable $Python -Arguments @("scripts\make_figures.py", "--results", $Results, "--output", (Join-Path $Results "figures"))

Write-Host "[9/11] Generating formatted result workbook..."
Invoke-Checked -Executable $Node -Arguments @("scripts\build_results_workbook.mjs", "--results", $Results, "--validation", $Validation, "--output", $WorkbookOutput)

Write-Host "[10/11] Building a reproducible demonstration case..."
Invoke-Checked -Executable $Python -Arguments @("scripts\demo_case.py", "--benchmark", $Benchmark, "--output", (Join-Path $Results "demo"))

Write-Host "[11/11] Auditing evidence completeness..."
Invoke-Checked -Executable $Python -Arguments @("scripts\audit_outputs.py", "--benchmark", $Benchmark, "--results", $Results, "--strict")

if ($WithSensitivity) {
    Write-Host "[extra] Running bounded candidate-count and weight sensitivity..."
    Invoke-Checked -Executable $Python -Arguments @("scripts\run_sensitivity.py", "--benchmark", $Benchmark, "--validation", (Join-Path $Validation "validated_instances.jsonl"), "--output", $Results, "--limit", "48")
}

if ($WithPerformance) {
    Write-Host "[extra] Building and timing scaling benchmarks..."
    $Scaling = Join-Path $ProjectRoot "data\scaling"
    Invoke-Checked -Executable $Node -Arguments @("scripts\build_scaling_benchmarks.mjs", "--output", $Scaling, "--sizes", "100,500,1000,5000")
    Invoke-Checked -Executable $Python -Arguments @("scripts\run_performance.py", "--input", $Scaling, "--output", (Join-Path $Results "performance.csv"))
}

if ($WithLibreOffice) {
    Write-Host "[extra] Cross-checking a bounded sample with LibreOffice..."
    Invoke-Checked -Executable $Python -Arguments @("scripts\validate_with_libreoffice.py", "--benchmark", $Benchmark, "--output", $Results, "--limit", "20", "--required")
}

Stop-Transcript | Out-Null
$script:TranscriptActive = $false
Invoke-Checked -Executable $Python -Arguments @("scripts\build_result_index.py", "--results", $Results)

Write-Host "Pipeline finished."
Write-Host "Main table: $Results\summary.csv"
Write-Host "Report: $Results\REPORT.md"
Write-Host "Workbook: $WorkbookOutput"
exit 0
