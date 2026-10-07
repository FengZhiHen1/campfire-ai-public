# T11 真实栈运行器：每次运行自动签发若干枚全新邀请码（邀请码是一次性的）。
#
# 用法（在仓库根执行）：
#   pwsh -File tmp/T11/run-real.ps1                       # 全部 @real 验收用例
#   pwsh -File tmp/T11/run-real.ps1 -Grep "链路4"          # 只跑某一条
#   pwsh -File tmp/T11/run-real.ps1 -Grep "@ablation"     # 只跑消融/控制证明
#
# 前置：后端（8000）与前端 dev（5173）已在跑，数据服务 healthy。
#   后端必须用规范化过 no_proxy 的环境启动（见 tmp/T11/start-backend.cmd）。
#
# 为什么签发**多枚**而不是一枚：邀请码一次性使用，而本轮有 3 处真实注册
# （验收链路 1 一次 + 消融/控制臂各一次）。只签一枚会产生假红。
param(
    [string]$Grep = "@real",
    [int]$CodeCount = 4,
    [string]$Out = "tmp\T11"
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $repoRoot

$env:T10_BASE_URL = 'http://localhost:5173'
# 产物落到 T11 目录，不覆盖 T10 的证据。
$env:T10_OUT = (Join-Path $repoRoot $Out)

Write-Output "==> 签发 $CodeCount 枚新邀请码"
$codes = @()
for ($i = 0; $i -lt $CodeCount; $i++) {
    $issueOutput = uv run python -m campfire.cli invite issue 2>&1 | Out-String
    $code = [regex]::Match($issueOutput, '\b([A-Z0-9]{8})\b').Groups[1].Value
    if ($code -eq '') {
        Write-Error "无法从 CLI 输出里解析邀请码：`n$issueOutput"
    }
    $codes += $code
}
Write-Output "    邀请码 = $($codes -join ', ')"
$env:T10_INVITE_CODE = $codes[0]
$env:T10_INVITE_CODES = ($codes -join ',')

Write-Output "==> 运行真实栈探针（grep='$Grep'）"
pnpm --filter '@campfire/web' exec playwright test `
    --config e2e-real/playwright.real.config.ts `
    --reporter=list `
    --grep $Grep 2>&1 | Tee-Object -FilePath (Join-Path $repoRoot "$Out\real-run-latest.txt")
exit $LASTEXITCODE
