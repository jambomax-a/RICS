# RICS 起動スクリプト（プロジェクトルートで実行）
param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
& .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -q
$env:PYTHONPATH = $PSScriptRoot

$inUse = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($inUse) {
    $procId = $inUse[0].OwningProcess
    Write-Host "ポート $Port は既に使用中です (PID $procId)。" -ForegroundColor Yellow
    Write-Host "  既に起動済みならブラウザで http://127.0.0.1:$Port を開いてください。"
    Write-Host "  止める場合: Stop-Process -Id $procId -Force"
    Write-Host "  別ポートで起動: .\run.ps1 -Port 8766"
    exit 1
}

$HostAddr = "0.0.0.0"  # 外部受入を許可

Write-Host "RICS Server starting on: http://localhost:$Port" -ForegroundColor Green
# --reload は SQLite ロックの原因になりやすいため通常は無効
if ($env:RICS_RELOAD -eq "1") {
    uvicorn backend.main:app --reload --host $HostAddr --port $Port
}
else {
    uvicorn backend.main:app --host $HostAddr --port $Port
}
