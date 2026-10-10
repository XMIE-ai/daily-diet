"""调用多模态大模型，从一张食物照片估算营养成分。

默认对接阿里云百炼（通义千问 Qwen-VL）的 OpenAI 兼容接口。
想换成智谱 GLM-4V、OpenAI GPT-4o、硅基流动等，只需要改 LLM_BASE_URL 和 LLM_MODEL。
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import time
from typing import Any, Dict, List

import httpx
from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError
from PIL import Image

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# 视觉理解模型：qwen3-vl-plus 精度和价格比较平衡；
# 想省钱可以换 qwen3-vl-flash，想更准可以换 qwen-vl-max。
# 完整列表：https://help.aliyun.com/zh/model-studio/model-list-visual-understanding/
DEFAULT_MODEL = "qwen3-vl-plus"

# 四项营养素的字段名，顺序固定，UI 和合计都依赖它
NUTRIENTS = ("calories", "protein", "carbs", "fat")
NUTRIENT_LABELS = {
    "calories": "热量(kcal)",
    "protein": "蛋白质(g)",
    "carbs": "碳水(g)",
    "fat": "脂肪(g)",
}

SYSTEM_PROMPT = """你是一位有十年经验的临床营养师，擅长通过照片估算食物分量和营养成分。

请仔细观察照片，完成这几件事：
1. 识别出照片里所有能吃的东西（主食、菜、肉、汤、饮料、调料都要算进去）
2. 估计每一道的分量（用克或毫升，例如「约200g」「约250ml」）
3. 估算每一道的热量(kcal)、蛋白质(g)、碳水(g)、脂肪(g)
4. 给出总热量和总营养素

估算要求：
- 参考中国食物成分表里的常见数值，不要凭感觉乱给
- 中式家常菜要考虑烹饪用油，油的热量必须计入
- 看不清分量时按「中份」估，并在 notes 里写明你的假设
- 照片里如果有多人份的菜，按画面中的实际分量估，别当成一整份
- 只返回 JSON，不要任何解释文字，不要 markdown 代码块

严格按这个结构返回：
{
  "dishes": [
    {"name": "食物名称", "portion": "约200g", "calories": 232, "protein": 4.8, "carbs": 51.6, "fat": 0.6}
  ],
  "total": {"calories": 232, "protein": 4.8, "carbs": 51.6, "fat": 0.6},
  "confidence": "高/中/低",
  "notes": "说明你的估算假设和不确定的地方"
}"""


def _env_flag(name: str, default: bool = False) -> bool:
    """把环境变量读成布尔值。认 1/true/yes/on。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def get_client(
    api_key: str | None = None,
    base_url: str | None = None,
    *,
    timeout: float = 90.0,
    use_proxy: bool | None = None,
) -> OpenAI:
    """创建模型客户端。key 的优先级：参数 > 环境变量。"""
    key = (
        api_key
        or os.getenv("LLM_API_KEY")
        or os.getenv("DASHSCOPE_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    ).strip()
    if not key:
        raise RuntimeError(
            "没有找到 API Key。把 .env.example 复制成 .env 并填入 LLM_API_KEY，"
            "或者在页面左侧栏里直接填写。"
        )
    url = (base_url or os.getenv("LLM_BASE_URL") or DEFAULT_BASE_URL).strip()

    if use_proxy is None:
        use_proxy = _env_flag("LLM_USE_PROXY", default=False)

    # httpx 默认会读取系统代理（Windows 上包括注册表里的代理设置）。
    # 国内访问百炼如果被导到境外代理，TLS 会被中间层掐断，报
    # "Connection error." 或 "UNEXPECTED_EOF_WHILE_READING"。
    # trust_env=False 让它忽略系统代理和代理环境变量——除非显式要求走代理。
    http_client = httpx.Client(trust_env=use_proxy, timeout=timeout)

    return OpenAI(api_key=key, base_url=url, http_client=http_client, max_retries=0)


def encode_image(image_bytes: bytes, max_side: int = 1024, quality: int = 85) -> str:
    """把图片压到长边不超过 max_side，再转成 data URL。

    原图动辄好几 MB，直接发出去又慢又费 token，压一下基本不影响估算精度。
    """
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")

    width, height = img.size
    scale = max_side / max(width, height)
    if scale < 1:
        img = img.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.LANCZOS,
        )

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _coerce_number(value: Any) -> float:
    """把模型返回的各种形式洗成数字。

    实测它会返回 232、"约560"、"26"、"≈18.5"、"560 kcal"、None 这些花样，
    所以不能直接 float()，先从字符串里抠出第一个数字。
    """
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return round(float(value), 1)
    if isinstance(value, str):
        match = _NUMBER_RE.search(value)
        if match:
            return round(float(match.group()), 1)
    return 0.0


def _extract_json(text: str) -> Dict[str, Any]:
    """从模型回复里抠出 JSON，容错掉 markdown 代码块和多余的客套话。"""
    cleaned = text.replace("```json", "").replace("```", "").strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"模型没有返回 JSON，原始内容是：{text[:300]}")
    return json.loads(cleaned[start : end + 1])


