from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, List
from datetime import datetime

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


def parse_ms_dt(s: str) -> Optional[datetime]:
    """
    MS возвращает 'YYYY-MM-DD HH:MM:SS.mmm' или 'YYYY-MM-DD HH:MM:SS'
    """
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return None


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
        order_id = (order_id or "").strip()
        if not order_id:
            raise ValueError("order_id is empty")
        return self.get(f"/entity/customerorder/{order_id}")

    def list_customerorders_page(self, limit: int, offset: int) -> List[Dict[str, Any]]:
        page = self.get("/entity/customerorder", params={"limit": limit, "offset": offset, "order": "moment,desc"})
        return page.get("rows", []) if isinstance(page, dict) else []

    @staticmethod
    def _attr_match_full(order_full: Dict[str, Any], attr_id: str, attr_name: str, value: str) -> bool:
        attrs = order_full.get("attributes") or []
        for a in attrs:
            if str(a.get("value", "")).strip() != value:
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
        date_from: str = "",  # 'YYYY-MM-DD' или 'YYYY-MM-DD HH:MM:SS'
        progress_cb=None,
    ) -> Optional[Dict[str, Any]]:
        """
        Быстрый и гарантированный поиск:
        - берём последние заказы (moment desc)
        - стопаемся, когда moment < date_from (если date_from задан)
        - дочитываем каждый заказ по id и сравниваем attributes
        """
        value = (value or "").strip()
        attr_id = (attr_id or "").strip()
        attr_name = (attr_name or "").strip()
        if not value:
            return None

        date_from_dt = None
        if date_from:
            df = date_from.strip()
            if len(df) == 10:
                df = df + " 00:00:00"
            date_from_dt = parse_ms_dt(df)

        offset = 0
        scanned = 0

        def _progress():
            if progress_cb:
                progress_cb(scanned, limit_total, offset)

        _progress()

        while scanned < limit_total:
            take = min(page_size, limit_total - scanned)
            rows = self.list_customerorders_page(limit=take, offset=offset)
            if not rows:
                break

            # ранний stop по дате (moment desc => дальше только старее)
            if date_from_dt:
                last_moment = parse_ms_dt(rows[-1].get("moment", ""))
                if last_moment and last_moment < date_from_dt:
                    # всё что дальше будет ещё старее — смысла листать нет
                    # но в этой пачке могут быть и свежие, так что всё равно пройдём по каждой записи ниже
                    pass

            for co in rows:
                if scanned >= limit_total:
                    break

                if date_from_dt:
                    m = parse_ms_dt(co.get("moment", ""))
                    if m and m < date_from_dt:
                        _progress()
                        return None  # дальше будут только старые

                scanned += 1
                oid = co.get("id")
                if not oid:
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
        cur = self.get_customerorder(order_id)
        desc = cur.get("description") or ""
        add = (text_to_append or "").strip()
        new_desc = desc + ("\n" if desc and add else "") + add
        return self.put(f"/entity/customerorder/{order_id}", {"description": new_desc})
