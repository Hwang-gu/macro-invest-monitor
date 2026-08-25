# 매일 07:00 (한국 시간) 미국 장 마감 이후 데이터를 받아 모델을 갱신합니다.
# 관리자 PowerShell에서 실행:  Set-ExecutionPolicy -Scope Process Bypass; .\scripts\install_daily_task.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python).Source
$script = Join-Path $root "scripts\daily.py"
$log = Join-Path $root "data\reports\scheduler.log"

$action = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At 7:00AM
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "MacroInvestDaily" -Action $action -Trigger $trigger -Settings $settings -Description "Collect markets and refresh allocation report" -Force | Out-Null
Write-Host "Scheduled task MacroInvestDaily registered (daily 07:00)."
Write-Host "Log folder: $log"
