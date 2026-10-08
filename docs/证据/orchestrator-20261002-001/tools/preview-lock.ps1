# 预览服务器端口锁：让多个包共享硬编码的 4173 端口而不互抢。
#
# 背景：`apps/web/e2e/support/paths.ts` 的 PREVIEW_PORT = 4173 是硬编码常量，
# playwright.config.ts 用 `--strictPort` 起它。因此并发跑 shots/build 必须串行占用端口。
# 本脚本用「原子创建锁文件」实现互斥（New-Item 在文件已存在时失败，是原子的）。
#
# 用法：
#   preview-lock.ps1 acquire [-TimeoutSec 900] [-Holder 'T03-executor']
#   preview-lock.ps1 release
# 退出码：0 = 成功；1 = 未取到（超时/被占用）。
#
# 陈旧锁：锁内有 pid 与 acquiredAt。若 pid 已不存在，或锁龄超过 StaleMinutes，则回收并告警。

[CmdletBinding()]
param(
  [Parameter(Mandatory = $true, Position = 0)]
  [ValidateSet('acquire', 'release', 'status')]
  [string]$Action,

  [int]$TimeoutSec = 900,
  [int]$StaleMinutes = 15,
  [string]$Holder = 'unknown'
)

$ErrorActionPreference = 'Stop'
$lockPath = Join-Path $PSScriptRoot 'preview-4173.lock'

function Write-LockInfo([string]$Path) {
  if (-not (Test-Path $Path)) { return }
  $raw = Get-Content $Path -Raw -ErrorAction SilentlyContinue
  Write-Host "  锁内容: $($raw.Trim())"
}

function Test-LockStale([string]$Path) {
  # 返回 $true 表示陈旧可回收。
  #
  # 为什么**不**用「持有 pid 是否还存在」判断陈旧：本锁的持有者是一次
  # `pwsh -File preview-lock.ps1 acquire` 调用，它取到锁后**立刻就退出了**。
  # 于是第二次 acquire 时 pid 必然已消失 —— 那样会立刻把活锁当成陈旧锁抢走，
  # 互斥完全失效（该缺陷由 2026-10-02 的互斥测试当场暴露：第二个 holder 在 2 次尝试内抢到了锁）。
  # 因此陈旧性只看**锁龄**；pid 仅作诊断信息保留。
  if (-not (Test-Path $Path)) { return $false }
  $text = (Get-Content $Path -Raw -ErrorAction SilentlyContinue)
  if ([string]::IsNullOrWhiteSpace($text)) { return $true }

  $at = $null
  foreach ($line in ($text -split "`n")) {
    if ($line -match '^\s*acquiredAt\s*=\s*(.+)$') { $at = $Matches[1].Trim() }
  }

  if ($at -eq $null) {
    # 没有时间戳的锁无法判断新旧：按文件 mtime 兜底，拿不到就当陈旧。
    try { return (((Get-Date) - (Get-Item $Path).LastWriteTime).TotalMinutes -gt $StaleMinutes) }
    catch { return $true }
  }
  try {
    $when = [datetime]::Parse($at)
    if (((Get-Date) - $when).TotalMinutes -gt $StaleMinutes) {
      Write-Host "  [告警] 锁龄超过 $StaleMinutes 分钟（$at）—— 按陈旧锁回收"
      return $true
    }
  } catch {
    Write-Host "  [告警] 锁的时间戳无法解析（$at）—— 按陈旧锁回收"
    return $true
  }
  return $false
}

function Test-PortBusy() {
  $c = Get-NetTCPConnection -LocalPort 4173 -State Listen -ErrorAction SilentlyContinue
  return ($null -ne $c)
}

switch ($Action) {
  'status' {
    if (Test-Path $lockPath) { Write-Host '锁: 已存在'; Write-LockInfo $lockPath }
    else { Write-Host '锁: 不存在（空闲）' }
    Write-Host ("4173 监听: " + $(if (Test-PortBusy) { '是' } else { '否' }))
    exit 0
  }

  'acquire' {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $attempt = 0
    while ($true) {
      $attempt++
      try {
        # 原子创建：文件已存在则抛异常
        $content = "holder=$Holder`npid=$PID`nacquiredAt=$((Get-Date).ToString('o'))`n"
        New-Item -Path $lockPath -ItemType File -Value $content -ErrorAction Stop | Out-Null
        Write-Host "[锁] 已取到（holder=$Holder, pid=$PID, 第 $attempt 次尝试）"
        exit 0
      } catch {
        # 已被占用：判断是否陈旧
        if (Test-LockStale $lockPath) {
          Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
          continue
        }
        if ((Get-Date) -ge $deadline) {
          Write-Host "[锁] 超时未取到（等了 $TimeoutSec 秒）"
          Write-LockInfo $lockPath
          Write-Host ("  4173 监听: " + $(if (Test-PortBusy) { '是' } else { '否' }))
          exit 1
        }
        if ($attempt -eq 1) {
          Write-Host "[锁] 被占用，等待中（最多 $TimeoutSec 秒）…"
          Write-LockInfo $lockPath
        }
        Start-Sleep -Seconds 5
      }
    }
  }

  'release' {
    if (-not (Test-Path $lockPath)) {
      Write-Host '[锁] 无锁可释放（可能已释放）'
      exit 0
    }
    $text = (Get-Content $lockPath -Raw -ErrorAction SilentlyContinue)
    if ($text -match 'pid=(\d+)') {
      $owner = [int]$Matches[1]
      if ($owner -ne $PID) {
        Write-Host "[告警] 锁的持有者是 pid=$owner，当前进程是 $PID —— 仍按请求释放（调用方须自行确认不会误放）"
      }
    }
    Remove-Item $lockPath -Force
    Write-Host '[锁] 已释放'
    exit 0
  }
}
