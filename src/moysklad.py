from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, List, Tuple

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
        # token может прийти уже с "Bearer " или "Basic "
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

    def search_customerorder(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Фоллбек: общий поиск.
        Важно: search НЕ гарантирует поиск по attributes, но иногда помогает.
        """
        query = (query or "").strip()
        if not query:
            return None
        page = self.get("/entity/customerorder", params={"limit": 50, "search": query, "order": "moment,desc"})
        rows = page.get("rows", []) if isinstance(page, dict) else []
        # search может вернуть похожие — проверим атрибуты уже в streamlit_app
        return rows[0] if rows else None

    def list_customerorders_page(self, limit: int, offset: int) -> List[Dict[str, Any]]:
        page = self.get("/entity/customerorder", params={"limit": limit, "offset": offset, "order": "moment,desc"})
        return page.get("rows", []) if isinstance(page, dict) else []

    @staticmethod
    def _attr_match(a: Dict[str, Any], attr_id: str, attr_name: str, value: str) -> bool:
        """
        Проверка одного элемента attributes[] на совпадение.
        """
        v = str(a.get("value", "")).strip()
        if v != value:
            return False

        if attr_id:
            if str(a.get("id", "")).strip() == attr_id:
                return True
            # иногда id нет, но есть meta.href — тоже можем извлечь
            meta = a.get("meta") or {}
            href = str(meta.get("href", "")).strip()
            if href.endswith(f"/{attr_id}"):
                return True

        if attr_name:
            if str(a.get("name", "")).strip() == attr_name:
                return True

        return False

    def find_customerorder_by_attr_value_recent(
        self,
        value: str,
        attr_id: str = "",
        attr_name: str = "",
        limit_total: int = 5000,
        page_size: int = 200,
        progress_cb=None,
    ) -> Optional[Dict[str, Any]]:
        """
        Рабочий способ для МС: перебор последних заказов и поиск по attributes[].

        progress_cb: функция(progress:int, scanned:int, limit_total:int, offset:int)
        """
        value = (value or "").strip()
        attr_id = (attr_id or "").strip()
        attr_name = (attr_name or "").strip()

        if not value:
            return None

        offset = 0
        scanned = 0

        while scanned < limit_total:
            take = min(page_size, limit_total - scanned)
            rows = self.list_customerorders_page(limit=take, offset=offset)
            if not rows:
                break

            for co in rows:
                scanned += 1
                attrs = co.get("attributes") or []
                for a in attrs:
                    if self._attr_match(a, attr_id=attr_id, attr_name=attr_name, value=value):
                        return co

                if progress_cb and scanned % 50 == 0:
                    progress_cb(scanned, limit_total, offset)

                if scanned >= limit_total:
                    break

            offset += len(rows)

            if progress_cb:
                progress_cb(scanned, limit_total, offset)

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
