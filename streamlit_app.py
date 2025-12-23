from __future__ import annotations

import streamlit as st

from src.moysklad import MoySkladClient, HttpError


st.set_page_config(page_title="CIS Scanner → МойСклад", layout="centered")
st.write("BUILD:", "2025-12-23 TWO-BUTTONS")
st.title("Сканер маркировки (DataMatrix) → МойСклад (customerorder.description)")


# -------- Settings (secrets first) --------
with st.sidebar:
    st.header("Настройки")

    ms_token = st.text_input("MS_TOKEN", type="password", value=st.secrets.get("MS_TOKEN", ""))
    qr_attr_id = st.text_input(
        "MS_ORDER_QR_ATTR_ID (ID доп.поля ШККОД128)",
        value=st.secrets.get("MS_ORDER_QR_ATTR_ID", "687d964c-5a22-11ee-0a80-032800443111"),
    )
    qr_attr_name = st.text_input(
        "MS_ORDER_QR_ATTR_NAME (fallback имя)",
        value=st.secrets.get("MS_ORDER_QR_ATTR_NAME", "ШККОД128"),
    )

    st.caption("ID берём из JSON заказа: атрибут 'ШККОД128' → поле 'id'.")

if not ms_token.strip():
    st.warning("Укажи MS_TOKEN в сайдбаре (Streamlit Secrets или вручную).")
    st.stop()

ms = MoySkladClient(token=ms_token)


def find_order(value: str, show_progress: bool = True):
    value = (value or "").strip()
    if not value:
        return None

    # 1) основной метод — filter по attributes.<attrId>=value
    order = ms.find_customerorder_by_attr_id_value(qr_attr_id.strip(), value)

    # 2) fallback — search
    if not order:
        order = ms.search_customerorder(value)

    # 3) fallback — bruteforce
    if not order:
        if show_progress:
            with st.spinner("Не нашёл быстрыми методами. Перебираю последние заказы..."):
                order = ms.find_customerorder_by_attr_bruteforce_recent(qr_attr_name.strip(), value, limit_total=2000)
        else:
            order = ms.find_customerorder_by_attr_bruteforce_recent(qr_attr_name.strip(), value, limit_total=2000)

    return order


st.subheader("1) Сканируй QR/Code128 (ШККОД128), например `*CtzwYRSH`")
scan = st.text_input("Скан", value="", placeholder="*CtzwYRSH")
st.caption(f"DEBUG scan repr: {scan.strip()!r}" if scan else "DEBUG scan repr: ''")

st.subheader("2) Коды DataMatrix (каждый с новой строки)")
cis_block = st.text_area(
    "DataMatrix",
    height=220,
    placeholder="010...21...\n010...21...\n...",
)

col1, col2 = st.columns(2)
with col1:
    find_btn = st.button("🔎 Найти заказ по QR", type="primary", disabled=not scan.strip())
with col2:
    write_btn = st.button("✅ Записать [CIS] в description", disabled=not (scan.strip() and cis_block.strip()))

# ----- Actions -----
if find_btn:
    value = scan.strip()
    try:
        order = find_order(value, show_progress=True)
        if not order:
            st.error("Заказ не найден в МойСклад")
        else:
            st.success(f"Найден заказ: {order.get('name')} | id={order.get('id')}")
            st.json(order)
    except HttpError as e:
        st.error(f"Ошибка МойСклад: HTTP {e.status}")
        st.json(e.payload)
    except Exception as e:
        st.exception(e)

if write_btn:
    value = scan.strip()
    try:
        order = find_order(value, show_progress=True)
        if not order:
            st.error("Заказ не найден в МойСклад")
            st.stop()

        order_id = order["id"]
        order_name = order.get("name", "")
        st.info(f"Пишу CIS в заказ {order_name} ({order_id})")

        cis_lines = [x.strip() for x in cis_block.splitlines() if x.strip()]
        block = "[CIS]\n" + "\n".join(cis_lines) + "\n[/CIS]"

        updated = ms.append_to_customerorder_description(order_id, block)
        st.success("Записал коды в customerorder.description ✅")

        # покажем кусок description
        st.write("Описание (кусок):")
        st.code((updated.get("description") or "")[:2000])

    except HttpError as e:
        st.error(f"Ошибка МойСклад: HTTP {e.status}")
        st.json(e.payload)
    except Exception as e:
        st.exception(e)
