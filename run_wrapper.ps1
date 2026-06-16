# 校园网自动登录启动包装器
# 先加路由，再启动 Python 守护
# 以管理员权限运行（由计划任务调用）

$scriptPath = Join-Path $PSScriptRoot "srun_auto_login.py"

# 0) 进程互斥：如果已有实例在运行则直接退出
$existing = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match [regex]::Escape($scriptPath) }
if ($existing) {
    exit 0
}
$existingPy = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match [regex]::Escape($scriptPath) }
if ($existingPy) {
    exit 0
}

# 匹配有线网卡名（中英文）
$wiredPattern = "以太网|Ethernet"

try {
    # 1) 找到有线网卡的默认网关
    $wiredIf = Get-NetIPInterface -AddressFamily IPv4 |
        Where-Object { $_.InterfaceAlias -match $wiredPattern -and $_.ConnectionState -eq 'Connected' } |
        Select-Object -First 1

    if ($wiredIf) {
        $route = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -InterfaceIndex $wiredIf.InterfaceIndex -ErrorAction SilentlyContinue
        if ($route) {
            $gw = $route.NextHop
            # 2) 添加校园网 Portal 网段的精确路由（如果不存在）
            $existing = Get-NetRoute -DestinationPrefix "192.168.112.0/24" -ErrorAction SilentlyContinue
            if (-not $existing) {
                New-NetRoute -DestinationPrefix "192.168.112.0/24" -InterfaceIndex $wiredIf.InterfaceIndex -NextHop $gw -RouteMetric 1 -ErrorAction SilentlyContinue
            }
        }
    }
} catch {
    # 路由添加失败不影响主脚本运行
}

# 3) 启动 Python 守护脚本
$pythonPath = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $pythonPath) {
    $pythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
}

& $pythonPath $scriptPath
