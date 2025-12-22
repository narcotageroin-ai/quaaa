from __future__ import annotations
from typing import Any, Dict, List, Tuple

from src.moysklad import MoySkladClient
from src.cis_logic import _get_attr_bool

def calc_expected_cis_units(
    ms: MoySkladClient,
    order_full: Dict[str, Any],
    attr_cis_required: str,
    bundle_mark_flag: str,
    max_component_fetch: int,
) -> Tuple[int, List[Dict[str, Any]], List[str]]:
    warnings: List[str] = []
    lines: List[Dict[str, Any]] = []
    expected = 0

    positions = (order_full.get("positions") or {}).get("rows") or []

    for pos in positions:
        qty = int(round(pos.get("quantity") or 0))
        ass = pos.get("assortment") or {}
        meta = ass.get("meta") or {}
        a_type = meta.get("type")

        if a_type == "bundle":
            bundle_href = meta.get("href")
            if not bundle_href:
                warnings.append("Bundle без href")
                continue

            bundle = ms.get(bundle_href, params={"expand": "attributes"})
            bundle_marked = bool(_get_attr_bool(bundle, bundle_mark_flag) or False)

            comps = ms.get_bundle_components(bundle_href)
            if len(comps) > max_component_fetch:
                warnings.append(f"Слишком много компонентов в комплекте (>{max_component_fetch}), обрежу список")
                comps = comps[:max_component_fetch]

            for c in comps:
                c_qty = int(round(c.get("quantity") or 0))
                c_ass = c.get("assortment") or {}
                c_href = (c_ass.get("meta") or {}).get("href")
                if not c_href:
                    continue

                c_full = ms.get(c_href, params={"expand": "attributes"})
                need = bundle_marked or bool(_get_attr_bool(c_full, attr_cis_required) or False)
                units = qty * c_qty

                lines.append({
                    "type": "component",
                    "name": c_full.get("name"),
                    "bundle": ass.get("name"),
                    "need_cis": need,
                    "units": units,
                })

                if need:
                    expected += units

        else:
            href = meta.get("href")
            if not href:
                continue
            full = ms.get(href, params={"expand": "attributes"})
            need = bool(_get_attr_bool(full, attr_cis_required) or False)
            lines.append({
                "type": "item",
                "name": full.get("name"),
                "need_cis": need,
                "units": qty,
            })
            if need:
                expected += qty

    return expected, lines, warnings
