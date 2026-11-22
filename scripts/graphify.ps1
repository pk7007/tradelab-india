param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$GraphifyArguments = @('--help')
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$graphifyExecutable = Join-Path $projectRoot '.tools/graphify-venv/Scripts/graphify.exe'
if (-not (Test-Path -LiteralPath $graphifyExecutable)) {
    throw 'Graphify is not installed locally. See docs/graphify-setup.md.'
}

$previousBackend = [Environment]::GetEnvironmentVariable('GRAPHIFY_BACKEND', 'Process')
$graphifyExitCode = 1
Push-Location -LiteralPath $projectRoot
try {
    $env:GRAPHIFY_BACKEND = 'none'
    & $graphifyExecutable @GraphifyArguments
    $graphifyExitCode = $LASTEXITCODE
}
finally {
    [Environment]::SetEnvironmentVariable('GRAPHIFY_BACKEND', $previousBackend, 'Process')
    Pop-Location
}
exit $graphifyExitCode
