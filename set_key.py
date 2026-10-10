"""安全地更新 .env 里的 API Key。

用法：
    python set_key.py

为什么要用这个而不是记事本：
  1. 输入的 key 不会出现在命令行历史里（不是作为参数传的）
  2. 不会像记事本「另存为」那样把文件存成 .env.txt
  3. 会自动校验格式（sk- 开头、没有多余的空格或引号），填错了当场告诉你
  4. 只改 LLM_API_KEY 这一行，其他行原样不动
"""
from __future__ import annotations

import getpass
import re
import sys
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent / ".env"


def main() -> int:
    if not ENV_PATH.exists():
        print(f"✗ 找不到 {ENV_PATH}")
        print("  请先把 .env.example 复制成 .env")
        return 1

    print(f"要更新的文件：{ENV_PATH}")
    print()
    print("现在粘贴你的新 API Key，然后按回车。")
    print("（提示：粘贴时屏幕上不会显示任何字符，这是正常的，不是没粘上）")
    print()

    raw = getpass.getpass("新 API Key: ").strip()

    if not raw:
        print("\n✗ 没有输入任何内容，已取消。")
        return 1

    if not raw.startswith("sk-"):
        print(f"\n✗ 这看起来不像 API Key。它应该以 'sk-' 开头，你输入的是 '{raw[:8]}...'")
        return 1

    if any(ch in raw for ch in " \t\"'") or "\n" in raw:
        print("\n✗ Key 里含有空格、引号或换行。请重新复制，注意不要带上多余字符。")
        return 1

    if len(raw) < 30:
        print(f"\n✗ Key 太短了（只有 {len(raw)} 个字符），可能没复制完整。已取消。")
        return 1

    text = ENV_PATH.read_text(encoding="utf-8")
    new_text, count = re.subn(r"(?m)^LLM_API_KEY=.*$", f"LLM_API_KEY={raw}", text)

    if count == 0:
        new_text = text.rstrip("\n") + f"\nLLM_API_KEY={raw}\n"
        count = 1

    ENV_PATH.write_text(new_text, encoding="utf-8")

    masked = f"{raw[:8]}...{raw[-4:]}"
    print(f"\n✓ 已更新 {count} 处")
    print(f"  当前 Key：{masked}（共 {len(raw)} 个字符）")
    print()
    print("下一步：双击 start.bat，上传一张照片点「开始分析」，确认新 Key 能用。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
