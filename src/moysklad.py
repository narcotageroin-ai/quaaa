# src/moysklad.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, List
import requests


class HttpError(Exception):
    def __init__(self, status: int, payload: Any):
        super().__init__(f"HTTP {status}: {payload}")
        self.status = status
        self.payload = payload


def request_json(method: str, url: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None, json: Any = None) -> Any:
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
        # Важно: МС ругался у тебя на Accept — здесь правильное значение.
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json;charset=utf-8",
            "Content-Type": "application/json",
        }

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{path}"
        return request_json("GET", url, headers=self._headers(), params=params)

    def put(self, path: str, payload: Any) -> Any:
        url = f"{self.base_url}{path}"
        return request_json("PUT", url, headers=self._headers(), json=payload)

    # --- CustomerOrder ---

    def find_customerorder_by_attr_id_value(self, attr_id: str, value: str) -> Optional[Dict[str, Any]]:
        """
        Ищем заказ покупателя по значению доп.поля.
        Самый надёжный вариант: filter=attributes.<attr_id>=<value>
        """
        value = (value or "").strip()
        if not value:
            return None

        flt = f"attributes.{attr_id}={value}"
        page = self.get("/entity/customerorder", params={"limit": 10, "filter": flt, "order": "moment,desc"})

        rows = page.get("rows", []) if isinstance(page, dict) else []
        return rows[0] if rows else None

    def search_customerorder(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Фоллбек: контекстный поиск.
        Может сработать, если filter по атрибутам вдруг не матчится.
        """
        query = (query or "").strip()
        if not query:
            return None
        page = self.get("/entity/customerorder", params={"limit": 20, "search": query, "order": "moment,desc"})
        rows = page.get("rows", []) if isinstance(page, dict) else []
        return rows[0] if rows else None

    def find_customerorder_by_attr_bruteforce_recent(self, attr_name: str, value: str, limit: int = 2000) -> Optional[Dict[str, Any]]:
        """
        Самый “железобетонный” фоллбек:
        берём последние N заказов и руками сравниваем по attributes[].name/value
        (медленно, но если надо — найдёт)
        """
        value = (value or "").strip()
        if not value:
            return None

        page = self.get("/entity/customerorder", params={"limit": min(limit, 1000), "offset": 0, "order": "moment,desc"})
        rows = page.get("rows", []) if isinstance(page, dict) else []

        # Если надо больше 1000 — долистаем
        offset = 1000
        while len(rows) < limit:
            if len(rows) == 0:
                break
            nxt = self.get("/entity/customerorder", params={"limit": 1000, "offset": offset, "order": "moment,desc"})
            r2 = nxt.get("rows", []) if isinstance(nxt, dict) else []
            if not r2:
                break
            rows.extend(r2)
            offset += 1000

        target_name = (attr_name or "").strip()

        for co in rows[:limit]:
            attrs = co.get("attributes") or []
            for a in attrs:
                if str(a.get("name", "")).strip() == target_name and str(a.get("value", "")).strip() == value:
                    return co
        return None

    def append_to_customerorder_description(self, order_id: str, text_to_append: str) -> Dict[str, Any]:
        """
        Дописываем в customerorder.description (комментарий/описание).
        """
        cur = self.get(f"/entity/customerorder/{order_id}")
        desc = cur.get("description") or ""
        add = text_to_append or ""
        new_desc = desc + ("\n" if desc and add else "") + add

        payload = {"description": new_desc}
        return self.put(f"/entity/customerorder/{order_id}", payload)
