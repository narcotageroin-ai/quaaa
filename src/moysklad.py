from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from datetime import datetime, timedelta

from src.http import request_json


class MoySkladClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/") + "/"
        self.token = token

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": self.token,
            "Accept": "application/json;charset=utf-8",
            "Content-Type": "application/json;charset=utf-8",
        }

    def get(self, path_or_url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = (
            path_or_url
            if path_or_url.startswith("http")
            else urljoin(self.base_url, path_or_url.lstrip("/"))
        )
        return request_json("GET", url, headers=self._headers(), params=params)

    def put(self, path_or_url: str, body: Dict[str, Any]) -> Any:
        url = (
            path_or_url
            if path_or_url.startswith("http")
            else urljoin(self.base_url, path_or_url.lstrip("/"))
        )
        return request_json("PUT", url, headers=self._headers(), json_body=body)

    # ---------- CustomerOrder basic ----------

    def find_customerorder_by_name(self, order_name: str) -> Optional[Dict[str, Any]]:
        order_name = (order_name or "").strip()
        if not order_name:
            return None

        safe = order_name.replace('"', '\\"')

        page = self.get(
            "/entity/customerorder",
            params={"limit": 100, "filter": f'name="{safe}"'},
        )
        rows = page.get("rows", []) or []
        if rows:
            rows.sort(key=lambda r: r.get("moment", ""), reverse=True)
            return rows[0]

        page = self.get(
            "/entity/customerorder",
            params={"limit": 100, "search": order_name},
        )
        rows = page.get("rows", []) or []
        if not rows:
            return None

        rows.sort(key=lambda r: r.get("moment", ""), reverse=True)
        return rows[0]

    def list_customerorders(self, limit: int = 100, offset: int = 0, filter_expr: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if filter_expr:
            params["filter"] = filter_expr
        return self.get("/entity/customerorder", params=params)

    def get_customerorder_full(self, order_id: str) -> Dict[str, Any]:
        return self.get(
            f"/entity/customerorder/{order_id}",
            params={"expand": "positions.assortment"},
        )

    def update_customerorder_description(self, order_id: str, new_description: str) -> Any:
        return self.put(
            f"/entity/customerorder/{order_id}",
            {"description": new_description},
        )

    def get_bundle_components(self, bundle_href: str) -> List[Dict[str, Any]]:
        bundle = self.get(
            bundle_href,
            params={"expand": "components.assortment,attributes"},
        )
        return (bundle.get("components") or {}).get("rows") or []

    # ---------- Find by attribute href/value (fast + brute force fallback) ----------

    @staticmethod
    def _attr_value_matches(attr: Dict[str, Any], attr_href: str, value: str) -> bool:
        meta = (attr.get("meta") or {})
        href = (meta.get("href") or "").strip()
        if href != attr_href.strip():
            return False
        return str(attr.get("value")).strip() == value.strip()

    def find_customerorder_by_attr_href_value_fast(self, attr_href: str, value: str) -> Optional[Dict[str, Any]]:
        attr_href = (attr_href or "").strip()
        value = (value or "").strip()
        if not attr_href or not value:
            return None

        # Try server-side filter (fast)
        for expr in (f'{attr_href}="{value}"', f"{attr_href}={value}"):
            page = self.get("/entity/customerorder", params={"limit": 50, "filter": expr})
            rows = page.get("rows", []) or []
            if rows:
                rows.sort(key=lambda r: r.get("moment", ""), reverse=True)
                return rows[0]
        return None

    def find_customerorder_by_attr_href_value_bruteforce(
        self,
        attr_href: str,
        value: str,
        max_orders: int = 500,
        days_back: int = 30,
    ) -> Optional[Dict[str, Any]]:
        """
        Guaranteed method: scan last N orders (optionally by moment >= now-days_back),
        load full order and compare attributes.
        """
        attr_href = (attr_href or "").strip()
        value = (value or "").strip()
        if not attr_href or not value:
            return None

        date_from = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d %H:%M:%S")
        # MS moment filter supports >= in some contexts; if not, we still have N cap
        filter_expr = f"moment>={date_from}"

        scanned = 0
        offset = 0
        limit = 100

        while scanned < max_orders:
            page = self.list_customerorders(limit=limit, offset=offset, filter_expr=filter_expr)
            rows = page.get("rows", []) or []
            if not rows:
                break

            for r in rows:
                if scanned >= max_orders:
                    break
                oid = r.get("id")
                if not oid:
                    continue
                scanned += 1
                full = self.get_customerorder_full(oid)
                attrs = full.get("attributes") or []
                for a in attrs:
                    if isinstance(a, dict) and self._attr_value_matches(a, attr_href, value):
                        return full

            offset += limit

        return None
