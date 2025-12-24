from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, List, Tuple
from datetime import datetime
import time

import requests


class HttpError(Exception):
    def __init__(self, status: int, payload: Any):
        super().__init__(f"HTTP {status}: {payload}")
        self.status = status
        self.payload = payload


def parse_ms_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return None


def _should_retry_http(status: int) -> bool:
    return status in (429, 500, 502, 503, 504)


def request_json(
    method: str,
    url: str,
    headers: Dict[str, str],
    params: Optional[Dict[str, Any]] = None,
    json: Any = None,
    timeout: Tuple[float, float] = (20.0, 90.0),  # (connect, read)
    max_retries: int = 4,
) -> Any:
    last_exc: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json,
                timeout=timeout,
            )

            if resp.status_code >= 400:
                try:
                    payload = resp.json()
                except Exception:
                    payload = resp.text

                if _should_retry_http(resp.status_code) and attempt < max_retries:
                    time.sleep(min(2.0, 0.4 * (2 ** (attempt - 1))))
                    continue

                raise HttpError(resp.status_code, payload)

            if resp.status_code == 204:
                return None
            return resp.json()

        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as e:
            last_exc = e
            if attempt < max_retries:
                time.sleep(min(2.0, 0.4 * (2 ** (attempt - 1))))
                continue
            raise

        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt < max_retries:
                time.sleep(min(2.0, 0.4 * (2 ** (attempt - 1))))
                continue
            raise

    if last_exc:
        raise last_exc
    raise RuntimeError("request_json failed unexpectedly")


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
        page = self.get(
            "/entity/customerorder",
            params={"limit": limit, "offset": offset, "order": "moment,desc"},
        )
        return page.get("rows", []) if isinstance(page, dict) else []

    @staticmethod
    def _match_attrs(attrs: List[Dict[str, Any]], attr_id: str, attr_name: str, value: str) -> bool:
        for a in (attrs or []):
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
        limit_total: int = 600,
        page_size: int = 120,
        date_from: str = "",          # 'YYYY-MM-DD' или 'YYYY-MM-DD HH:MM:SS'
        max_full_reads: int = 250,    # ✅ важно: теперь есть
        progress_cb=None,             # progress_cb(scanned, total, offset, full_reads)
    ) -> Optional[Dict[str, Any]]:
        value = (value or "").strip()
        attr_id = (attr_id or "").strip()
        attr_name = (attr_name or "").strip()
        if not value:
            return None

        date_from_dt = None
        if date_from:
            df = date_from.strip()
            if len(df) == 10:
                df += " 00:00:00"
            date_from_dt = parse_ms_dt(df)

        offset = 0
        scanned = 0
        full_reads = 0

        def _progress():
            if progress_cb:
                progress_cb(scanned, limit_total, offset, full_reads)

        _progress()

        while scanned < limit_total:
            take = min(page_size, limit_total - scanned)
            rows = self.list_customerorders_page(limit=take, offset=offset)
            if not rows:
                break

            for co in rows:
                if scanned >= limit_total:
                    break

                # ранний stop по дате
                if date_from_dt:
                    m = parse_ms_dt(co.get("moment", ""))
                    if m and m < date_from_dt:
                        _progress()
                        return None

                scanned += 1

                # если attributes вдруг пришли в short-rows — проверим сразу
                attrs_short = co.get("attributes")
                if isinstance(attrs_short, list) and self._match_attrs(attrs_short, attr_id, attr_name, value):
                    oid = co.get("id")
                    if not oid:
                        continue
                    full_reads += 1
                    _progress()
                    return self.get_customerorder(oid)

                oid = co.get("id")
                if not oid:
                    continue

                if full_reads >= max_full_reads:
                    _progress()
                    return None

                full_reads += 1
                full = self.get_customerorder(oid)
                if self._match_attrs(full.get("attributes") or [], attr_id, attr_name, value):
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
