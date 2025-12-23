import streamlit as st
import os

from src.http import HttpError
from src.config import Settings
from src.moysklad import MoySkladClient
from src.order_expand import calc_expected_cis_units
from src.cis_logic import normalize_codes, replace_cis_block


st.set_page_config(page_title="CIS Scanner", layout="wide")
st.write("BUILD:", "2025-12-23 CLEAN")
st.title("Сканер маркировки (DataMatrix)")


def load_settings():
    data = {}

    try:
        for k, v in st.secrets.items():
            data[k] = str(v)
    except Exception:
        pass

    for k in [
        "MS_BASE_URL",
        "MS_TOKEN",
        "MS_ATTR_CIS_REQUIRED",
        "MS_BUNDLE_MARK_FLAG",
        "MS_ORDER_QR_ATTR_NAME",
        "MAX_COMPONENT_FETCH",
    ]:
        if k not in data and os.getenv(k):
            data[k] = os.getenv(k)

    return Settings(**data)


with st.sidebar:
    try:
        settings = load_settings()
        st.success("Settings OK")
    except Exception as e:
        st.error(f"Settings error: {e}")
        st.stop()


ms = MoySkladClient(
    base_url=settings.MS_BASE_URL,
    token=settings.ms_auth_header(),
)

st.markdown("### Введи номер заказа или отсканируй QR")

with st.form("scan_form"):
    value = st.text_input("QR / номер заказа", placeholder="*Cr9lrVQX или 4345577084")
    submit = st.form_submit_button("Открыть заказ")

if submit:
    try:
        row = ms.find_customerorder_by_attr_value(
            settings.MS_ORDER_QR_ATTR_NAME,
            value.strip(),
        )
        if not row:
            row = ms.find_customerorder_by_name(value.strip())
    except HttpError as e:
        st.error(f"HTTP {e.status}")
        st.json(e.payload)
        st.stop()

    if not row:
        st.error("Заказ не найден")
        st.stop()

    full = ms.get_customerorder_full(row["id"])

    expected, lines, warnings = calc_expected_cis_units(
        ms,
        full,
        settings.MS_ATTR_CIS_REQUIRED,
        settings.MS_BUNDLE_MARK_FLAG,
        settings.MAX_COMPONENT_FETCH,
    )

    st.session_state["order"] = full
    st.session_state["expected"] = expected


if "order" in st.session_state:
    order = st.session_state["order"]
    expected = st.session_state["expected"]

    st.success(f"Заказ {order['name']} | Нужно КМ: {expected}")

    raw = st.text_area("DataMatrix коды (по одному в строке)", height=240)
    codes, dups = normalize_codes(raw)

    if st.button("Записать в МС", disabled=len(codes) != expected):
        desc = replace_cis_block(order.get("description") or "", codes)
        ms.update_customerorder_description(order["id"], desc)
        st.success("Сохранено")
