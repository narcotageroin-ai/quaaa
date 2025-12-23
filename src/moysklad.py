from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, List

import requests


class HttpError(Exception):
    def __init__(self, status: int, payload: Any):
        super().__init__(f"HTTP {status}: {payload}")
        self.status = status
        self.payload = payload


def request_json(
    method: str,
    url: str,
    headers: Dict[str, str],
    params: Optional[Dict[str, Any]] = None,
    json: Any = None,
) -> Any:
    resp = requests.request(method, url, headers=headers, params=params, json=json, timeout=60)
    if resp.status_code >= 400:
        try:
            payload = resp.json()
        except Exception:
            payload = resp.text
        raise HttpError(resp.status_code, payload)
    if resp.status_code == 204:
        return None
    return resp.json()


@dataclass
class MoySkladClient:
    token: str
    base_url: str = "https://api.moysklad.ru/api/remap/1.2"

    def _headers(self) -> Dict[str, str]:
        auth = (self.token or "").strip()
        # токен может прийти уже с "Bearer " или "Basic "
        if not (auth.lower().startswith("bearer ") or auth.lower().startswith("basic ")):
            auth = f"Bearer {auth}"

        return {
            "Authorization": auth,
            "Accept": "application/json;charset=utf-8",
            "Content-Type": "application/json",
        }

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{path}"
        return request_json("GET", url, headers=self._headers(), params=params)

    def put(self, path: str, payload: Any) -> Any:
        url = f"{self.base_url}{path}"
        return request_json("PUT", url, headers=self._headers(), json=payload)

    # ---------------- CustomerOrder ----------------

    def find_customerorder_by_attr_id_value(self, attr_id: str, value: str) -> Optional[Dict[str, Any]]:
        """
        Ищем заказ покупателя по значению доп.поля.
        Самый надёжный вариант для МС: filter=attributes.<attr_id>=<value>
        """
        attr_id = (attr_id or "").strip()
        value = (value or "").strip()
        if not attr_id or not value:
            return None

        flt = f"attributes.{attr_id}={value}"
        page = self.get("/entity/customerorder", params={"limit": 10, "filter": flt, "order": "moment,desc"})
        rows = page.get("rows", []) if isinstance(page, dict) else []
        return rows[0] if rows else None

    def search_customerorder(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Фоллбек: общий поиск (может не искать в attributes, но иногда помогает).
        """
        query = (query or "").strip()
        if not query:
            return None
        page = self.get("/entity/customerorder", params={"limit": 20, "search": query, "order": "moment,desc"})
        rows = page.get("rows", []) if isinstance(page, dict) else []
        return rows[0] if rows else None

    def list_customerorders_page(self, limit: int, offset: int) -> List[Dict[str, Any]]:
        page = self.get("/entity/customerorder", params={"limit": limit, "offset": offset, "order": "moment,desc"})
        return page.get("rows", []) if isinstance(page, dict) else []

    def find_customerorder_by_attr_bruteforce_recent(
        self,
        attr_name: str,
        value: str,
        limit_total: int = 2000,
        page_size: int = 200,
    ) -> Optional[Dict[str, Any]]:
        """
        Железобетонный фоллбек:
        берём последние N заказов и сравниваем attributes[].name/value (в кратком объекте rows).
        """
        attr_name = (attr_name or "").strip()
        value = (value or "").strip()
        if not attr_name or not value:
            return None

        offset = 0
        scanned = 0

        while scanned < limit_total:
            rows = self.list_customerorders_page(limit=min(page_size, limit_total - scanned), offset=offset)
            if not rows:
                break

            for co in rows:
                scanned += 1
                attrs = co.get("attributes") or []
                for a in attrs:
                    if str(a.get("name", "")).strip() == attr_name and str(a.get("value", "")).strip() == value:
                        return co

                if scanned >= limit_total:
                    break

            offset += len(rows)

        return None

    def append_to_customerorder_description(self, order_id: str, text_to_append: str) -> Dict[str, Any]:
        """
        Дописываем в customerorder.description.
        """
        order_id = (order_id or "").strip()
        if not order_id:
            raise ValueError("order_id is empty")

        cur = self.get(f"/entity/customerorder/{order_id}")
        desc = cur.get("description") or ""
        add = (text_to_append or "").strip()
        new_desc = desc + ("\n" if desc and add else "") + add

        payload = {"description": new_desc}
        return self.put(f"/entity/customerorder/{order_id}", payload)
