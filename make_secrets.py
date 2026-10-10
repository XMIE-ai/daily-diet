"""从 .env 生成 Streamlit Cloud Secrets 需要的内容，并复制到剪贴板。

为什么要用它：
  Streamlit Secrets 用的是 TOML 格式（值要加引号），和 .env 不一样。
  手动把 key 从 .env 挪到网页上，很容易粘出换行或漏掉引号——
  而 key 一旦断成两行，TOML 就会解析失败。

用法：
    python make_secrets.py

然后再到 Streamlit 的 Secrets 框里按 Ctrl+V。

⚠️ 注意：这个脚本会把完整 key 打印到屏幕上。别把它的输出截图发人。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent / ".env"


def load_env(path: Path) -> dict:
    cfg: dict[str, str] = {}
    if not path.exists():
        return cfg
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        cfg[key.strip()] = val.strip().strip('"').strip("'")
    return cfg


def copy_to_clipboard(text: str) -> bool:
    """Windows 上把文本放进剪贴板。clip 需要 UTF-16LE 编码才不会乱码。"""
    try:
        subprocess.run(
            "clip",
            input=text.encode("utf-16-le"),
            shell=True,
            check=True,
            timeout=10,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    if not ENV_PATH.exists():
        print(f"✗ 找不到 {ENV_PATH}")
        print("  请先把 .env.example 复制成 .env，并跑一次 python set_key.py")
        return 1

    cfg = load_env(ENV_PATH)
    key = cfg.get("LLM_API_KEY", "").strip()
    base = cfg.get("LLM_BASE_URL", "").strip()
    model = cfg.get("LLM_MODEL", "").strip()

    if not key:
        print("✗ .env 里的 LLM_API_KEY 是空的，先跑 python set_key.py")
        return 1
    if not key.startswith("sk-"):
        print(f"✗ LLM_API_KEY 看起来不对（应以 sk- 开头，当前是 {key[:8]}...）")
        return 1
    if "\n" in key or "\r" in key or " " in key:
        print("✗ LLM_API_KEY 里含有换行或空格，先跑 python set_key.py 重新写一遍")
        return 1
    if not base:
        base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    if not model:
        model = "qwen3-vl-plus"

    toml = (
        f'LLM_API_KEY = "{key}"\n'
        f'LLM_BASE_URL = "{base}"\n'
        f'LLM_MODEL = "{model}"\n'
    )

    print("=" * 62)
    print("下面这段就是要粘进 Streamlit Secrets 的内容：")
    print("=" * 62)
    print()
    print(toml)
    print("=" * 62)
    print(f"自检：key 共 {len(key)} 个字符，不含换行 = {chr(10) not in key and chr(13) not in key}")
    print()

    if copy_to_clipboard(toml):
        print("✓ 已复制到剪贴板")
        print("  → 现在去 Streamlit 的 Secrets 框里 Ctrl+V 粘贴即可")
    else:
        print("（自动复制失败，请手动选上面那段复制）")

    print()
    print("⚠️ 提示：这个输出里有你的完整 key，别截图发给别人。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
