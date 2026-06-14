#!/usr/bin/env python3
"""
校园网 srun 深澜 Portal 自动登录脚本
适用：杭州电子科技大学 (HDU) 及使用 srun 认证的学校
纯 Python 标准库，零外部依赖

使用方式：
    python srun_auto_login.py              # 前台运行，带日志输出
    pythonw srun_auto_login.py             # 后台静默运行（无控制台窗口）
"""

import json
import hmac
import hashlib
import struct
import socket
import time
import sys
import os
import re
import urllib.request
import urllib.error
import urllib.parse

# ──────────────────────────────────────────────────
# 0. 配置加载
# ──────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "srun_config.json")

DEFAULT_CONFIG = {
    "username": "你的学号",
    "password": "你的校园网密码",
    "gateway": "192.168.112.30",
    "ac_id": "0",
    "check_interval": 30,       # 未认证时检测间隔（秒）
    "online_interval": 300,     # 已在线时检测间隔（秒），避免频繁请求
    "log_file": os.path.join(SCRIPT_DIR, "srun_login.log"),
}


def load_config():
    """加载配置文件，不存在则创建模板"""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # 合并默认值
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    else:
        # 创建模板
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        log(f"配置文件模板已创建: {CONFIG_PATH}")
        log("请编辑配置文件填入账号密码后重新运行")
        sys.exit(0)


# ──────────────────────────────────────────────────
# 1. 日志
# ──────────────────────────────────────────────────

_LOG_FILE = None


def log(msg):
    """打印带时间戳的日志，同时写入文件"""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        # GBK 终端无法打印某些 Unicode 字符时降级
        print(line.encode("gbk", errors="replace").decode("gbk"), flush=True)
    if _LOG_FILE:
        try:
            _LOG_FILE.write(line + "\n")
            _LOG_FILE.flush()
        except Exception:
            pass


# ──────────────────────────────────────────────────
# 2. srun 自定义 Base64
# ──────────────────────────────────────────────────

SRUN_ALPHABET = (
    "LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA"
)


def _long_to_bytes(n: int) -> bytes:
    """32位整数转小端序字节（小端序）"""
    return struct.pack("<I", n & 0xFFFFFFFF)


def _bytes_to_long(b):
    """小端序字节转32位整数"""
    return struct.unpack("<I", b[:4])[0]


def srun_base64_encode(data: bytes) -> str:
    """
    用 srun 自定义字母表进行 Base64 编码
    字母表: LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA
    """
    result = []
    padding = (3 - len(data) % 3) % 3
    data = data + b"\x00" * padding

    for i in range(0, len(data), 3):
        n = (data[i] << 16) + (data[i + 1] << 8) + data[i + 2]
        result.append(SRUN_ALPHABET[(n >> 18) & 0x3F])
        result.append(SRUN_ALPHABET[(n >> 12) & 0x3F])
        result.append(SRUN_ALPHABET[(n >> 6) & 0x3F])
        result.append(SRUN_ALPHABET[n & 0x3F])

    # 替换填充字符
    if padding:
        result[-padding:] = ["="] * padding

    return "".join(result)


# ──────────────────────────────────────────────────
# 3. xEncode — XXTEA 变体加密
# ──────────────────────────────────────────────────


def _str_to_uint32_array(s: str) -> list:
    """字符串按小端序打包为 32 位整数数组"""
    b = s.encode("utf-8")
    # 补齐到 4 的倍数
    pad = (4 - len(b) % 4) % 4
    b = b + b"\x00" * pad
    v = []
    for i in range(0, len(b), 4):
        v.append(_bytes_to_long(b[i : i + 4]))
    return v


def _uint32_array_to_bytes(v: list) -> bytes:
    """32 位整数数组转回字节（小端序）"""
    return b"".join(_long_to_bytes(n) for n in v)


