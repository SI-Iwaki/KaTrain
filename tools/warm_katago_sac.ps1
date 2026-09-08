<#
.SYNOPSIS
  Smart App Control (SAC) の初回評価を、ログオン時に katago.exe を空打ちして済ませておく。

.DESCRIPTION
  この PC は SAC が有効で、未署名の実行ファイルの許可判定は NTFS 拡張属性
  $KERNEL.PURGE.ESBCACHE にキャッシュされる。名前のとおり再起動で purge されるため、
  purge 後の「初回実行」がクラウド照会の結果を待たずに拒否され
  [WinError 4551] になることがある（数分後には自然に通る）。

  実測 2026-09-09: 9/8 14:17 の再起動後、9/9 3:11 の KaTrain 起動が 4551 で失敗し、
  3:15 には同じファイルが通った。旧 katago.exe でも 8/2 に同じ単発ブロックが出ている。

  このスクリプトを「ログオン時」のタスクで回しておくと、ユーザーが KaTrain や
  katrain_debug / E2E ハーネスを起動する頃には評価が済んでいる。
  判定・解析には一切影響しない（version を表示して終わるだけ）。

.NOTES
  タスク登録は  tools\warm_katago_sac.ps1 -Install
  解除は        tools\warm_katago_sac.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Uninstall,
    [int]$MaxAttempts = 6,
    [int]$RetryDelaySeconds = 30
)

$ErrorActionPreference = 'Continue'
$TaskName = 'KaTrain-WarmKataGoSAC'
$KatrainHome = Join-Path $env:USERPROFILE '.katrain'
$LogFile = Join-Path $KatrainHome 'logs\sac_warmup.log'

function Write-Log([string]$Message) {
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Write-Output $line
    try {
        $dir = Split-Path $LogFile -Parent
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        Add-Content -Path $LogFile -Value $line -Encoding utf8
    } catch { }
}

function Install-Task {
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $PSCommandPath)
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    # ログオン直後はネットワークが上がりきっておらず ISG 照会が通らないので少し待つ
    $trigger.Delay = 'PT1M'
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Description 'KataGo の実行ファイルを空打ちして Smart App Control の初回評価を済ませる' -Force | Out-Null
    Write-Log ('タスク {0} を登録しました: {1}' -f $TaskName, $PSCommandPath)
}

function Uninstall-Task {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Log ('タスク {0} を解除しました' -f $TaskName)
}

function Invoke-Warmup {
    if (-not (Test-Path $KatrainHome)) { Write-Log ('{0} が無いので何もしません' -f $KatrainHome); return }
    $exes = @(Get-ChildItem -Path $KatrainHome -Recurse -Depth 2 -Filter 'katago*.exe' -File -ErrorAction SilentlyContinue |
              Sort-Object FullName)
    if ($exes.Count -eq 0) { Write-Log ('{0} に katago*.exe がありません' -f $KatrainHome); return }

    $pending = [System.Collections.ArrayList]@($exes.FullName)
    for ($attempt = 1; $attempt -le $MaxAttempts -and $pending.Count -gt 0; $attempt++) {
        $stillBlocked = [System.Collections.ArrayList]@()
        foreach ($exe in $pending) {
            $null = & $exe version 2>&1
            $code = $LASTEXITCODE
            if ($code -eq 0) {
                Write-Log ('OK       {0}' -f $exe)
            } else {
                # 4551 は 0xC0000428 相当のポリシー拒否として -1073740760 等で返る
                Write-Log ('BLOCKED  {0} (exit {1}, attempt {2}/{3})' -f $exe, $code, $attempt, $MaxAttempts)
                [void]$stillBlocked.Add($exe)
            }
        }
        $pending = $stillBlocked
        if ($pending.Count -gt 0 -and $attempt -lt $MaxAttempts) { Start-Sleep -Seconds $RetryDelaySeconds }
    }
    if ($pending.Count -gt 0) {
        Write-Log ('WARN     まだ通らない実行ファイル: {0}' -f ($pending -join ', '))
    } else {
        Write-Log '完了: すべての katago 実行ファイルが起動できます'
    }
}

if ($Install)        { Install-Task }
elseif ($Uninstall)  { Uninstall-Task }
else                 { Invoke-Warmup }
