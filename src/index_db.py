from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime


def _utcnow_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class IndexDB:
    path: str = "data/index.sqlite"

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orders_index (
                    barcode128 TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    order_name TEXT NOT NULL,
                    moment TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS exploded_positions (
                    barcode128 TEXT NOT NULL,
                    line_no INTEGER NOT NULL,
                    assortment_href TEXT,
                    assortment_type TEXT,
                    code TEXT,
                    name TEXT,
                    ean13 TEXT,
                    quantity REAL NOT NULL,
                    PRIMARY KEY (barcode128, line_no)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_order_id ON orders_index(order_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_barcode ON exploded_positions(barcode128)")
            conn.commit()

    def upsert_order(
        self,
        barcode128: str,
        order_id: str,
        order_name: str,
        moment: str = "",
    ) -> None:
        barcode128 = (barcode128 or "").strip()
        if not barcode128:
            return

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO orders_index(barcode128, order_id, order_name, moment, updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(barcode128) DO UPDATE SET
                    order_id=excluded.order_id,
                    order_name=excluded.order_name,
                    moment=excluded.moment,
                    updated_at=excluded.updated_at
                """,
                (barcode128, order_id, order_name, moment, _utcnow_iso()),
            )
            conn.commit()

    def replace_positions(self, barcode128: str, positions: List[Dict[str, Any]]) -> None:
        """
        Полностью заменяет распакованные позиции для данного barcode128
        positions: список dict (assortment_href, assortment_type, code, name, ean13, quantity)
        """
        barcode128 = (barcode128 or "").strip()
        if not barcode128:
            return

        with self._connect() as conn:
            conn.execute("DELETE FROM exploded_positions WHERE barcode128=?", (barcode128,))
            for i, p in enumerate(positions, start=1):
                conn.execute(
                    """
                    INSERT INTO exploded_positions(
                        barcode128, line_no, assortment_href, assortment_type, code, name, ean13, quantity
                    ) VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        barcode128,
                        i,
                        p.get("assortment_href"),
                        p.get("assortment_type"),
                        p.get("code"),
                        p.get("name"),
                        p.get("ean13"),
                        float(p.get("quantity", 0) or 0),
                    ),
                )
            conn.commit()

    def lookup_order(self, barcode128: str) -> Optional[Dict[str, Any]]:
        barcode128 = (barcode128 or "").strip()
        if not barcode128:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT barcode128, order_id, order_name, moment, updated_at FROM orders_index WHERE barcode128=?",
                (barcode128,),
            ).fetchone()
            return dict(row) if row else None

    def lookup_positions(self, barcode128: str) -> List[Dict[str, Any]]:
        barcode128 = (barcode128 or "").strip()
        if not barcode128:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT line_no, assortment_href, assortment_type, code, name, ean13, quantity
                FROM exploded_positions
                WHERE barcode128=?
                ORDER BY line_no ASC
                """,
                (barcode128,),
            ).fetchall()
            return [dict(r) for r in rows]

    def stats(self) -> Dict[str, int]:
        with self._connect() as conn:
            a = conn.execute("SELECT COUNT(*) AS c FROM orders_index").fetchone()["c"]
            b = conn.execute("SELECT COUNT(*) AS c FROM exploded_positions").fetchone()["c"]
            return {"orders_index": int(a), "exploded_positions": int(b)}
