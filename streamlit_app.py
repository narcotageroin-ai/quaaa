import os
import streamlit as st

from src.http import HttpError
from src.config import Settings
from src.moysklad import MoySkladClient
from src.order_expand import calc_expected_cis_units
from src.cis_logic import normalize_codes, replace_cis_block


st.set_page_config(page_title="CIS Scanner", layout="wide")
st.write("BUILD:", "2025-12-23 QR-ATTR-FIND")
st.title("Сканер маркировки (DataMatrix) → МойСклад (customerorder.description)")


def load_settings() -> Settings:
    data = {}

    # Streamlit secrets
    try:
        for k, v in st.secrets.items():
            data[k] = str(v)
    except Exception:
        pass

    # env vars
    keys = [
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


def load_order(ms: MoySkladClient, settings: Settings, query: str) -> None:
    query = (query or "").strip()
    if not query:
        st.warning("Отсканируй QR (*Cr9lrVQX) или введи номер заказа (4345577084)")
        st.stop()

    try:
        # 1) try QR attribute in customerorder
        row = ms.find_entity_by_attr_value("customerorder", settings.MS_ORDER_QR_ATTR_NAME, query)

        # 2) fallback: by customerorder.name
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


with st.sidebar:
    st.subheader("Настройки")
    try:
        settings = load_settings()
        st.success("Settings OK")
    except Exception as e:
        st.error(f"Settings error: {e}")
        st.stop()

    dry_run = st.toggle("Dry run (не записывать в МС)", value=False)

ms = MoySkladClient(
    base_url=settings.MS_BASE_URL,
    token=settings.ms_auth_header(),
)

# DEBUG кнопка — покажет, как API реально видит атрибуты customerorder
with st.sidebar:
    st.divider()
    if st.button("DEBUG: атрибуты (customerorder/demand/saleschannelorder)"):
        try:
            entities = ["customerorder", "demand", "saleschannelorder"]
            result = {}
            for ent in entities:
                meta = ms.get(f"/entity/{ent}/metadata")
                attrs = meta.get("attributes") or []
                out = []
                for a in attrs:
                    if isinstance(a, dict):
                        out.append({
                            "name": a.get("name"),
                            "type": a.get("type"),
                            "href": (a.get("meta") or {}).get("href"),
                        })
                result[ent] = out
            st.json(result)
        except HttpError as e:
            st.error(f"HTTP {e.status}")
            st.json(e.payload)
        st.stop()



st.markdown("### Сканируй QR из oShip (значение из доп.поля) или введи номер заказа")

with st.form("scan_form", clear_on_submit=False):
    scan_value = st.text_input(
        "QR / номер заказа",
        placeholder="*Cr9lrVQX или 4345577084",
    )
    submit = st.form_submit_button("Открыть заказ")

if submit:
    load_order(ms, settings, scan_value)


if "order_full" in st.session_state:
    order = st.session_state["order_full"]
    expected = st.session_state["expected"]
    lines = st.session_state["lines"]
    warnings = st.session_state["warnings"]

    st.divider()
    st.success(f"Заказ {order.get('name')} | Нужно КМ: {expected}")

    if warnings:
        st.warning("\n".join(warnings))

    with st.expander("Показать расчёт по позициям"):
        for ln in lines:
            if ln.get("type") == "component":
                st.write(
                    f"Комплект: **{ln.get('bundle')}** → {ln.get('name')} | "
                    f"шт: {ln.get('units')} | ЧЗ: {ln.get('need_cis')}"
                )
            else:
                st.write(f"{ln.get('name')} | шт: {ln.get('units')} | ЧЗ: {ln.get('need_cis')}")

    st.markdown("### Сканирование DataMatrix (каждый код с новой строки)")
    raw = st.text_area("Коды", height=260)

    codes, dups = normalize_codes(raw)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Уникальных", len(codes))
    c2.metric("Дубли", len(dups))
    c3.metric("Ожидалось", expected)
    c4.metric("Отклонение", len(codes) - expected)

    if dups:
        st.error("Есть дубли (первые 10):\n" + "\n".join(dups[:10]))

    save_ok = (len(dups) == 0) and (expected == 0 or len(codes) == expected)
    if expected > 0 and len(codes) != expected:
        st.info("Чтобы сохранить, количество кодов должно совпасть с ожидаемым.")

    if st.button("✅ Записать в МойСклад", disabled=not save_ok, type="primary"):
        new_desc = replace_cis_block(order.get("description") or "", codes)

        if dry_run:
            st.success("Dry run: запись не выполнена. Ниже пример description:")
            st.code(new_desc)
        else:
            try:
                ms.update_customerorder_description(st.session_state["order_id"], new_desc)
                st.success("Коды сохранены в customerorder.description ✅")
            except HttpError as e:
                st.error(f"Ошибка записи: HTTP {e.status}")
                st.json(e.payload)
