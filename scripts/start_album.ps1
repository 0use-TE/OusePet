param([int]$Port = 8766)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$albumPython = Join-Path $projectRoot '.venv-smoke/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $albumPython)) {
    throw '请先准备 .venv-smoke Python 环境，参见 README 的前端面板说明。'
}
Push-Location -LiteralPath (Join-Path $projectRoot 'frontend')
try {
    if (-not (Test-Path -LiteralPath 'node_modules')) {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
    }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw '前端编译失败' }
} finally { Pop-Location }
Write-Host "有宠相簿：http://127.0.0.1:$Port"
& $albumPython -m uvicorn ousepet.api:app --host 127.0.0.1 --port $Port
