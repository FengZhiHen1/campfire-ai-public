# MVP 种子数据导入 — Windows 一键入口
# 用法: .\scripts\seed.ps1 [-append] [-count N]

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $scriptDir "..")

Write-Host "=== Campfire-AI MVP 种子数据导入 ===" -ForegroundColor Cyan

$pyArgs = @()
if ($append) { $pyArgs += "--append" }
if ($count) { $pyArgs += "--count"; $pyArgs += "$count" }

uv run scripts/seed.py @pyArgs
