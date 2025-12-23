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

    # ---------- Attributes helpers (robust) ----------

    @staticmethod
    def _norm_name(s: str) -> str:
        # lower + remove spaces
        return "".join((s or "").strip().lower().split())

    def _get_attr_href_by_name(self, entity: str, attr_name: str) -> Optional[str]:
        """
        Returns attribute meta.href for entity metadata by attribute display name.
        Robust: ignores spaces/case, and has fallback 'contains' match.
        """
        target = self._norm_name(attr_name)
        if not target:
            return None

        meta = self.get(f"/entity/{entity}/metadata")
        attrs = meta.get("attributes") or []

        # 1) exact match (normalized)
        for a in attrs:
            if not isinstance(a, dict):
                continue
            name = str(a.get("name", ""))
            if self._norm_name(name) == target:
                return (a.get("meta") or {}).get("href")

        # 2) fallback: contains (normalized)
        for a in attrs:
            if not isinstance(a, dict):
                continue
            name = str(a.get("name", ""))
            if target in self._norm_name(name):
                return (a.get("meta") or {}).get("href")

        return None

    def find_entity_by_attr_value(self, entity: str, attr_name: str, value: str) -> Optional[Dict[str, Any]]:
        """
        Find entity row by custom attribute value.
        Works by resolving attribute meta.href and using it in filter.
        """
        href = self._get_attr_href_by_name(entity, attr_name)
        if not href:
            return None

        value = (value or "").strip()
        if not value:
            return None

        # MS can be picky: try both quoted and unquoted
        for expr in (f'{href}="{value}"', f"{href}={value}"):
            page = self.get(f"/entity/{entity}", params={"limit": 100, "filter": expr})
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

    # ---------- Debug helpers ----------

    def list_entity_attributes(self, entity: str) -> List[Dict[str, Any]]:
        meta = self.get(f"/entity/{entity}/metadata")
        attrs = meta.get("attributes") or []
        out: List[Dict[str, Any]] = []
        for a in attrs:
            if not isinstance(a, dict):
                continue
            out.append(
                {
                    "name": a.get("name"),
                    "type": a.get("type"),
                    "href": (a.get("meta") or {}).get("href"),
                }
            )
        return out
