# setup_task.ps1 — Windowsタスクスケジューラに登録するスクリプト
# 管理者権限のPowerShellで実行してください
# 使い方: powershell -ExecutionPolicy Bypass -File setup_task.ps1

$taskName   = "FX-AI-Trader-Scanner"
$pythonPath = "C:\Users\mao\Desktop\fx-trader-desktop\.venv\Scripts\python.exe"
$scriptPath = "C:\Users\mao\Desktop\fx-trader-desktop\src-python\run_background.py"
$workDir    = "C:\Users\mao\Desktop\fx-trader-desktop\src-python"

# 既存タスクを削除
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# タスク設定
$action  = New-ScheduledTaskAction -Execute $pythonPath -Argument $scriptPath -WorkingDirectory $workDir
$trigger = New-ScheduledTaskTrigger -AtStartup   # PC起動時に自動スタート
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Days 365) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $taskName `
    -Action   $action `
    -Trigger  $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Description "FX AI Trader 毎時シグナルスキャン + LINE/Discord通知"

Write-Host "タスク登録完了: $taskName" -ForegroundColor Green
Write-Host "今すぐ起動する場合:" -ForegroundColor Yellow
Write-Host "  Start-ScheduledTask -TaskName '$taskName'" -ForegroundColor Yellow
