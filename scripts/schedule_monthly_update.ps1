# Registers a Windows scheduled task: the 10th of every month at 03:00, runs ml/pipelines/monthly_update.py.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\schedule_monthly_update.ps1 [-Upload user@host]
# If the laptop is off at 03:00 the task runs at the next start (StartWhenAvailable).
param([string]$Upload = "")

$root = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python).Source
$arg = "ml\pipelines\monthly_update.py"
if ($Upload) { $arg += " --upload $Upload" }

$trigger = New-ScheduledTaskTrigger -Daily -At 3:00AM
# The cmdlet has no "day 10 of the month" trigger: run daily, only act from day 10 on. The script is idempotent
# and only trains when a new month has been published.
$action = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $root `
  -Argument "-NoProfile -Command `"if ((Get-Date).Day -ge 10) { & '$python' $arg *>> data\monthly_update.log }`""
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName "HeimkommenMonthlyUpdate" -Action $action -Trigger $trigger -Settings $settings -Force
Write-Host "Registered. Log: $root\data\monthly_update.log"