def srun_xencode(msg: str, key: str) -> bytes:
    """
    srun 的 xEncode 加密 —— XXTEA 变体（非标准 XXTEA）
    与 Portal.js 中 encode() 函数完全一致

    参数:
        msg: 待加密的 JSON 字符串
        key: 加密密钥（来自 get_challenge 的 token）
    """
    if not msg:
        return b""

    v = _str_to_uint32_array(msg)
    # srun 特有：在数组末尾追加原始消息长度（与 Portal.js 中 s(str, true) 一致）
    v.append(len(msg))

    k = _str_to_uint32_array(key)

    while len(k) < 4:
        k.append(0)

    n = len(v) - 1
    if n < 1:
        return _uint32_array_to_bytes(v)

    DELTA = 0x9E3779B9
    z = v[n]
    total = 0
    q = 6 + 52 // (n + 1)

    while q > 0:
        total = (total + DELTA) & 0xFFFFFFFF
        e = (total >> 2) & 3

        for p in range(n):
            y = v[p + 1]
            # srun 变体 XXTEA 公式（与 Portal.js 一致）
            mx = (
                ((z >> 5) ^ (y << 2))
                + (((y >> 3) ^ (z << 4)) ^ (total ^ y))
                + (k[(p & 3) ^ e] ^ z)
            ) & 0xFFFFFFFF
            v[p] = (v[p] + mx) & 0xFFFFFFFF
            z = v[p]

        y = v[0]
        mx = (
            ((z >> 5) ^ (y << 2))
            + (((y >> 3) ^ (z << 4)) ^ (total ^ y))
            + (k[((n) & 3) ^ e] ^ z)
        ) & 0xFFFFFFFF
        v[n] = (v[n] + mx) & 0xFFFFFFFF
        z = v[n]

        q -= 1

    return _uint32_array_to_bytes(v)


# ──────────────────────────────────────────────────
# 4. 加密参数计算
# ──────────────────────────────────────────────────


def calc_encrypted_password(token: str, password: str) -> str:
    """
    计算密码的 HMAC-MD5 哈希（裸 hex，不含 {MD5} 前缀）
    {MD5} 前缀只在发送请求时拼接
    """
    return hmac.new(
        token.encode("utf-8"), password.encode("utf-8"), hashlib.md5
    ).hexdigest()


def calc_info(username: str, password: str, ip: str, acid: str, token: str) -> str:
    """
    计算 info 字段
    格式: {SRBX1} + Base64( xEncode(JSON信息, token) )
    """
    info_obj = {
        "username": username,
        "password": password,
        "ip": ip,
        "acid": acid,
        "enc_ver": "srun_bx1",
    }
    json_str = json.dumps(info_obj, separators=(",", ":"), ensure_ascii=False)
    encoded = srun_xencode(json_str, token)
    b64 = srun_base64_encode(encoded)
    return "{SRBX1}" + b64


def calc_chksum(
    token: str,
    username: str,
    hmd5: str,
    acid: str,
    ip: str,
    n: str,
    type_: str,
    info: str,
) -> str:
    """
    计算 SHA1 校验和
    拼接顺序: token + username + token + hmd5 + token + acid + token + ip
              + token + n + token + type + token + info
    """
    chkstr = (
        token
        + username
        + token
        + hmd5
        + token
        + acid
        + token
        + ip
        + token
        + n
        + token
        + type_
        + token
        + info
    )
    return hashlib.sha1(chkstr.encode("utf-8")).hexdigest()


# ──────────────────────────────────────────────────
# 5. 网络工具
# ──────────────────────────────────────────────────


