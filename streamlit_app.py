# streamlit_app.py
from __future__ import annotations

import streamlit as st

from src.moysklad import MoySkladClient, HttpError


st.set_page_config(page_title="Сканер маркировки → МойСклад", layout="centered")

st.title("Сканер маркировки (DataMatrix) → МойСклад (customerorder.description)")

# --- Настройки ---
with st.sidebar:
    st.header("Настройки")

    ms_token = st.text_input("MS_TOKEN", type="password", value=st.secrets.get("MS_TOKEN", ""))
    st.caption("Токен МойСклад (Bearer)")

    # ВАЖНО: здесь мы просим именно ID доп.поля, а не имя
    qr_attr_id = st.text_input(
        "MS_ORDER_QR_ATTR_ID (ID доп.поля ШККОД128)",
        value=st.secrets.get("MS_ORDER_QR_ATTR_ID", "687d964c-5a22-11ee-0a80-032800443111"),
    )
    qr_attr_name = st.text_input(
        "MS_ORDER_QR_ATTR_NAME (для bruteforce fallback)",
        value=st.secrets.get("MS_ORDER_QR_ATTR_NAME", "ШККОД128"),
    )

    st.divider()
    st.write("Подсказка: ID можно взять прямо из JSON заказа (ты уже прислал — он известен).")


if not ms_token:
    st.warning("Укажи MS_TOKEN в сайдбаре.")
    st.stop()

ms = MoySkladClient(token=ms_token)

st.subheader("1) Сканируй QR/Code128 (например `*CtzwYRSH`)")
scan = st.text_input("Скан", value="", placeholder="*CtzwYRSH")

debug = st.checkbox("Показать debug", value=True)

if debug and scan:
    st.code(f"DEBUG scan repr: {scan!r}")

st.subheader("2) Найти заказ в МойСклад по ШККОД128 и записать коды в description")

cis_block = st.text_area(
    "Список DataMatrix (каждый код с новой строки)",
    height=200,
    placeholder="010...21...\n010...21...\n...",
)

btn = st.button("Найти заказ и записать [CIS] блок", type="primary", disabled=not (scan.strip() and cis_block.strip()))

if btn:
    value = scan.strip()

    try:
        # 1) основной метод — filter по attributes.<attrId>=value
        order = ms.find_customerorder_by_attr_id_value(qr_attr_id.strip(), value)

        # 2) fallback — search
        if not order:
            order = ms.search_customerorder(value)

        # 3) fallback — bruteforce последних заказов
        if not order:
            order = ms.find_customerorder_by_attr_bruteforce_recent(qr_attr_name.strip(), value, limit=2000)

        if not order:
            st.error("Заказ не найден в МойСклад")
            st.stop()

        order_id = order["id"]
        order_name = order.get("name", "")
        st.success(f"Найден заказ: {order_name} ({order_id})")

        # Формируем блок
        cis_lines = [x.strip() for x in cis_block.splitlines() if x.strip()]
        block = "[CIS]\n" + "\n".join(cis_lines) + "\n[/CIS]"

        updated = ms.append_to_customerorder_description(order_id, block)
        st.success("Записал коды в customerorder.description ✅")

        if debug:
            st.write("Текущее description (кусок):")
            st.code((updated.get("description") or "")[:2000])

    except HttpError as e:
        st.error(f"Ошибка МойСклад: HTTP {e.status}")
        st.json(e.payload)
    except Exception as e:
        st.exception(e)
