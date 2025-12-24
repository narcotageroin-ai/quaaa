from __future__ import annotations

import os
import streamlit as st
from requests.exceptions import ReadTimeout, ConnectTimeout

from src.moysklad import MoySkladClient, HttpError
from src.index_db import IndexDB
from src.indexer import (
    list_customerorders_packing_since,
    extract_attr_value,
    get_customerorder_positions_expand,
    explode_order_positions,
)

st.set_page_config(page_title="Packing Index → CIS Writer", layout="centered")
st.write("BUILD:", "2025-12-24 PACKING-INDEX-SQLITE")
st.title("Упаковка: индекс заказов (ШККОД128) → мгновенный поиск → запись CIS")

# гарантируем папку под sqlite
os.makedirs("data", exist_ok=True)

with st.sidebar:
    st.header("MS настройки")
    ms_token = st.text_input("MS_TOKEN", type="password", value=st.secrets.get("MS_TOKEN", ""))

    ms_packing_state_href = st.text_input(
        "MS_PACKING_STATE_HREF (href статуса «упаковка»)",
        value=st.secrets.get("MS_PACKING_STATE_HREF", ""),
        placeholder="https://api.moysklad.ru/api/remap/1.2/entity/customerorder/metadata/states/....",
    )

    st.divider()
    st.header("Атрибут ШККОД128")
    qr_attr_id = st.text_input(
        "MS_ORDER_QR_ATTR_ID",
        value=st.secrets.get("MS_ORDER_QR_ATTR_ID", "687d964c-5a22-11ee-0a80-032800443111"),
    )
    qr_attr_name = st.text_input(
        "MS_ORDER_QR_ATTR_NAME (fallback)",
        value=st.secrets.get("MS_ORDER_QR_ATTR_NAME", "ШККОД128"),
    )

    st.divider()
    st.header("Индексирование")
    date_from = st.text_input("Брать заказы начиная с (YYYY-MM-DD)", value=st.secrets.get("DATE_FROM", "2025-12-20"))
    max_total = st.number_input("Макс. заказов за прогон", min_value=50, max_value=20000, value=int(st.secrets.get("MAX_TOTAL", 4000)))
    page_limit = st.number_input("Пачка MS limit", min_value=50, max_value=500, value=int(st.secrets.get("PAGE_LIMIT", 200)))

db = IndexDB("data/index.sqlite")
db.init()

if not ms_token.strip():
    st.warning("Введи MS_TOKEN в сайдбаре.")
    st.stop()

if not ms_packing_state_href.strip():
    st.warning("Введи MS_PACKING_STATE_HREF (href статуса «упаковка») в сайдбаре.")
    st.stop()

ms = MoySkladClient(token=ms_token)

# ------------------ Блок обновления индекса ------------------
st.subheader("1) Обновить индекс заказов «упаковка»")
colA, colB = st.columns([1, 2])
with colA:
    do_index = st.button("🔄 Обновить индекс", type="primary")
with colB:
    st.caption("Индекс: ШККОД128 → заказ + распакованные позиции (bundle → components)")

if do_index:
    try:
        prog = st.progress(0, text="Загружаю список заказов из МойСклад...")
        status = st.empty()

        orders = list_customerorders_packing_since(
            ms=ms,
            packing_state_href=ms_packing_state_href.strip(),
            date_from=date_from.strip(),
            limit=int(page_limit),
            max_total=int(max_total),
        )

        status.write(f"Найдено заказов в «упаковка»: {len(orders)}. Индексирую...")

        added = 0
        skipped = 0
        no_barcode = 0

        for i, o in enumerate(orders, start=1):
            oid = o.get("id")
            if not oid:
                skipped += 1
                continue

            # берём полный заказ, чтобы точно были attributes (и moment)
            full = ms.get_customerorder(oid)
            b128 = extract_attr_value(full, attr_id=qr_attr_id, attr_name=qr_attr_name)
            if not b128:
                no_barcode += 1
                continue

            # позиции → распаковка
            pos = get_customerorder_positions_expand(ms, oid)
            exploded = explode_order_positions(ms, pos)

            db.upsert_order(
                barcode128=str(b128).strip(),
                order_id=str(oid),
                order_name=str(full.get("name") or ""),
                moment=str(full.get("moment") or ""),
            )
            db.replace_positions(str(b128).strip(), exploded)
            added += 1

            if i % 10 == 0:
                pct = int((i / max(1, len(orders))) * 100)
                prog.progress(pct, text=f"Индексирую {i}/{len(orders)}...")
                status.write(f"Готово: {added} | без ШККОД128: {no_barcode} | пропущено: {skipped}")

        prog.progress(100, text="Индекс обновлён")
        st.success(f"Индекс обновлён ✅ Заиндексировано: {added} | без ШККОД128: {no_barcode} | пропущено: {skipped}")
        st.json(db.stats())

    except HttpError as e:
        st.error(f"Ошибка МойСклад: HTTP {e.status}")
        st.json(e.payload)
    except (ReadTimeout, ConnectTimeout):
        st.error("МойСклад долго отвечает. Попробуй ещё раз (или уменьши MAX_TOTAL / сдвинь DATE_FROM ближе).")
    except Exception as e:
        st.exception(e)

st.divider()

# ------------------ Блок мгновенного скана ------------------
st.subheader("2) Скан по ШККОД128 (мгновенно из индекса)")
scan = st.text_input("Скан (например *CtzwYRSH)", value="", placeholder="*CtzwYRSH")
scan_val = (scan or "").strip()
st.caption(f"DEBUG scan repr: {scan_val!r}" if scan_val else "DEBUG scan repr: ''")

if scan_val:
    found = db.lookup_order(scan_val)
    if not found:
        st.warning("Не найдено в индексе. Нажми «Обновить индекс» (или сдвинь DATE_FROM).")
    else:
        st.success(f"Найдено: заказ {found['order_name']} | id={found['order_id']} | moment={found.get('moment')}")
        pos = db.lookup_positions(scan_val)
        st.write("Распакованные позиции (bundle уже раскрыт):")
        st.dataframe(pos, use_container_width=True)

st.divider()

# ------------------ Запись CIS ------------------
st.subheader("3) Записать CIS в customerorder.description")
cis_block = st.text_area("DataMatrix (каждый с новой строки)", height=220, placeholder="010...21...\n010...21...\n...")

write_btn = st.button("✅ Записать [CIS] в description", disabled=not (scan_val and cis_block.strip()))
if write_btn:
    try:
        found = db.lookup_order(scan_val)
        if not found:
            st.error("Скан не найден в индексе. Сначала обнови индекс.")
            st.stop()

        order_id = found["order_id"]
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
