from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from src.moysklad import MoySkladClient


def _norm_date_from(date_from: str) -> str:
    """
    МС фильтр moment>=YYYY-MM-DD HH:MM:SS
    """
    df = (date_from or "").strip()
    if not df:
        return ""
    if len(df) == 10:
        return df + " 00:00:00"
    return df


def extract_attr_value(order: Dict[str, Any], attr_id: str = "", attr_name: str = "") -> Optional[str]:
    attrs = order.get("attributes") or []
    for a in attrs:
        if attr_id and str(a.get("id", "")).strip() == attr_id.strip():
            return a.get("value")
        if attr_name and str(a.get("name", "")).strip() == attr_name.strip():
            return a.get("value")
    return None


def list_customerorders_packing_since(
    ms: MoySkladClient,
    packing_state_href: str,
    date_from: str,
    limit: int = 100,
    max_total: int = 2000,
) -> List[Dict[str, Any]]:
    """
    Тянем заказы строго по фильтру:
      state=<href>;moment>=<date_from>
    """
    df = _norm_date_from(date_from)
    offset = 0
    out: List[Dict[str, Any]] = []
    while True:
        if len(out) >= max_total:
            break
        take = min(limit, max_total - len(out))
        flt = f"state={packing_state_href}"
        if df:
            flt += f";moment>={df}"
        page = ms.get(
            "/entity/customerorder",
            params={
                "filter": flt,
                "order": "moment,desc",
                "limit": take,
                "offset": offset,
            },
        )
        rows = page.get("rows", []) if isinstance(page, dict) else []
        if not rows:
            break
        out.extend(rows)
        offset += len(rows)
        if len(rows) < take:
            break
    return out


def get_customerorder_positions_expand(ms: MoySkladClient, order_id: str) -> List[Dict[str, Any]]:
    """
    Берём позиции с expand=assortment чтобы видеть type(bundle/product) + code/name + barcodes
    """
    page = ms.get(f"/entity/customerorder/{order_id}/positions", params={"limit": 1000, "offset": 0, "expand": "assortment"})
    return page.get("rows", []) if isinstance(page, dict) else []


def get_bundle_components(ms: MoySkladClient, bundle_id: str) -> List[Dict[str, Any]]:
    """
    Состав комплекта: /entity/bundle/{id}?expand=components.assortment
    """
    b = ms.get(f"/entity/bundle/{bundle_id}", params={"expand": "components.assortment"})
    comps = (b.get("components") or {}).get("rows") or []
    return comps


def pick_ean13(assortment: Dict[str, Any]) -> str:
    bcs = assortment.get("barcodes") or []
    for bc in bcs:
        if isinstance(bc, dict) and bc.get("ean13"):
            return str(bc["ean13"])
    return ""


def explode_order_positions(ms: MoySkladClient, positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Распаковывает bundle → компоненты * qty_bundle
    обычные товары оставляет как есть.
    Возвращает плоский список строк для сохранения в БД.
    """
    out: List[Dict[str, Any]] = []

    def add_line(ass: Dict[str, Any], qty: float):
        meta = ass.get("meta") or {}
        href = meta.get("href")
        a_type = meta.get("type") or ass.get("type")
        out.append(
            {
                "assortment_href": href,
                "assortment_type": a_type,
                "code": ass.get("code"),
                "name": ass.get("name"),
                "ean13": pick_ean13(ass),
                "quantity": qty,
            }
        )

    for p in positions:
        qty = float(p.get("quantity", 0) or 0)
        ass = p.get("assortment") or {}
        meta = ass.get("meta") or {}
        a_type = (meta.get("type") or "").strip()

        if a_type == "bundle":
            bundle_id = ass.get("id")
            comps = get_bundle_components(ms, bundle_id)
            # components rows обычно содержат quantity + assortment
            for c in comps:
                c_qty = float(c.get("quantity", 0) or 0)
                c_ass = c.get("assortment") or {}
                add_line(c_ass, qty * c_qty)
        else:
            add_line(ass, qty)

    # можно агрегировать одинаковые товары (по href/code) чтобы было красиво:
    agg: Dict[str, Dict[str, Any]] = {}
    for row in out:
        key = (row.get("assortment_href") or row.get("code") or row.get("name") or "").strip()
        if not key:
            key = str(len(agg) + 1)
        if key not in agg:
            agg[key] = dict(row)
        else:
            agg[key]["quantity"] = float(agg[key].get("quantity", 0) or 0) + float(row.get("quantity", 0) or 0)

    return list(agg.values())
