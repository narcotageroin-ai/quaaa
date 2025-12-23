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

    def get_customerorder(self, order_id: str) -> Dict[str, Any]:
        """
        Полное чтение заказа (тут attributes точно есть).
        """
        order_id = (order_id or "").strip()
        if not order_id:
            raise ValueError("order_id is empty")
        return self.get(f"/entity/customerorder/{order_id}")

    def list_customerorders_page(self, limit: int, offset: int) -> List[Dict[str, Any]]:
        """
        Список последних заказов. ВАЖНО: attributes тут могут НЕ приходить.
        """
        page = self.get("/entity/customerorder", params={"limit": limit, "offset": offset, "order": "moment,desc"})
        return page.get("rows", []) if isinstance(page, dict) else []

    @staticmethod
    def _attr_match_full(order_full: Dict[str, Any], attr_id: str, attr_name: str, value: str) -> bool:
        """
        Проверка attributes[] внутри полного заказа.
        """
        attrs = order_full.get("attributes") or []
        for a in attrs:
            v = str(a.get("value", "")).strip()
            if v != value:
                continue

            if attr_id and str(a.get("id", "")).strip() == attr_id:
                return True

            if attr_name and str(a.get("name", "")).strip() == attr_name:
                return True

        return False

    def find_customerorder_by_attr_value_recent(
        self,
        value: str,
        attr_id: str = "",
        attr_name: str = "",
        limit_total: int = 800,
        page_size: int = 100,
        progress_cb=None,
    ) -> Optional[Dict[str, Any]]:
        """
        ГАРАНТИРОВАННЫЙ поиск:
        1) берём последние N заказов списком
        2) по каждому делаем GET /customerorder/{id} и проверяем attributes
        """
        value = (value or "").strip()
        attr_id = (attr_id or "").strip()
        attr_name = (attr_name or "").strip()
        if not value:
            return None

        offset = 0
        scanned = 0

        def _progress():
            if progress_cb:
                # единый контракт: (scanned, total, offset)
                progress_cb(scanned, limit_total, offset)

        _progress()

        while scanned < limit_total:
            take = min(page_size, limit_total - scanned)
            rows = self.list_customerorders_page(limit=take, offset=offset)
            if not rows:
                break

            for co in rows:
                if scanned >= limit_total:
                    break
                scanned += 1

                oid = co.get("id")
                if not oid:
                    _progress()
                    continue

                full = self.get_customerorder(oid)
                if self._attr_match_full(full, attr_id=attr_id, attr_name=attr_name, value=value):
                    _progress()
                    return full

                if scanned % 20 == 0:
                    _progress()

            offset += len(rows)
            _progress()

        return None

    def append_to_customerorder_description(self, order_id: str, text_to_append: str) -> Dict[str, Any]:
        """
        Дописываем в customerorder.description.
        """
        cur = self.get_customerorder(order_id)
        desc = cur.get("description") or ""
        add = (text_to_append or "").strip()
        new_desc = desc + ("\n" if desc and add else "") + add
        return self.put(f"/entity/customerorder/{order_id}", {"description": new_desc})
