# WiFi 优先级调整脚本 — 让 WiFi 优先级高于有线
# 适用场景：热点提供外网 + 有线网口测试校园网认证
# 支持中英文 Windows 网卡名
#
# 使用:
#   .\set_wifi_priority.ps1              # 设置 WiFi 优先（一次性）
#   .\set_wifi_priority.ps1 -Watch       # 持续监控，阻止有线抢默认路由
#   .\set_wifi_priority.ps1 -Reset       # 恢复默认（有线优先）

param([switch]$Reset, [switch]$Watch)

# 需要管理员权限
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "需要管理员权限，正在尝试提权..." -ForegroundColor Yellow
    $argList = "-NoProfile -ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Path)`""
    if ($Reset)  { $argList += " -Reset" }
    if ($Watch)  { $argList += " -Watch" }
    Start-Process pwsh -Verb RunAs -ArgumentList $argList
    exit
}

# 匹配 WiFi 和有线网卡的名称模式（中英文）
$wifiPattern  = "WLAN|Wi-Fi|WiFi"
$wiredPattern = "以太网|Ethernet"

# 备份文件路径
$backupFile = "$PSScriptRoot\metric_backup.json"
$regBackupFile = "$PSScriptRoot\dhcp_gateway_backup.json"

# ============================================================
# 工具函数
# ============================================================

function Get-WiredAdapters {
    Get-NetIPInterface -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -match $wiredPattern }
}

function Remove-WiredDefaultRoutes {
    $removed = 0
    Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
        Where-Object { $_.InterfaceAlias -match $wiredPattern } |
        ForEach-Object {
            Remove-NetRoute -DestinationPrefix "0.0.0.0/0" -InterfaceIndex $_.InterfaceIndex -Confirm:$false -ErrorAction SilentlyContinue
            $removed++
        }
    return $removed
}

function Set-WiredDHCPGatewayDisabled {
    <#
    通过注册表禁用有线网卡的 DHCP 默认网关。
    注册表路径: HKLM\...\Interfaces\{GUID}\DisableDefaultGateway = 1
    这是唯一能持久阻止 DHCP 下发默认路由的方法。
    #>
    $results = @()
    Get-NetAdapter | Where-Object { $_.Name -match $wiredPattern } | ForEach-Object {
        $guid = $_.InterfaceGuid
        $regPath = "HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\$guid"
        try {
            Set-ItemProperty -Path $regPath -Name "DisableDefaultGateway" -Value 1 -Type DWord -Force -ErrorAction Stop
            $results += @{ Name=$_.Name; Guid=$guid; Status="OK" }
        } catch {
            $results += @{ Name=$_.Name; Guid=$guid; Status="FAIL: $_" }
        }
    }
    return $results
}

function Restore-WiredDHCPGateway {
    # 恢复注册表中的 DisableDefaultGateway 为 0
    Get-NetAdapter | Where-Object { $_.Name -match $wiredPattern } | ForEach-Object {
        $guid = $_.InterfaceGuid
        $regPath = "HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\$guid"
        try {
            Remove-ItemProperty -Path $regPath -Name "DisableDefaultGateway" -Force -ErrorAction Stop
            Write-Host "  已恢复 DHCP 网关: $($_.Name)" -ForegroundColor Green
        } catch {
            # 键不存在也算 OK
        }
    }
}

# ============================================================
# -Watch 模式：持续清理有线网卡的默认路由
# ============================================================

if ($Watch) {
    Write-Host "Watch 模式启动 — 每 10 秒检查并删除有线网卡的默认路由" -ForegroundColor Cyan
    Write-Host "按 Ctrl+C 退出" -ForegroundColor DarkGray
    while ($true) {
        $n = Remove-WiredDefaultRoutes
        if ($n -gt 0) {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 删除了 $n 条默认路由" -ForegroundColor Yellow
        }
        Start-Sleep 10
    }
    exit
}

# ============================================================
# -Reset 模式：恢复出厂设置
# ============================================================

if ($Reset) {
    Write-Host "恢复默认: 有线优先..." -ForegroundColor Yellow

    # 恢复跃点数
    if (Test-Path $backupFile) {
        $backup = Get-Content $backupFile -Raw | ConvertFrom-Json
        foreach ($entry in $backup.PSObject.Properties) {
            $idx = [int]$entry.Name
            $origMetric = $entry.Value
            try {
                Set-NetIPInterface -InterfaceIndex $idx -InterfaceMetric $origMetric -ErrorAction Stop
                $iface = Get-NetIPInterface -InterfaceIndex $idx -AddressFamily IPv4 -ErrorAction SilentlyContinue
                if ($iface) {
                    Write-Host "  已恢复跃点 $($iface.InterfaceAlias): $origMetric" -ForegroundColor Green
                }
            } catch {
                Write-Host "  恢复 InterfaceIndex=$idx 失败: $_" -ForegroundColor Yellow
            }
        }
        Remove-Item $backupFile -Force
    } else {
        Write-Host "  未找到跃点备份，使用默认值..." -ForegroundColor Yellow
        Get-NetIPInterface -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -match $wifiPattern } |
            Set-NetIPInterface -InterfaceMetric 40
        Get-NetIPInterface -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -match $wiredPattern } |
            Set-NetIPInterface -InterfaceMetric 5
    }

    # 恢复 DHCP 默认网关
    Restore-WiredDHCPGateway

    Write-Host "已恢复。可能需要重启网卡或插拔网线才能生效。" -ForegroundColor Green
    exit
}

