$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (Test-Path -LiteralPath $BundledPython) {
    $Python = $BundledPython
} else {
    $Command = Get-Command python -ErrorAction SilentlyContinue
    if (-not $Command) { throw "Python 3.11 or newer was not found." }
    $Python = $Command.Source
}

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $Python -m unittest discover -s tests -p "test_*.py" -v
    $TestExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}
exit $TestExitCode
