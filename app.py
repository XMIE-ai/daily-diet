"""每日饮食管理 · 用一张照片估算热量和营养素（Streamlit 版）。

运行：streamlit run app.py
"""
from __future__ import annotations

import os
from datetime import date

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from analyzer import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    NUTRIENT_LABELS,
    analyze_image,
)

load_dotenv()

st.set_page_config(page_title="每日饮食管理 · AI 热量估算", page_icon="🥗", layout="wide")

MEALS = ["早餐", "午餐", "晚餐", "加餐"]
LABELS = list(NUTRIENT_LABELS.values())


def secret(name: str, default: str = "") -> str:
    """优先读 Streamlit secrets（云端部署用），其次读环境变量（本地 .env 用）。"""
    try:
        value = st.secrets[name]
        if value:
            return str(value)
    except Exception:
        pass
    return os.getenv(name, default) or ""


if "records" not in st.session_state:
    st.session_state.records = []
if "last_result" not in st.session_state:
    st.session_state.last_result = None


# ----------------------------- 侧边栏：模型设置 + 今日汇总 -----------------------------
with st.sidebar:
    st.header("⚙️ 模型设置")
    api_key = st.text_input(
        "API Key",
        value=secret("LLM_API_KEY"),
        type="password",
        help="本地写在 .env 里，云端写在 Streamlit secrets 里。这里也可以临时填。",
    )
    base_url = st.text_input("Base URL", value=secret("LLM_BASE_URL", DEFAULT_BASE_URL))
    model = st.text_input("模型", value=secret("LLM_MODEL", DEFAULT_MODEL))
    st.caption("默认用阿里云百炼的通义千问 Qwen-VL。换模型只改上面两行就行。")

    st.divider()
    st.header("📅 今日汇总")
    if st.session_state.records:
        today_df = pd.DataFrame(st.session_state.records)
        today_df = today_df[today_df["日期"] == date.today().isoformat()]
        if today_df.empty:
            st.caption("今天还没有记录。")
        else:
            st.metric("热量", f"{today_df[LABELS[0]].sum():.0f} kcal")
            st.metric("蛋白质", f"{today_df[LABELS[1]].sum():.1f} g")
            st.metric("碳水", f"{today_df[LABELS[2]].sum():.1f} g")
            st.metric("脂肪", f"{today_df[LABELS[3]].sum():.1f} g")
    else:
        st.caption("今天还没有记录。")


# ----------------------------- 主区：上传与拍照 -----------------------------
st.title("🥗 每日饮食管理")
st.caption("上传一张照片 → 大模型估算热量、蛋白质、碳水、脂肪 → 存进当天记录。")

left, right = st.columns([1, 1])

with left:
    uploaded = st.file_uploader("上传食物照片", type=["jpg", "jpeg", "png", "webp"])
    camera = st.camera_input("或者直接拍一张（手机上好用）")
    meal = st.selectbox("这是哪一餐", MEALS, index=1)
    extra = st.text_input(
        "补充信息（可选）",
        placeholder="例如：米饭是小碗 / 这盘是两人份 / 用橄榄油煎的",
    )

image_bytes = None
if uploaded is not None:
    image_bytes = uploaded.getvalue()
elif camera is not None:
    image_bytes = camera.getvalue()

with right:
    if image_bytes:
        st.image(image_bytes, caption="待分析的照片", use_container_width=True)
    else:
        st.info("在左边上传或拍一张食物照片。\n\n小提示：从斜上方拍、让所有菜都进画面、旁边放个筷子或手当参照，估算会准不少。")

run = st.button("🔍 开始分析", type="primary", use_container_width=True)

if run:
    if not image_bytes:
        st.warning("先上传或拍一张照片。")
    elif not api_key:
        st.error("还没有 API Key，去左边侧边栏填一下。")
    else:
        with st.spinner("大模型正在看图估算，大概要十几秒……"):
            try:
                st.session_state.last_result = analyze_image(
                    image_bytes,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    extra_info=extra,
                )
            except Exception as exc:  # noqa: BLE001 - 出错就原样告诉用户
                st.session_state.last_result = None
                st.error(f"分析失败：{exc}")


# ----------------------------- 分析结果 -----------------------------
result = st.session_state.last_result
if result:
    st.divider()
    st.subheader("分析结果")

    total = result["total"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("热量", f"{total['calories']:.0f} kcal")
    c2.metric("蛋白质", f"{total['protein']:.1f} g")
    c3.metric("碳水", f"{total['carbs']:.1f} g")
    c4.metric("脂肪", f"{total['fat']:.1f} g")

    st.caption(f"估算置信度：{result['confidence']}　|　模型：{result.get('model', '')}")

    if result["notes"]:
        st.info(f"营养师备注：{result['notes']}")

    if result["dishes"]:
        table = pd.DataFrame(result["dishes"])
        table = table.rename(columns={"name": "食物", "portion": "分量", **NUTRIENT_LABELS})
        st.dataframe(table, use_container_width=True, hide_index=True)

        if st.button("✅ 保存到今日记录", type="primary"):
            today = date.today().isoformat()
            for dish in result["dishes"]:
                row = {"日期": today, "餐次": meal, "食物": dish["name"], "分量": dish["portion"]}
                row.update({label: dish[key] for key, label in NUTRIENT_LABELS.items()})
                st.session_state.records.append(row)
            st.success(f"已保存 {len(result['dishes'])} 条记录。")
            st.rerun()
    else:
        st.warning("模型没识别出食物，换张更清楚的照片试试。")


# ----------------------------- 记录与导出 -----------------------------
st.divider()
st.subheader("历史记录")

if not st.session_state.records:
    st.caption("还没有记录。分析完点上面的「保存到今日记录」。")
else:
    df = pd.DataFrame(st.session_state.records)
    st.dataframe(df, use_container_width=True, hide_index=True)

    col_a, col_b = st.columns(2)
    col_a.download_button(
        "⬇️ 导出全部记录 (CSV)",
        df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"diet-records-{date.today().isoformat()}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    if col_b.button("🗑️ 清空记录", use_container_width=True):
        st.session_state.records = []
        st.rerun()

    st.caption(
        "注意：记录存在浏览器会话里，刷新页面或重启服务会清空。"
        "想要长期保存，导出 CSV，或者后面接一个数据库（Supabase 免费版就够）。"
    )
