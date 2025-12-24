from __future__ import annotations

import os
import time
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from requests.exceptions import ReadTimeout, ConnectTimeout

from src.moysklad import MoySkladClient, HttpError
from src.index_db import IndexDB
from src.indexer import (
    list_customerorders_packing_since,
    extract_attr_value,
    is_done_by_description,
    get_customerorder_positions_expand,
    explode_order_positions,
    expected_units_from_exploded,
)

st.set_page_config(page_title="Упаковка → CIS", layout="wide")
st.write("BUILD:", "2025-12-24 AUTO-10MIN-AUTO-SCAN")
st.title("Упаковка: авто-индекс заказов → мгновенный поиск → CIS")

os.makedirs("data", exist_ok=True)

with st.sidebar:
    st.header("MS")
    ms_token = st.text_input("MS_TOKEN", type="password", value=st.secrets.get("MS_TOKEN", ""))
    ms_packing_state_href = st.text_input(
        "MS_PACKING_STATE_HREF",
        value=st.secrets.get("MS_PACKING_STATE_HREF", ""),
    )

    st.divider()
    st.header("ШККОД128")
    qr_attr_id = st.text_input(
        "MS_ORDER_QR_ATTR_ID",
        value=st.secrets.get("MS_ORDER_QR_ATTR_ID", "687d964c-5a22-11ee-0a80-032800443111"),
    )
    qr_attr_name = st.text_input(
        "MS_ORDER_QR_ATTR_NAME",
        value=st.secrets.get("MS_ORDER_QR_ATTR_NAME", "ШККОД128"),
    )

    st.divider()
    st.header("Авто-индекс каждые 10 минут")
    date_from = st.text_input("DATE_FROM (YYYY-MM-DD)", value=st.secrets.get("DATE_FROM", "2025-12-20"))
    max_total = st.number_input("MAX_TOTAL", min_value=50, max_value=20000, value=int(st.secrets.get("MAX_TOTAL", 4000)))
    page_limit = st.number_input("PAGE_LIMIT", min_value=50, max_value=500, value=int(st.secrets.get("PAGE_LIMIT", 200)))
    list_limit = st.number_input("Сколько показывать в списке", min_value=20, max_value=2000, value=int(st.secrets.get("LIST_LIMIT", 200)))

db = IndexDB("data/index.sqlite")
db.init()

if not ms_token.strip():
    st.warning("Укажи MS_TOKEN.")
    st.stop()
if not ms_packing_state_href.strip():
    st.warning("Укажи MS_PACKING_STATE_HREF (href статуса «упаковка»).")
    st.stop()

ms = MoySkladClient(token=ms_token)

# Авто-обновление страницы каждые 10 минут (600_000 мс)
tick = st_autorefresh(interval=10 * 60 * 1000, key="auto_refresh_10m")

# ---------- авто-индексация (с защитой от частого запуска) ----------
def run_indexing(auto: bool = True) -> None:
    now = time.time()
    last = float(st.session_state.get("last_index_ts", 0.0))
    if auto and (now - last) < 9.5 * 60:
        return  # не чаще ~раз в 10 минут

    st.session_state["last_index_ts"] = now

    prog = st.progress(0, text="Авто-индексация: загружаю заказы из МС...")
    status = st.empty()

    orders = list_customerorders_packing_since(
        ms=ms,
        packing_state_href=ms_packing_state_href.strip(),
        date_from=date_from.strip(),
        limit=int(page_limit),
        max_total=int(max_total),
    )

    added = 0
    skipped_done = 0
    no_barcode = 0

    for i, o in enumerate(orders, start=1):
        oid = o.get("id")
        if not oid:
            continue

        # берём full, чтобы прочитать description/attributes
        full = ms.get_customerorder(oid)

        # 2) обработанные — убираем
        if is_done_by_description(full):
            skipped_done += 1
            continue

        b128 = extract_attr_value(full, attr_id=qr_attr_id, attr_name=qr_attr_name)
        if not b128:
            no_barcode += 1
            continue

        pos = get_customerorder_positions_expand(ms, oid)
        exploded = explode_order_positions(ms, pos)
        expected_units = expected_units_from_exploded(exploded)

        db.upsert_order(
            barcode128=str(b128).strip(),
            order_id=str(oid),
            order_name=str(full.get("name") or ""),
            moment=str(full.get("moment") or ""),
            expected_units=expected_units,
            done=0,
        )
        db.replace_positions(str(b128).strip(), exploded)
        added += 1

        if i % 10 == 0:
            pct = int((i / max(1, len(orders))) * 100)
            prog.progress(pct, text=f"Авто-индексация {i}/{len(orders)}...")
            status.write(f"Обновлено: {added} | уже обработано: {skipped_done} | без ШККОД128: {no_barcode}")

    prog.progress(100, text="Авто-индексация завершена")
    status.write(f"Готово. Обновлено: {added} | уже обработано: {skipped_done} | без ШККОД128: {no_barcode}")

