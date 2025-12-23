import os
import datetime as dt
import streamlit as st

from src.config import Settings
from src.moysklad import MoySkladClient
from src.order_expand import calc_expected_cis_units
from src.cis_logic import normalize_codes, soft_validate_datamatrix, replace_cis_block

st.set_page_config(page_title="Сканер ЧЗ (DataMatrix) → МойСклад", layout="wide")
st.title("Сканер кодов маркировки (DataMatrix) → customerorder.description (МойСклад)")

def load_settings() -> Settings:
    data = {}
    try:
        for k, v in st.secrets.items():
            data[k] = str(v)
    except Exception:
        pass

    keys = ["MS_BASE_URL","MS_TOKEN","MS_ATTR_CIS_REQUIRED","MS_BUNDLE_MARK_FLAG","MAX_COMPONENT_FETCH"]
    for k in keys:
        if k not in data and os.getenv(k):
            data[k] = os.getenv(k)

    return Settings(**data)

with st.sidebar:
    st.subheader("Настройки")
    try:
        settings = load_settings()
        st.success("OK")
    except Exception as e:
        st.error(f"Ошибка настроек: {e}")
        st.stop()

    dry_run = st.toggle("Dry run (не записывать в МС)", value=False)

ms = MoySkladClient(base_url=settings.MS_BASE_URL, token=settings.ms_auth_header())

order_name = st.text_input("Номер заказа МойСклад (customerorder.name)", placeholder="Например: 4375172716")
load_btn = st.button("Загрузить заказ", type="primary")

if load_btn:
    if not order_name.strip():
        st.warning("Введите номер заказа.")
        st.stop()

    with st.spinner("Ищу заказ в МойСклад..."):
       from src.http import HttpError  # добавь импорт сверху

try:
    row = ms.find_customerorder_by_name(order_name.strip())
except HttpError as e:
    st.error(f"Ошибка МойСклад: HTTP {e.status}")
    st.json(e.payload)
    st.stop()

    if not row:
        st.error("Заказ не найден по name. Проверьте номер (customerorder.name).")
        st.stop()

    order_id = row["id"]
    with st.spinner("Загружаю состав заказа..."):
        full = ms.get_customerorder_full(order_id)

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

if "order_full" in st.session_state:
    full = st.session_state["order_full"]
    expected = st.session_state["expected"]
    lines = st.session_state["lines"]
    warnings = st.session_state["warnings"]

    st.success(f"Заказ: {full.get('name')} | Ожидается КМ: {expected}")

    if warnings:
        st.warning("\n".join(warnings))

    with st.expander("Показать расчёт по позициям"):
        for ln in lines:
            if ln.get("type") == "component":
                st.write(f"Комплект: **{ln.get('bundle')}** → {ln.get('name')} | шт: {ln.get('units')} | ЧЗ: {ln.get('need_cis')}")
            else:
                st.write(f"{ln.get('name')} | шт: {ln.get('units')} | ЧЗ: {ln.get('need_cis')}")

    st.markdown("### Сканирование DataMatrix (каждый код с новой строки)")
    raw = st.text_area("Вставьте/сканируйте коды", height=240, placeholder="01...\n01...\n01...")

    codes, dups = normalize_codes(raw)
    dm_warnings = []
    for c in codes[:50]:
        w = soft_validate_datamatrix(c)
        if w:
            dm_warnings.append(f"{c[:32]}... → " + ", ".join(w))

    c1, c2, c3, c4 = st.columns([1,1,1,1])
    c1.metric("Введено (уникальных)", len(codes))
    c2.metric("Дубли", len(dups))
    c3.metric("Ожидалось", expected)
    c4.metric("Отклонение", len(codes) - expected)

    if dups:
        st.error("Есть дубли (первые 10):\n" + "\n".join(dups[:10]))

    if dm_warnings:
        st.warning("Предупреждения по формату DataMatrix (мягкая проверка):\n" + "\n".join(dm_warnings[:10]))

    save_ok = (len(dups) == 0) and (expected == 0 or len(codes) == expected)
    if expected > 0 and len(codes) != expected:
        st.info("Чтобы сохранить, количество кодов должно совпасть с ожидаемым.")

    if st.button("✅ Записать в МойСклад", disabled=not save_ok, type="primary"):
        order_id = st.session_state["order_id"]
        desc = full.get("description") or ""
        new_desc = replace_cis_block(desc, codes)
        if dry_run:
            st.success("Dry run: запись не выполнена. Ниже пример description:")
            st.code(new_desc)
        else:
            with st.spinner("Записываю в customerorder.description..."):
                ms.update_customerorder_description(order_id, new_desc)
            st.success("Готово! Коды записаны в customerorder.description.")
