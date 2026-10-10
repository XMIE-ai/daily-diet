"""诊断脚本：定位「Connection error」到底是网络问题还是配置问题。

会做四件事：
  1. 读 .env，检查三个配置项是否齐全（key 只显示前缀，不打印完整内容）
  2. 测试能不能连上接口域名（先不管 key 对不对）
  3. 带上 key 请求一次，看鉴权是否通过
  4. 给出结论

用法： python check_api.py
"""
from __future__ import annotations

import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent / ".env"
DEFAULT_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def load_env(path: Path) -> dict:
    cfg = {}
    if not path.exists():
        return cfg
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        cfg[key.strip()] = val.strip().strip('"').strip("'")
    return cfg


def http_get(url: str, api_key: str | None = None, timeout: int = 25):
    headers = {"User-Agent": "diet-app-diagnose"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(400).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(400).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


print("=" * 64)
print("1. 读取 .env")
print("=" * 64)
print(f"  路径: {ENV_PATH}")
print(f"  存在: {ENV_PATH.exists()}")

cfg = load_env(ENV_PATH)
api_key = cfg.get("LLM_API_KEY", "").strip()
base_url = (cfg.get("LLM_BASE_URL") or DEFAULT_BASE).strip().rstrip("/")
model = cfg.get("LLM_MODEL", "").strip()

if not ENV_PATH.exists():
    print("\n  ✗ .env 不存在，请先复制 .env.example 为 .env")
    sys.exit(1)

if api_key:
    print(f"  LLM_API_KEY : {api_key[:12]}...（共 {len(api_key)} 字符）")
    print(f"                key 类型前缀: {api_key.split('-')[1] if '-' in api_key else '未知'}")
else:
    print("  LLM_API_KEY : ✗ 空的！")
print(f"  LLM_BASE_URL: {base_url}")
print(f"  LLM_MODEL   : {model or '（空）'}")

if not api_key:
    print("\n  ✗ key 是空的，先跑 python set_key.py 填进去")
    sys.exit(1)

host = urllib.parse.urlparse(base_url).hostname or ""
port = urllib.parse.urlparse(base_url).port or 443

print()
print("=" * 64)
print("2. 域名解析与 TCP 连通性（先不管 key）")
print("=" * 64)
try:
    ip = socket.gethostbyname(host)
    print(f"  DNS 解析    : ✓ {host} -> {ip}")
except Exception as exc:  # noqa: BLE001
    print(f"  DNS 解析    : ✗ 失败 {type(exc).__name__}: {exc}")

try:
    with socket.create_connection((host, port), timeout=15):
        print(f"  TCP 连接    : ✓ {host}:{port} 可连接")
except Exception as exc:  # noqa: BLE001
    print(f"  TCP 连接    : ✗ 失败 {type(exc).__name__}: {exc}")
    print("                → 这是网络问题，和 key 无关。检查代理/防火墙/网络")

print()
print("=" * 64)
print("3. HTTPS 请求测试")
print("=" * 64)
models_url = f"{base_url}/models"

status, body = http_get(models_url)
print(f"  不带 key 请求 {models_url}")
print(f"    -> HTTP {status}")
if status == 401:
    print("       ✓ 能连上（401 是正常的，因为没带 key）")
elif status == 200:
    print("       ✓ 能连上")
elif status is None:
    print(f"       ✗ 连不上: {body}")
    print("       → 网络层失败，这就是 Connection error 的来源")
else:
    print(f"       响应: {body[:200]}")

status2, body2 = http_get(models_url, api_key=api_key)
print(f"\n  带上 key 请求")
print(f"    -> HTTP {status2}")
if status2 == 200:
    print("       ✓✓ Key 有效，鉴权通过")
elif status2 == 401:
    print(f"       ✗ Key 无效或已失效")
    print(f"       响应: {body2[:300]}")
elif status2 == 403:
    print(f"       ✗ 被拒绝（可能是地域不匹配）")
    print(f"       响应: {body2[:300]}")
elif status2 is None:
    print(f"       ✗ 连接失败: {body2}")
else:
    print(f"       响应: {body2[:300]}")

print()
print("=" * 64)
print("4. 实际调用一次模型（最终验证）")
print("=" * 64)
if not model:
    print("  LLM_MODEL 是空的，跳过")
else:
    import json as _json

    payload = _json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "回复两个字：可用"}],
        "max_tokens": 10,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "diet-app-diagnose",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = _json.load(resp)
            text = data["choices"][0]["message"]["content"]
            print(f"  ✓✓ 模型调用成功，返回: {text!r}")
            print(f"     实际使用的模型: {data.get('model')}")
    except urllib.error.HTTPError as exc:
        print(f"  ✗ HTTP {exc.code}: {exc.read(400).decode('utf-8', 'replace')[:300]}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ 失败 {type(exc).__name__}: {exc}")

print()
print("=" * 64)
print("结论")
print("=" * 64)
print("  如果第 2 步 TCP 或第 3 步不带 key 就失败 → 网络问题")
print("  如果第 3 步不带 key 成功、带 key 返回 401 → key 问题")
print("  如果全绿 → 配置没问题，去重启应用（旧的环境变量会被缓存）")
