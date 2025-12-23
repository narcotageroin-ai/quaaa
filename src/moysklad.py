from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

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

    # ---------- CustomerOrder search ----------

    def find_customerorder_by_name(self, order_name: str) -> Optional[Dict[str, Any]]:
        order_name = order_name.strip()
        if not order_name:
            return None

        safe = order_name.replace('"', '\\"')

        # 1) exact match by name
        page = self.get(
            "/entity/customerorder",
            params={"limit": 100, "filter": f'name="{safe}"'},
        )
        rows = page.get("rows", []) or []
        if rows:
            rows.sort(key=lambda r: r.get("moment", ""), reverse=True)
            return rows[0]

        # 2) fallback: search
        page = self.get(
            "/entity/customerorder",
            params={"limit": 100, "search": order_name},
        )
        rows = page.get("rows", []) or []
        if not rows:
            return None

        rows.sort(key=lambda r: r.get("moment", ""), reverse=True)
        return rows[0]

    def find_customerorder_by_attr_href_value(self, attr_href: str, value: str) -> Optional[Dict[str, Any]]:
        """
        Find customerorder by custom attribute using exact attribute meta.href (no name resolution).
        """
        attr_href = (attr_href or "").strip()
        value = (value or "").strip()
        if not attr_href or not value:
            return None

        for expr in (f'{attr_href}="{value}"', f"{attr_href}={value}"):
            page = self.get("/entity/customerorder", params={"limit": 100, "filter": expr})
            rows = page.get("rows", []) or []
            if rows:
                rows.sort(key=lambda r: r.get("moment", ""), reverse=True)
                return rows[0]
        return None

    # ---------- CustomerOrder details/update ----------

    def get_customerorder_full(self, order_id: str) -> Dict[str, Any]:
        return self.get(
            f"/entity/customerorder/{order_id}",
            params={"expand": "positions.assortment"},
        )

    def get_bundle_components(self, bundle_href: str) -> List[Dict[str, Any]]:
        bundle = self.get(
            bundle_href,
            params={"expand": "components.assortment,attributes"},
        )
        return (bundle.get("components") or {}).get("rows") or []

    def update_customerorder_description(self, order_id: str, new_description: str) -> Any:
        return self.put(
            f"/entity/customerorder/{order_id}",
            {"description": new_description},
        )