# ============================================================
# 主模式：设置 WiFi 优先
# ============================================================

Write-Host "=" * 50 -ForegroundColor Cyan
Write-Host "设置 WiFi 优先 (热点外网 + 有线校园网)" -ForegroundColor Cyan
Write-Host "=" * 50 -ForegroundColor Cyan

# 1. 备份当前状态
Write-Host "[1/4] 备份当前状态..." -ForegroundColor DarkGray
$backup = @{}
Get-NetIPInterface -AddressFamily IPv4 |
    Where-Object { $_.InterfaceAlias -match "$wifiPattern|$wiredPattern" } |
    ForEach-Object { $backup["$($_.InterfaceIndex)"] = $_.InterfaceMetric }
$backup | ConvertTo-Json | Set-Content $backupFile -Force

# 2. 调整跃点数
Write-Host "[2/4] 调整网卡跃点数..." -ForegroundColor DarkGray

$wifi = Get-NetIPInterface -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -match $wifiPattern }
if ($wifi) {
    $wifiMetric = 3
    $wifi | Set-NetIPInterface -InterfaceMetric $wifiMetric
    Write-Host "  WiFi ($($wifi.InterfaceAlias)) → 跃点 $wifiMetric (最高优先)" -ForegroundColor Green
} else {
    Write-Host "  [WARN] 未找到 WiFi 网卡" -ForegroundColor Red
}

$wired = Get-WiredAdapters
if ($wired) {
    $wiredMetric = 100
    foreach ($if in $wired) {
        Write-Host "  有线 ($($if.InterfaceAlias)) → 跃点 $wiredMetric (低优先)" -ForegroundColor Yellow
        Set-NetIPInterface -InterfaceIndex $if.InterfaceIndex -InterfaceMetric $wiredMetric
        # 关闭自动跃点，防止 Windows 重新计算
        Set-NetIPInterface -InterfaceIndex $if.InterfaceIndex -AutomaticMetric Disabled
    }
} else {
    Write-Host "  [WARN] 未找到有线网卡" -ForegroundColor Yellow
}

# 3. 删除有线网卡已有的默认路由
Write-Host "[3/4] 清理有线网卡的默认路由..." -ForegroundColor DarkGray
$n = Remove-WiredDefaultRoutes
if ($n -gt 0) {
    Write-Host "  删除了 $n 条默认路由" -ForegroundColor Yellow
} else {
    Write-Host "  当前没有有线的默认路由（或网卡未连接）" -ForegroundColor DarkGray
}

# 4. 通过注册表持久禁用有线网卡的 DHCP 默认网关
Write-Host "[4/4] 禁用有线网卡的 DHCP 默认网关（注册表持久化）..." -ForegroundColor DarkGray
$regResults = Set-WiredDHCPGatewayDisabled
foreach ($r in $regResults) {
    if ($r.Status -eq "OK") {
        Write-Host "  $($r.Name): 已禁用 DHCP 默认网关" -ForegroundColor Green
    } else {
        Write-Host "  $($r.Name): $($r.Status)" -ForegroundColor Red
    }
}

# 完成
Write-Host ""
Write-Host "当前跃点（越小越优先）:" -ForegroundColor Cyan
Get-NetIPInterface -AddressFamily IPv4 |
    Where-Object { $_.InterfaceAlias -match "$wifiPattern|$wiredPattern" } |
    Sort-Object InterfaceMetric |
    Select-Object InterfaceAlias, InterfaceMetric |
    Format-Table -AutoSize

Write-Host ""
Write-Host "[OK] 设置完成。" -ForegroundColor Green
Write-Host "  插上光纤后，有线网卡不会抢默认路由，WiFi 始终提供外网。" -ForegroundColor Cyan
Write-Host ""
Write-Host "  如果插拔光纤后仍出现断网，运行: .\set_wifi_priority.ps1 -Watch" -ForegroundColor Yellow
Write-Host "  恢复默认: .\set_wifi_priority.ps1 -Reset" -ForegroundColor DarkGray