def parse_result(raw: str) -> Dict[str, Any]:
    """把模型返回的原始文本变成干净的字典，并重算合计。"""
    data = _extract_json(raw)

    dishes: List[Dict[str, Any]] = []
    for row in data.get("dishes") or []:
        if not isinstance(row, dict):
            continue
        dish: Dict[str, Any] = {
            "name": str(row.get("name") or "未知食物").strip(),
            "portion": str(row.get("portion") or "").strip(),
        }
        for key in NUTRIENTS:
            dish[key] = _coerce_number(row.get(key))
        dishes.append(dish)

    # 合计自己算，不用模型给的，保证和明细对得上
    total = {key: round(sum(dish[key] for dish in dishes), 1) for key in NUTRIENTS}

    return {
        "dishes": dishes,
        "total": total,
        "confidence": str(data.get("confidence") or "未知").strip(),
        "notes": str(data.get("notes") or "").strip(),
    }


# 这些错误是「可能重试就好了」的类型：连不上、超时、被限流
RETRYABLE_ERRORS = (APIConnectionError, APITimeoutError, RateLimitError, httpx.TransportError)


def analyze_image(
    image_bytes: bytes,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    extra_info: str = "",
    timeout: float = 90.0,
    retries: int = 3,
) -> Dict[str, Any]:
    """核心函数：一张图片进去，结构化营养成分出来。

    连接类错误会自动重试（1s / 2s 退避）。重试用完还失败，就抛出人话的错误说明。
    """
    client = get_client(api_key, base_url, timeout=timeout)
    model_name = (model or os.getenv("LLM_MODEL") or DEFAULT_MODEL).strip()

    prompt = "请分析这张照片里的食物，估算分量和营养成分。"
    if extra_info.strip():
        prompt += f"\n补充信息（以此为准，优先于你的目测）：{extra_info.strip()}"

    payload = encode_image(image_bytes)
    last_error: Exception | None = None

    for attempt in range(1, max(1, retries) + 1):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": payload}},
                            {"type": "text", "text": prompt},
                        ],
                    },
                ],
                temperature=0.2,
                timeout=timeout,
            )
            break
        except RETRYABLE_ERRORS as exc:
            last_error = exc
            if attempt >= max(1, retries):
                raise RuntimeError(
                    f"连不上模型服务（已重试 {retries} 次）：{exc}\n"
                    "常见原因：\n"
                    "  1. 系统代理 / VPN / 网络加速器拦截了请求"
                    "（可运行 python check_network.py 确认）\n"
                    "  2. 网络本身不通\n"
                    "  3. LLM_BASE_URL 填错了"
                ) from exc
            time.sleep(2 ** (attempt - 1))  # 1s, 2s, 4s ...
    else:  # pragma: no cover - 循环必然 break 或 raise
        raise RuntimeError(f"请求失败：{last_error}")

    raw = (response.choices[0].message.content or "").strip()
    result = parse_result(raw)
    result["model"] = model_name
    result["raw"] = raw
    result["attempts"] = attempt
    return result
