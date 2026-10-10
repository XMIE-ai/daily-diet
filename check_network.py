"""网络诊断：判断 dashscope 的 HTTPS 连接是被代理掐断的，还是直连就断。

四项测试，逐层剥离：
  1. 打印所有代理配置（环境变量 + Windows 系统设置）
  2. 直连做一次纯 TLS 握手（完全绕过代理）—— 检验握手本身是否可行
  3. 带 key 请求，但显式禁用代理
  4. 带 key 请求，走系统代理设置
  5. 不带 key 请求 —— 这是最关键的对照

用法： python check_network.py
"""
from __future__ import annotations

import os
import socket
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent / ".env"
HOST = "dashscope.aliyuncs.com"
PATH = "/compatible-mode/v1/models"
URL = f"https://{HOST}{PATH}"


def load_key() -> str:
    if not ENV_PATH.exists():
        return ""
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("LLM_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def describe(exc: BaseException) -> str:
    reason = exc
    while getattr(reason, "reason", None) is not None:
        reason = reason.reason  # type: ignore[assignment]
    return f"{type(reason).__name__}: {reason}"


key = load_key()

print("=" * 66)
print("1. 代理配置")
print("=" * 66)
found = False
for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
             "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
    val = os.environ.get(name)
    if val:
        print(f"  环境变量 {name} = {val}")
        found = True
if not found:
    print("  环境变量: 没有设置任何代理")

try:
    sys_proxies = urllib.request.getproxies()
    print(f"  Windows 系统代理设置: {sys_proxies if sys_proxies else '（空）'}")
    if sys_proxies:
        print("  ⚠️ 系统配置了代理 —— 这很可能就是问题所在")
except Exception as exc:  # noqa: BLE001
    print(f"  读取系统代理失败: {exc}")

print()
print("=" * 66)
print("2. 纯 TLS 握手（完全绕过代理，验证握手本身能不能成）")
print("=" * 66)
try:
    ctx = ssl.create_default_context()
    with socket.create_connection((HOST, 443), timeout=15) as sock:
        with ctx.wrap_socket(sock, server_hostname=HOST) as tls:
            print("  ✓ TLS 握手成功")
            print(f"    协议版本: {tls.version()}")
            print(f"    加密套件: {tls.cipher()[0]}")
            print("    → 说明直连的 TLS 是通的，问题在代理或请求层")
except Exception as exc:  # noqa: BLE001
    print(f"  ✗ TLS 握手失败: {describe(exc)}")
    print("    → 直连就被掐断，是最底层的网络拦截")

print()
print("=" * 66)
print("3. 带 key 请求，显式禁用代理")
print("=" * 66)
direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
req = urllib.request.Request(URL, headers={
    "Authorization": f"Bearer {key}",
    "User-Agent": "net-diagnose",
})
try:
    with direct.open(req, timeout=25) as resp:
        print(f"  ✓ HTTP {resp.status}")
except urllib.error.HTTPError as exc:
    print(f"  HTTP {exc.code}")
    if exc.code == 401:
        print("    ✓ 连接正常！401 只说明 key 没通过鉴权")
    elif exc.code == 403:
        print("    ⚠️ 403 —— 可能是地域或权限问题")
    print(f"    响应: {exc.read(200).decode('utf-8', 'replace')}")
except Exception as exc:  # noqa: BLE001
    print(f"  ✗ 失败: {describe(exc)}")
    print("    → 不走代理也失败，说明不是代理造成的")

print()
print("=" * 66)
print("4. 带 key 请求，走系统代理设置")
print("=" * 66)
req2 = urllib.request.Request(URL, headers={
    "Authorization": f"Bearer {key}",
    "User-Agent": "net-diagnose",
})
try:
    with urllib.request.urlopen(req2, timeout=25) as resp:
        print(f"  ✓ HTTP {resp.status}")
except urllib.error.HTTPError as exc:
    print(f"  HTTP {exc.code}")
except Exception as exc:  # noqa: BLE001
    print(f"  ✗ 失败: {describe(exc)}")

print()
print("=" * 66)
print("5. 不带 key 请求（最关键的对照）")
print("=" * 66)
req3 = urllib.request.Request(URL, headers={"User-Agent": "net-diagnose"})
try:
    with urllib.request.urlopen(req3, timeout=25) as resp:
        print(f"  ✓ HTTP {resp.status}")
except urllib.error.HTTPError as exc:
    print(f"  HTTP {exc.code}")
    if exc.code == 401:
        print("    ✓✓ 关键结论：连接完全正常！401 是「没带钥匙」的正常回应")
        print("        → 所以问题不在网络，而在 key 或请求内容")
except Exception as exc:  # noqa: BLE001
    print(f"  ✗ 失败: {describe(exc)}")
    print("    → 关键结论：不带 key 也连不上，问题是网络层，和 key 无关")

print()
print("=" * 66)
print("把以上全部输出发给我")
print("=" * 66)
