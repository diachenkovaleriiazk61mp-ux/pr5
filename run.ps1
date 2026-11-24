param([ValidateSet("all","check","global","rw","serial","parallel","smoke")][string]$Stage="all")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Python = (Get-Command python -ErrorAction Stop).Source
& $Python -c "import sys; assert sys.version_info >= (3,10), 'Python 3.10 or newer is required'"
if ($LASTEXITCODE -ne 0) { throw "Python check failed" }
if ($Stage -eq "check") {
    & $Python check.py
} elseif ($Stage -eq "smoke") {
    & $Python benchmark.py --smoke
} elseif ($Stage -eq "global" -or $Stage -eq "rw") {
    & $Python benchmark.py --mode $Stage
} elseif ($Stage -eq "serial" -or $Stage -eq "parallel") {
    & $Python benchmark.py --kind $Stage
} else {
    & $Python check.py
    if ($LASTEXITCODE -ne 0) { throw "Correctness checks failed" }
    & $Python -u benchmark.py
    if ($LASTEXITCODE -ne 0) { throw "Measurements failed" }
    & $Python audit.py
}
if ($LASTEXITCODE -ne 0) { throw "Stage failed: $Stage" }
