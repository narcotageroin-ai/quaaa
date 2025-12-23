from __future__ import annotations

import streamlit as st

from src.moysklad import MoySkladClient, HttpError


st.set_page_config(page_title="CIS Scanner → МойСклад", layout="centered")
st.write("BUILD:", "2025-12-23 ATTR-BRUTEFORCE")
st.title("Сканер маркировки (DataMatrix) → МойСклад (customerorder.description)")


with st.sidebar:
    st.header("Настройки")

    ms_token = st.text_input("MS_TOKEN", type="password", value=st.secrets.get("MS_TOKEN", ""))

    # ВАЖНО: фильтра по attributes.<id> в МС нет, поэтому ID нужен для сверки внутри attributes[]
    qr_attr_id = st.text_input(
        "MS_ORDER_QR_ATTR_ID (id доп.поля ШККОД128)",
        value=st.secrets.get("MS_ORDER_QR_ATTR_ID", "687d964c-5a22-11ee-0a80-032800443111"),
    )
    qr_attr_name = st.text_input(
        "MS_ORDER_QR_ATTR_NAME (имя доп.поля, fallback)",
        value=st.secrets.get("MS_ORDER_QR_ATTR_NAME", "ШККОД128"),
    )

    limit_total = st.number_input("Сколько последних заказов смотреть (limit_total)", min_value=500, max_value=20000, value=int(st.secrets.get("LIMIT_TOTAL", 5000)))
    page_size = st.number_input("Размер страницы (page_size)", min_value=50, max_value=1000, value=int(st.secrets.get("PAGE_SIZE", 200)))

    st.caption("Поиск идёт перебором последних заказов, потому что фильтр по доп.полям в API не поддерживается.")


if not ms_token.strip():
    st.warning("Укажи MS_TOKEN в сайдбаре (Streamlit Secrets или вручную).")
    st.stop()

ms = MoySkladClient(token=ms_token)


def normalize_scan(s: str) -> str:
    # пока просто strip — у тебя repr чистый
    return (s or "").strip()


def find_order(value: str):
    value = normalize_scan(value)
    if not value:
        return None

    prog = st.progress(0, text="Ищу заказ по доп.полю (перебор последних заказов)...")
    status = st.empty()

    def cb(scanned: int, total: int, offset: int):
        pct = int(min(100, (scanned / total) * 100))
        prog.progress(pct, text=f"Проверено заказов: {scanned}/{total} (offset={offset})")
        status.write(f"Проверено: {scanned} / {total}")

    # 1) основной надёжный метод: перебор последних заказов и сверка attributes[]
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


st.subheader("1) Сканируй QR/Code128 (ШККОД128), например `*CtzwYRSH`")
scan = st.text_input("Скан", value="", placeholder="*CtzwYRSH")
st.caption(f"DEBUG scan repr: {normalize_scan(scan)!r}" if scan else "DEBUG scan repr: ''")

st.subheader("2) Коды DataMatrix (каждый с новой строки)")
cis_block = st.text_area(
    "DataMatrix",
    height=220,
    placeholder="010...21...\n010...21...\n...",
)

col1, col2 = st.columns(2)
with col1:
    find_btn = st.button("🔎 Найти заказ по QR", type="primary", disabled=not normalize_scan(scan))
with col2:
    write_btn = st.button("✅ Записать [CIS] в description", disabled=not (normalize_scan(scan) and cis_block.strip()))


if find_btn:
    value = normalize_scan(scan)
    try:
        order = find_order(value)
        if not order:
            st.error("Заказ не найден в МойСклад (в пределах выбранного лимита перебора)")
        else:
            st.success(f"Найден заказ: {order.get('name')} | id={order.get('id')}")
            st.json(order)
    except HttpError as e:
        st.error(f"Ошибка МойСклад: HTTP {e.status}")
        st.json(e.payload)
    except Exception as e:
        st.exception(e)


if write_btn:
    value = normalize_scan(scan)
    try:
        order = find_order(value)
        if not order:
            st.error("Заказ не найден в МойСклад (в пределах выбранного лимита перебора)")
            st.stop()

        order_id = order["id"]
        order_name = order.get("name", "")
        st.info(f"Пишу CIS в заказ {order_name} ({order_id})")

        cis_lines = [x.strip() for x in cis_block.splitlines() if x.strip()]
        block = "[CIS]\n" + "\n".join(cis_lines) + "\n[/CIS]"

        updated = ms.append_to_customerorder_description(order_id, block)
        st.success("Записал коды в customerorder.description ✅")

        st.write("Описание (кусок):")
        st.code((updated.get("description") or "")[:2000])

    except HttpError as e:
        st.error(f"Ошибка МойСклад: HTTP {e.status}")
        st.json(e.payload)
    except Exception as e:
        st.exception(e)
