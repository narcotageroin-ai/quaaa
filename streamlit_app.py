from __future__ import annotations

import streamlit as st
from src.moysklad import MoySkladClient, HttpError

st.set_page_config(page_title="CIS Scanner → МойСклад", layout="centered")
st.write("BUILD:", "2025-12-23 FULL-GET-SCAN")
st.title("Сканер маркировки (DataMatrix) → МойСклад (customerorder.description)")

with st.sidebar:
    st.header("Настройки")
    ms_token = st.text_input("MS_TOKEN", type="password", value=st.secrets.get("MS_TOKEN", ""))

    qr_attr_id = st.text_input(
        "MS_ORDER_QR_ATTR_ID (id доп.поля ШККОД128)",
        value=st.secrets.get("MS_ORDER_QR_ATTR_ID", "687d964c-5a22-11ee-0a80-032800443111"),
    )
    qr_attr_name = st.text_input(
        "MS_ORDER_QR_ATTR_NAME (fallback имя)",
        value=st.secrets.get("MS_ORDER_QR_ATTR_NAME", "ШККОД128"),
    )

    limit_total = st.number_input("Сколько последних заказов проверить", min_value=50, max_value=5000, value=int(st.secrets.get("LIMIT_TOTAL", 800)))
    page_size = st.number_input("Размер пачки (страницы)", min_value=20, max_value=500, value=int(st.secrets.get("PAGE_SIZE", 100)))

if not ms_token.strip():
    st.warning("Укажи MS_TOKEN в сайдбаре.")
    st.stop()

ms = MoySkladClient(token=ms_token)

st.subheader("1) Сканируй QR/Code128 (ШККОД128), например `*CtzwYRSH`")
scan = st.text_input("Скан", value="", placeholder="*CtzwYRSH")
scan_val = (scan or "").strip()
st.caption(f"DEBUG scan repr: {scan_val!r}" if scan_val else "DEBUG scan repr: ''")

st.subheader("2) Коды DataMatrix (каждый с новой строки)")
cis_block = st.text_area("DataMatrix", height=220, placeholder="010...21...\n010...21...\n...")

col1, col2 = st.columns(2)
with col1:
    find_btn = st.button("🔎 Найти заказ по QR", type="primary", disabled=not scan_val)
with col2:
    write_btn = st.button("✅ Записать [CIS] в description", disabled=not (scan_val and cis_block.strip()))


def find_order(value: str):
    prog = st.progress(0, text="Ищу заказ (читаю последние заказы и дочитываю каждый по id)...")
    status = st.empty()

    def cb(scanned: int, total: int):
        pct = int(min(100, (scanned / total) * 100))
        prog.progress(pct, text=f"Проверено {scanned}/{total} заказов (GET каждого заказа по id)")
        status.write(f"Проверено: {scanned} / {total}")

    order = ms.find_customerorder_by_attr_value_recent(
        value=value,
        attr_id=qr_attr_id.strip(),
        attr_name=qr_attr_name.strip(),
        limit_total=int(limit_total),
        page_size=int(page_size),
        progress_cb=cb,
    )
    prog.progress(100, text="Готово")
    return order


if find_btn:
    try:
        order = find_order(scan_val)
        if not order:
            st.error("Заказ не найден (в пределах выбранного лимита последних заказов)")
        else:
            st.success(f"Найден заказ: {order.get('name')} | id={order.get('id')}")
            st.json({
                "id": order.get("id"),
                "name": order.get("name"),
                "moment": order.get("moment"),
                "state": (order.get("state") or {}).get("meta", {}),
                "shk128": next((a.get("value") for a in (order.get("attributes") or []) if a.get("id") == qr_attr_id.strip()), None),
            })
    except HttpError as e:
        st.error(f"Ошибка МойСклад: HTTP {e.status}")
        st.json(e.payload)
    except Exception as e:
        st.exception(e)


if write_btn:
    try:
        order = find_order(scan_val)
        if not order:
            st.error("Заказ не найден (в пределах выбранного лимита последних заказов)")
            st.stop()

        order_id = order["id"]
        st.info(f"Пишу CIS в заказ {order.get('name')} ({order_id})")

        cis_lines = [x.strip() for x in cis_block.splitlines() if x.strip()]
        block = "[CIS]\n" + "\n".join(cis_lines) + "\n[/CIS]"

        updated = ms.append_to_customerorder_description(order_id, block)
        st.success("Записал коды в customerorder.description ✅")
        st.code((updated.get("description") or "")[:2000])

    except HttpError as e:
        st.error(f"Ошибка МойСклад: HTTP {e.status}")
        st.json(e.payload)
    except Exception as e:
        st.exception(e)