def get_local_ip(gateway: str = "192.168.112.30") -> str:
    """
    获取本机在校园网中的 IP 地址
    通过 UDP connect 到网关来触发路由表查询，获取对应网卡的源 IP
    路由表最长前缀匹配确保走正确的网卡（即使 WiFi 是默认路由）
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(3)
        # UDP connect 不发送数据，仅触发路由查找 + 绑定源地址
        s.connect((gateway, 80))
        ip = s.getsockname()[0]
        s.close()
        if ip != "127.0.0.1" and ip != "0.0.0.0":
            return ip
    except Exception:
        pass

    # fallback: 枚举所有网卡，逐一尝试连接网关来确定正确的 IP
    try:
        for if_name in socket.gethostbyname_ex(socket.gethostname())[2]:
            if if_name == "127.0.0.1":
                continue
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(2)
                s.bind((if_name, 0))
                s.connect((gateway, 80))
                ip = s.getsockname()[0]
                s.close()
                if ip != "127.0.0.1":
                    return ip
            except Exception:
                continue
    except Exception:
        pass

    return "0.0.0.0"


def check_reachable(host: str, port: int = 80, timeout: float = 3) -> bool:
    """检测 TCP 端口是否可达"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def _detect_os() -> str:
    """检测当前操作系统，返回 srun 格式的 OS 字符串"""
    if sys.platform == "win32":
        v = sys.getwindowsversion()
        return f"windows+{v.major}"
    elif sys.platform == "darwin":
        return "macos"
    else:
        return "linux"


