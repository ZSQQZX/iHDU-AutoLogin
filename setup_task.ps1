# 校园网自动登录 - 任务计划注册
# 用法: .\setup_task.ps1          # 注册
#       .\setup_task.ps1 -Remove  # 删除

param([switch]$Remove)

$TaskName = "SrunAutoLogin"
$WorkDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$Wrapper   = Join-Path $WorkDir "run_wrapper.ps1"

if ($Remove) {
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
        Write-Host "[OK] 已删除: $TaskName" -ForegroundColor Green
    } catch {
        Write-Host "任务不存在: $_" -ForegroundColor Yellow
    }
    exit
}

# 检查包装器
if (-not (Test-Path $Wrapper)) {
    Write-Host "[ERROR] 找不到: $Wrapper" -ForegroundColor Red
    exit 1
}

# 动作：用 PowerShell 运行包装器（自动加路由 + 启动 Python）
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -File `"$Wrapper`"" `
    -WorkingDirectory $WorkDir

# 触发器1: 用户登录
$T1 = New-ScheduledTaskTrigger -AtLogOn

# 触发器2: 系统启动后 2 分钟
$T2 = New-ScheduledTaskTrigger -AtStartup -RandomDelay (New-TimeSpan -Minutes 2)

# 触发器3: 每 10 分钟兜底（防脚本异常退出）
$T3 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 10) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit 0 `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

# 以管理员权限运行（加路由需要）
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $T1, $T2, $T3 `
        -Settings $Settings `
        -Principal $Principal `
        -Description "校园网 srun 自动登录：检测断网 → 自动认证" `
        -Force `
        -ErrorAction Stop

    Write-Host ""
    Write-Host "[OK] 任务已注册: $TaskName" -ForegroundColor Green
    Write-Host ""
    Write-Host "  工作目录: $WorkDir"
    Write-Host "  运行方式: 管理员权限，无窗口"
    Write-Host "  触发: 登录 + 开机 + 每10分钟"
    Write-Host ""
    Write-Host "  配置文件: srun_config.json" -ForegroundColor Cyan
    Write-Host "  日志文件: srun_login.log" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  手动测试: python srun_auto_login.py" -ForegroundColor DarkGray
    Write-Host "  删除任务: .\setup_task.ps1 -Remove" -ForegroundColor DarkGray

} catch {
    Write-Host "[ERROR] 注册失败: $_" -ForegroundColor Red
    Write-Host "请以管理员身份运行此脚本" -ForegroundColor Yellow
}
