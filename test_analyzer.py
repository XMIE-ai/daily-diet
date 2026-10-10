"""analyzer.py 的单元测试。

跑法（二选一，都不需要联网、不需要 API Key）：
    pytest -q
    python test_analyzer.py
"""
from __future__ import annotations

import base64
import io
import json
import sys
import types
from pathlib import Path

# --- 用一个假的 openai 顶掉真依赖，这样没装 openai 也能测解析逻辑 ---
_stub = types.ModuleType("openai")


class _FakeOpenAI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


_stub.OpenAI = _FakeOpenAI
sys.modules.setdefault("openai", _stub)
# -------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyzer  # noqa: E402


def test_clean_json():
    raw = json.dumps(
        {
            "dishes": [
                {"name": "米饭", "portion": "约200g", "calories": 232, "protein": 4.8, "carbs": 51.6, "fat": 0.6},
                {"name": "红烧肉", "portion": "约120g", "calories": 468, "protein": 12.1, "carbs": 6.2, "fat": 44.3},
            ],
            # 故意给一个错的 total，验证我们会重算
            "total": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0},
            "confidence": "中",
            "notes": "按中份估算",
        }
    )
    result = analyzer.parse_result(raw)

    assert len(result["dishes"]) == 2
    assert result["total"]["calories"] == 700.0
    assert result["confidence"] == "中"
    assert result["notes"] == "按中份估算"


def test_markdown_fence_and_chatter():
    """模型经常套 markdown 代码块，前后还加客套话。"""
    raw = """好的，我来帮您分析这张照片。

```json
{
  "dishes": [
    {"name": "牛肉面", "portion": "约450g", "calories": "约560", "protein": "26", "carbs": 78, "fat": "18.5"}
  ],
  "confidence": "低",
  "notes": "汤没喝完"
}
```
希望有帮助！"""
    result = analyzer.parse_result(raw)

    assert len(result["dishes"]) == 1
    assert result["dishes"][0]["calories"] == 560.0
    assert result["total"]["carbs"] == 78.0


def test_coerce_number_handles_model_formats():
    cases = [
        (232, 232.0),
        (18.55, 18.6),
        ("560", 560.0),
        ("约560", 560.0),
        ("560 kcal", 560.0),
        ("≈18.5", 18.5),
        ("约 230 千卡", 230.0),
        ("", 0.0),
        (None, 0.0),
        (True, 0.0),  # bool 是 int 的子类，必须挡住
    ]
    for raw_value, expected in cases:
        assert analyzer._coerce_number(raw_value) == expected, f"{raw_value!r} -> {analyzer._coerce_number(raw_value)!r}"


def test_dirty_rows_do_not_crash():
    raw = json.dumps({"dishes": [{"name": "未知", "calories": None}, "这不是字典", {}], "confidence": None})
    result = analyzer.parse_result(raw)

    assert isinstance(result["dishes"], list)
    assert result["total"]["calories"] == 0.0
    assert result["confidence"] == "未知"


def test_non_json_raises():
    try:
        analyzer.parse_result("这张照片里有米饭和青菜。")
    except ValueError:
        return
    raise AssertionError("模型没返回 JSON 时应该抛 ValueError")


def test_encode_image_compresses():
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (3000, 2000), (200, 120, 60)).save(buffer, format="PNG")
    original = buffer.getvalue()

    data_url = analyzer.encode_image(original)
    assert data_url.startswith("data:image/jpeg;base64,")

    decoded = base64.b64decode(data_url.split(",", 1)[1])
    size = Image.open(io.BytesIO(decoded)).size
    assert max(size) == 1024
    assert len(decoded) < len(original)


def _main() -> int:
    tests = [(name, obj) for name, obj in sorted(globals().items()) if name.startswith("test_") and callable(obj)]
    failed = []
    for name, func in tests:
        try:
            func()
            print(f"[PASS] {name}")
        except AssertionError as exc:
            failed.append(name)
            print(f"[FAIL] {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            print(f"[ERROR] {name}: {type(exc).__name__}: {exc}")

    print()
    if failed:
        print(f"{len(failed)}/{len(tests)} 个测试失败: {failed}")
        return 1
    print(f"全部通过（{len(tests)} 个测试）")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
