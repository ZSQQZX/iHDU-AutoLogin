# 校园网 srun 自动登录

> 杭州电子科技大学 / 深澜 srun Portal 认证  
> 插光纤 → 自动检测 → 自动拨号。全程零操作。

## 快速开始

1. 编辑 `srun_config.json`，填入 **学号** 和 **密码**
2. 管理员运行 `.\setup_task.ps1`，注册后台任务
3. 完事。开机/插光纤自动认证

## 文件说明

| 文件 | 用途 |
|------|------|
| `srun_auto_login.py` | 守护脚本：检测断网 → srun 加密认证 → 循环 |
| `srun_config.json` | 配置文件（账号/密码/网关/间隔） |
| `run_wrapper.ps1` | 包装器：自动加校园网路由 + 启动 Python |
| `setup_task.ps1` | 一键注册/删除 Windows 计划任务 |
| `set_wifi_priority.ps1` | 设置 WiFi 优先于有线（热点+校园网双网卡场景） |

## 原理

```
检测 192.168.112.30 可达 → get_challenge(token) → xEncode×Base64 加密
→ HMAC-MD5 密码 → SHA1 校验 → srun_portal 登录 → 成功后 5 分钟再检
```

加密实现完全对照 Portal.js 源码：
- XXTEA **srun 变体**（注意：不是标准 XXTEA，公式中 `+`/`^` 分组不同）
- 自定义 Base64 字母表
- 消息长度追加

## 手动运行

```powershell
# 前台（看日志）
python srun_auto_login.py

# 后台（无窗口）
pythonw srun_auto_login.py

# 取消后台
.\setup_task.ps1 -Remove
```

## 配置项

```json
{
    "username": "学号",
    "password": "密码",
    "gateway": "192.168.112.30",
    "ac_id": "0",
    "check_interval": 30,      // 未认证时检测间隔（秒）
    "online_interval": 300,    // 在线时检测间隔（秒）
    "log_file": "路径\\srun_login.log"
}
```

## 日志

运行日志在 `srun_login.log`，超过 1MB 自动轮转。

## 其他学校

只要是深澜 srun Portal（`srun_portal` / `get_challenge` 接口），改 `gateway` 和 `ac_id` 就能用。如果不通，抓浏览器登录请求比对参数即可。

## 安全

密码明文存于 `srun_config.json`，**不要上传到公开仓库**。
