from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
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

    def _ensure_column(self, conn: sqlite3.Connection, table: str, col: str, ddl: str) -> None:
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

    def init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orders_index (
                    barcode128 TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    order_name TEXT NOT NULL,
                    moment TEXT,
                    expected_units REAL DEFAULT 0,
                    done INTEGER DEFAULT 0,
                    done_at TEXT,
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

            # миграции на всякий случай (если таблица уже была старой)
            self._ensure_column(conn, "orders_index", "expected_units", "expected_units REAL DEFAULT 0")
            self._ensure_column(conn, "orders_index", "done", "done INTEGER DEFAULT 0")
            self._ensure_column(conn, "orders_index", "done_at", "done_at TEXT")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_order_id ON orders_index(order_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_done ON orders_index(done)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_barcode ON exploded_positions(barcode128)")
            conn.commit()

    def upsert_order(
        self,
        barcode128: str,
        order_id: str,
        order_name: str,
        moment: str = "",
        expected_units: float = 0.0,
        done: int = 0,
    ) -> None:
        barcode128 = (barcode128 or "").strip()
        if not barcode128:
            return

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO orders_index(barcode128, order_id, order_name, moment, expected_units, done, done_at, updated_at)
                VALUES(?,?,?,?,?,?,NULL,?)
                ON CONFLICT(barcode128) DO UPDATE SET
                    order_id=excluded.order_id,
                    order_name=excluded.order_name,
                    moment=excluded.moment,
                    expected_units=excluded.expected_units,
                    done=excluded.done,
                    updated_at=excluded.updated_at
                """,
                (barcode128, order_id, order_name, moment, float(expected_units or 0), int(done or 0), _utcnow_iso()),
            )
            conn.commit()

    def replace_positions(self, barcode128: str, positions: List[Dict[str, Any]]) -> None:
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

    def mark_done(self, barcode128: str) -> None:
        barcode128 = (barcode128 or "").strip()
        if not barcode128:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE orders_index SET done=1, done_at=? WHERE barcode128=?",
                (_utcnow_iso(), barcode128),
            )
            conn.commit()

    def lookup_order(self, barcode128: str) -> Optional[Dict[str, Any]]:
        barcode128 = (barcode128 or "").strip()
        if not barcode128:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT barcode128, order_id, order_name, moment, expected_units, done, done_at, updated_at
                FROM orders_index
                WHERE barcode128=?
                """,
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

    def list_open_orders(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT barcode128, order_id, order_name, moment, expected_units, updated_at
                FROM orders_index
                WHERE done=0
                ORDER BY moment DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            return [dict(r) for r in rows]

    def stats(self) -> Dict[str, int]:
        with self._connect() as conn:
            a = conn.execute("SELECT COUNT(*) AS c FROM orders_index").fetchone()["c"]
            b = conn.execute("SELECT COUNT(*) AS c FROM exploded_positions").fetchone()["c"]
            c = conn.execute("SELECT COUNT(*) AS c FROM orders_index WHERE done=0").fetchone()["c"]
            return {"orders_index": int(a), "exploded_positions": int(b), "open_orders": int(c)}