# запуск авто-индекса при первом заходе и на каждом тике
try:
    run_indexing(auto=True)
except Exception:
    # авто не должно валить всю страницу
    pass

# ---------- UI ----------
left, right = st.columns([1, 1], gap="large")

with left:
    st.subheader("Список заказов в «упаковка» (только НЕ обработанные)")
    st.caption("Обработанные (где уже есть [CIS]...[/CIS]) автоматически исчезают из списка.")
    open_orders = db.list_open_orders(limit=int(list_limit))
    st.json({"stats": db.stats(), "shown": len(open_orders)})
    st.dataframe(open_orders, use_container_width=True, height=420)

with right:
    st.subheader("Скан QR/Code128 → сразу найти заказ (без кнопки)")
    scan_val = st.text_input("ШККОД128", value="", placeholder="*CtzwYRSH", key="scan_code128")

    found = db.lookup_order(scan_val.strip()) if scan_val.strip() else None

    if scan_val.strip() and not found:
        st.warning("Не найдено в индексе. Подожди авто-обновление (до 10 минут) или убедись, что заказ реально в статусе «упаковка» и с DATE_FROM попадает.")
    if found:
        st.success(f"Найден заказ: {found['order_name']} | id={found['order_id']} | moment={found.get('moment')}")
        st.caption(f"Ожидается КИЗов: {int(found.get('expected_units') or 0)}")

        pos = db.lookup_positions(scan_val.strip())
        with st.expander("Распаковка комплекта → товары", expanded=True):
            st.dataframe(pos, use_container_width=True, height=220)

        st.divider()

        # ---- Сканирование КИЗов по одному (авто новая строка) ----
st.subheader("Сканируй КИЗы (DataMatrix) по одному")

if "cis_scanned" not in st.session_state:
    st.session_state["cis_scanned"] = []  # список в порядке сканирования

def add_cis(val: str):
    v = (val or "").strip()
    if not v:
        return
    # не даём дублей
    if v not in st.session_state["cis_scanned"]:
        st.session_state["cis_scanned"].append(v)

def on_cis_scan():
    # берём значение из виджета
    v = (st.session_state.get("cis_one_input") or "").strip()
    if v:
        add_cis(v)
    # ✅ очищаем поле корректно (в callback)
    st.session_state["cis_one_input"] = ""

st.text_input(
    "КИЗ (один скан)",
    value="",
    key="cis_one_input",
    placeholder="010...21...",
    on_change=on_cis_scan,
)

expected = int(found.get("expected_units") or 0)
scanned_count = len(st.session_state["cis_scanned"])
remaining = max(0, expected - scanned_count)

st.write(f"Просканировано: **{scanned_count}** / **{expected}** | Осталось: **{remaining}**")

st.text_area(
    "Список просканированных КИЗов",
    value="\n".join(st.session_state["cis_scanned"]),
    height=180,
    key="cis_view",
    disabled=True,
)

c1, c2, c3 = st.columns(3)
with c1:
    if st.button("🧹 Очистить КИЗы"):
        st.session_state["cis_scanned"] = []
        st.session_state["cis_one_input"] = ""
        st.rerun()
with c2:
    if st.button("↩️ Удалить последний"):
        if st.session_state["cis_scanned"]:
            st.session_state["cis_scanned"].pop()
        st.session_state["cis_one_input"] = ""
        st.rerun()
with c3:
    if st.button("🔄 Обновить индекс сейчас"):
        try:
            run_indexing(auto=False)
        finally:
            st.session_state["cis_one_input"] = ""
            st.rerun()

        st.subheader("Отправка в МойСклад")
        if not can_send:
            st.error("Нельзя отправить: не просканены ВСЕ КИЗы комплекта.")
        send_btn = st.button("✅ Записать [CIS] в customerorder.description", disabled=not can_send)

        if send_btn:
            try:
                order_id = found["order_id"]
                cis_lines = st.session_state["cis_scanned"]
                block = "[CIS]\n" + "\n".join(cis_lines) + "\n[/CIS]"

                updated = ms.append_to_customerorder_description(order_id, block)

                # 2) убрать из списка: помечаем done в БД, и в МС уже есть [CIS]
                db.mark_done(scan_val.strip())

                st.success("Записал коды в customerorder.description ✅ Заказ помечен обработанным и исчезнет из списка.")
                # очистим для следующего заказа
                st.session_state["cis_scanned"] = []
                st.session_state["scan_code128"] = ""
                st.rerun()

            except HttpError as e:
                st.error(f"Ошибка МойСклад: HTTP {e.status}")
                st.json(e.payload)
            except (ReadTimeout, ConnectTimeout):
                st.error("МойСклад долго отвечает. Попробуй ещё раз.")
            except Exception as e:
                st.exception(e)