def http_get(url: str, timeout: float = 8) -> str:
    """HTTP GET 请求，返回响应文本"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.read().decode("utf-8", errors="replace")
    except Exception as e:
        raise e


# ──────────────────────────────────────────────────
# 6. 登录核心逻辑
# ──────────────────────────────────────────────────


def do_login(cfg: dict) -> str:
    """
    执行一次 srun 登录
    返回: "ok" | "already" | "fail"
    """
    gateway = cfg["gateway"]
    username = cfg["username"]
    password = cfg["password"]
    acid = cfg["ac_id"]

    # 1) 获取本机 IP
    ip = get_local_ip(gateway)
    log(f"本机 IP: {ip}")

    # 2) 获取 challenge token
    cb = f"jQuery{int(time.time() * 1000)}_{int(time.time())}"
    ts = int(time.time() * 1000)
    challenge_url = (
        f"http://{gateway}/cgi-bin/get_challenge"
        f"?callback={cb}&username={username}&ip={ip}&_={ts}"
    )

    try:
        raw = http_get(challenge_url)
    except Exception as e:
        log(f"获取 challenge 失败: {e}")
        return "fail"

    # 解析 JSONP 或纯 JSON
    token = _parse_challenge(raw)
    if not token:
        log(f"解析 challenge 失败, 响应: {raw[:300]}")
        return "fail"
    log(f"获取 token: {token}")

    # 3) 计算加密参数
    hmd5 = calc_encrypted_password(token, password)
    # 发送的 password 字段需要 {MD5} 前缀；chksum 中的 hmd5 不加前缀
    enc_password = "{MD5}" + hmd5
    n = "200"
    type_ = "1"
    info = calc_info(username, password, ip, acid, token)
    chksum = calc_chksum(token, username, hmd5, acid, ip, n, type_, info)

    # 4) 发起登录请求
    ts2 = int(time.time() * 1000)
    login_url = (
        f"http://{gateway}/cgi-bin/srun_portal"
        f"?callback={cb}"
        f"&action=login"
        f"&username={urllib.parse.quote(username)}"
        f"&password={urllib.parse.quote(enc_password)}"
        f"&ac_id={acid}"
        f"&ip={ip}"
        f"&chksum={chksum}"
        f"&info={urllib.parse.quote(info)}"
        f"&n={n}"
        f"&type={type_}"
        f"&os={_detect_os()}"
        f"&name=windows"
        f"&double_stack=0"
        f"&_={ts2}"
    )

    try:
        raw = http_get(login_url)
    except Exception as e:
        log(f"登录请求失败: {e}")
        return "fail"

    # 5) 解析结果
    result = _parse_login_result(raw)
    if result == "ok":
        log("[OK] 登录成功")
    elif result == "already":
        log("[INFO] 已经在线，无需重复登录")
    else:
        log(f"[FAIL] 登录失败，响应: {raw[:400]}")
    return result


def _parse_challenge(raw: str) -> str:
    """从 get_challenge 的响应中提取 token"""
    # 尝试解析 JSONP: callback({...})
    m = re.search(r'"challenge"\s*:\s*"([^"]+)"', raw)
    if m:
        return m.group(1)
    # 尝试纯 JSON
    try:
        obj = json.loads(raw)
        return obj.get("challenge", "")
    except json.JSONDecodeError:
        pass
    return ""


def _parse_login_result(raw: str) -> str:
    """
    解析登录结果
    返回:
        "ok"        — 本次登录成功
        "already"   — 已经在线，无需重复登录
        "fail"      — 登录失败
    """
    # 已经在线
    if re.search(r"already\s*online", raw, re.IGNORECASE):
        return "already"
    if re.search(r"已在线|已经在线", raw):
        return "already"
    if re.search(r'"error"\s*:\s*"E0001"', raw):
        return "already"
    if re.search(r"acct_online", raw, re.IGNORECASE):
        return "already"
    # 本次登录成功 — 必须有明确的成功标志
    if re.search(r'"error"\s*:\s*"ok"', raw, re.IGNORECASE):
        return "ok"
    if re.search(r'"error_msg"\s*:\s*"ok"', raw, re.IGNORECASE):
        return "ok"
    if re.search(r'"suc_msg"\s*:\s*"login_ok"', raw, re.IGNORECASE):
        return "ok"
    if re.search(r'"error"\s*:\s*"0"', raw):
        return "ok"
    if re.search(r'"res"\s*:\s*"ok"', raw, re.IGNORECASE):
        return "ok"
    # 其余情况一律视为失败，避免将错误页误判为成功
    return "fail"


# ──────────────────────────────────────────────────
# 7. 主循环
# ──────────────────────────────────────────────────


def main():
    global _LOG_FILE

    cfg = load_config()

    # 初始化日志文件（超过 1MB 自动轮转）
    log_path = cfg.get("log_file", "")
    if log_path:
        try:
            # 轮转：超过 1MB 时备份旧日志
            max_size = 1 * 1024 * 1024
            if os.path.exists(log_path) and os.path.getsize(log_path) > max_size:
                backup = log_path + ".old"
                if os.path.exists(backup):
                    os.remove(backup)
                os.rename(log_path, backup)
            _LOG_FILE = open(log_path, "a", encoding="utf-8")
        except Exception:
            pass

    log("=" * 50)
    log("校园网 srun 自动登录脚本启动")
    log(f"网关: {cfg['gateway']} | 账号: {cfg['username']}")
    log(f"短间隔: {cfg['check_interval']}s | 长间隔: {cfg['online_interval']}s")

    short_interval = cfg["check_interval"]
    long_interval = cfg.get("online_interval", 300)
    gateway = cfg["gateway"]

    # 跟踪在线状态，用于动态调整检查间隔
    is_online = False       # 当前是否认为已在线
    consecutive_failures = 0

    while True:
        try:
            # 1. 检查网关是否可达（判断物理连接）
            gw_ok = check_reachable(gateway, port=80, timeout=3)

            if not gw_ok:
                # 网关不可达 → 可能没插网线
                if is_online or consecutive_failures == 0:
                    log("[WARN] 网关不可达，等待校园网连接...")
                is_online = False
                consecutive_failures = 0
                time.sleep(short_interval)
                continue

            # 2. 网关可达 → 尝试认证
            #    （WiFi 优先模式下外网始终通，所以不依赖外网检测，直接尝试登录）
            result = do_login(cfg)

            if result in ("ok", "already"):
                if not is_online:
                    log(f"[ONLINE] 校园网认证正常（{long_interval}s 后再检）")
                is_online = True
                consecutive_failures = 0
                # 已在线时用长间隔，减少不必要的认证请求
                time.sleep(long_interval)
            else:
                # "fail"
                is_online = False
                consecutive_failures += 1
                backoff = min(consecutive_failures * short_interval, 300)
                log(f"认证失败，{backoff}s 后重试 (连续失败 {consecutive_failures} 次)")
                time.sleep(backoff)

        except KeyboardInterrupt:
            log("收到退出信号，脚本停止")
            break
        except Exception as e:
            log(f"异常: {e}")
            time.sleep(short_interval)

    if _LOG_FILE:
        _LOG_FILE.close()


if __name__ == "__main__":
    main()
