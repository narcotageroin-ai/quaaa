import os
import io
import streamlit as st
import qrcode

from src.http import HttpError
from src.config import Settings
from src.moysklad import MoySkladClient
from src.order_expand import calc_expected_cis_units
from src.cis_logic import normalize_codes, soft_validate_datamatrix, replace_cis_block


st.set_page_config(page_title="Сканер ЧЗ", layout="wide")
st.write("BUILD:", "2025-12-23 QR+OSHIP")
st.title("Сканер кодов маркировки (DataMatrix)")

# ---------------- SETTINGS ----------------

def load_settings() -> Settings:
    data = {}

    try:
        for k, v in st.secrets.items():
            data[k] = str(v)
    except Exception:
        pass

    keys = [
        "APP_BASE_URL",
        "MS_BASE_URL",
        "MS_TOKEN",
        "MS_ATTR_CIS_REQUIRED",
        "MS_BUNDLE_MARK_FLAG",
        "MS_ORDER_QR_ATTR_NAME",
        "MAX_COMPONENT_FETCH",
    ]

    for k in keys:
        if k not in data and os.getenv(k):
            data[k] = os.getenv(k)

    return Settings(**data)


# ---------------- QR UTILS ----------------

def make_qr_png_bytes(url: str) -> bytes:
    qr = qrcode.QRCode(border=2, box_size=6)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------- LOAD ORDER ----------------

def load_order(ms: MoySkladClient, settings: Settings, query: str):
    query = (query or "").strip()
    if not query:
        st.warning("Отсканируй QR или введи номер заказа")
        st.stop()

    try:
        # 1️⃣ пробуем найти по QR (доп.поле)
        row = ms.find_customerorder_by_attr_value(
            settings.MS_ORDER_QR_ATTR_NAME,
            query,
        )
        # 2️⃣ если не нашли — пробуем по номеру заказа
        if not row:
            row = ms.find_customerorder_by_name(query)

    except HttpError as e:
        st.error(f"Ошибка МойСклад: HTTP {e.status}")
        st.json(e.payload)
        st.stop()

    if not row:
        st.error("Заказ не найден в МойСклад")
        st.stop()

    order_id = row["id"]

    try:
        full = ms.get_customerorder_full(order_id)
    except HttpError as e:
        st.error(f"Ошибка загрузки заказа: HTTP {e.status}")
        st.json(e.payload)
        st.stop()

    expected, lines, warnings = calc_expected_cis_units(
        ms=ms,
        order_full=full,
        attr_cis_required=settings.MS_ATTR_CIS_REQUIRED,
        bundle_mark_flag=settings.MS_BUNDLE_MARK_FLAG,
        max_component_fetch=settings.MAX_COMPONENT_FETCH,
    )

    st.session_state["order_id"] = order_id
    st.session_state["order_full"] = full
    st.session_state["expected"] = expected
    st.session_state["lines"] = lines
    st.session_state["warnings"] = warnings


# ---------------- UI ----------------

with st.sidebar:
    st.subheader("Настройки")
    try:
        settings = load_settings()
        st.success("OK")
    except Exception as e:
        st.error(f"Ошибка настроек: {e}")
        st.stop()

    dry_run = st.toggle("Dry run", value=False)

ms = MoySkladClient(
    base_url=settings.MS_BASE_URL,
    token=settings.ms_auth_header(),
)

st.markdown("### Сканируй QR (ШККОД128) или введи номер заказа")

with st.form("scan_form"):
    scan_value = st.text_input(
        "QR / Номер заказа",
        placeholder="*Cr9lrVQX или 4345577084",
    )
    submit = st.form_submit_button("Открыть заказ")

if submit:
    load_order(ms, settings, scan_value)


# ---------------- SCAN CIS ----------------

if "order_full" in st.session_state:
    full = st.session_state["order_full"]
    expected = st.session_state["expected"]

    st.divider()
    st.success(f"Заказ {full.get('name')} | Нужно КМ: {expected}")

    st.markdown("### Сканирование DataMatrix")
    raw = st.text_area("Каждый код с новой строки", height=260)

    codes, dups = normalize_codes(raw)

    c1, c2, c3 = st.columns(3)
    c1.metric("Уникальных", len(codes))
    c2.metric("Дубли", len(dups))
    c3.metric("Ожидалось", expected)

    if dups:
        st.error("Обнаружены дубли")

    if st.button("✅ Записать в МС", disabled=(len(codes) != expected)):
        new_desc = replace_cis_block(full.get("description") or "", codes)

        if dry_run:
            st.code(new_desc)
        else:
            try:
                ms.update_customerorder_description(
                    st.session_state["order_id"],
                    new_desc,
                )
                st.success("Коды сохранены в МойСклад")
            except HttpError as e:
                st.error(f"Ошибка записи: HTTP {e.status}")
                st.json(e.payload)
