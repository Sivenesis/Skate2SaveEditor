"""Touchgrind Skate 2 - Registry Database Editor.

Provides typed CRUD access to registry.db:
- Typed tables: stringdata, integerdata, floatdata, binarydata
- DLC park unlocks (8 parks)
- Challenges editor (280+ challenges across 9 skateparks)
- Highscores editor (Competition and Line modes)
- Equipment indices and per-deck metrics
- Raw SQL query and execution explorer
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any

DLC_PARKS_LIST = [
    "thecarpark",
    "dairyfactory",
    "thedocks",
    "themotel",
    "playground",
    "megaramp",
    "spacedock",
    "theoffice",
]

ALL_PARK_NAMES = [
    "backyard",
    "dairyfactory",
    "downhill",
    "funpark",
    "office",
    "research",
    "spacedock",
    "thecarpark",
    "thedocks",
]

ALLOWED_TABLES = {"binarydata", "floatdata", "integerdata", "stringdata"}


class RegistryEditor:
    """Editor for Touchgrind Skate 2's primary registry.db database."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database file not found: {self.db_path}")

        # Check SQLite integrity and schema
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA schema_version")
            rows = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            existing_tables = {r[0] for r in rows}
            missing = ALLOWED_TABLES - existing_tables
            if missing:
                raise ValueError(f"Database missing required typed tables: {missing}")
        finally:
            conn.close()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # --------------------------------------------------------------------------
    # Raw Typed Table Accessors
    # --------------------------------------------------------------------------

    def get_raw_value(self, table: str, key: str) -> Any:
        if table not in ALLOWED_TABLES:
            raise ValueError(f"Table '{table}' not in allowed tables: {ALLOWED_TABLES}")

        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT value FROM {table} WHERE key = ?", (key,))
            row = cur.fetchone()
            if row is None:
                return None
            val = row[0]
            if table == "floatdata" and val is not None:
                return float(val)
            return val
        finally:
            conn.close()

    def set_raw_value(self, table: str, key: str, value: Any) -> None:
        if table not in ALLOWED_TABLES:
            raise ValueError(f"Table '{table}' not in allowed tables: {ALLOWED_TABLES}")

        # Validate types
        if table == "integerdata":
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"Value for integerdata must be an int, got {type(value)}")
        elif table == "floatdata":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"Value for floatdata must be float/int, got {type(value)}")
            value = float(value)
        elif table == "stringdata":
            if not isinstance(value, str):
                raise TypeError(f"Value for stringdata must be str, got {type(value)}")
        elif table == "binarydata":
            if not isinstance(value, (bytes, bytearray, memoryview)):
                raise TypeError(f"Value for binarydata must be bytes, got {type(value)}")

        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(f"DELETE FROM {table} WHERE key = ?", (key,))
            cur.execute(
                f"INSERT INTO {table} (key, value) VALUES (?, ?)",
                (key, value),
            )
            conn.commit()
        finally:
            conn.close()

    def delete_raw_value(self, table: str, key: str) -> None:
        if table not in ALLOWED_TABLES:
            raise ValueError(f"Table '{table}' not in allowed tables: {ALLOWED_TABLES}")

        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(f"DELETE FROM {table} WHERE key = ?", (key,))
            conn.commit()
        finally:
            conn.close()

    # --------------------------------------------------------------------------
    # Feature 6: DLC Park Unlocks
    # --------------------------------------------------------------------------

    def get_parks(self) -> dict[str, bool]:
        res: dict[str, bool] = {}
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            for p in DLC_PARKS_LIST:
                key = f"is_purchased_se.illusionlabs.skate2.{p}"
                cur.execute("SELECT value FROM integerdata WHERE key = ?", (key,))
                row = cur.fetchone()
                res[p] = bool(row[0]) if (row is not None and row[0] is not None) else False
        finally:
            conn.close()
        return res

    def set_parks(self, parks_dict: dict[str, Any]) -> None:
        if not parks_dict:
            return

        for p, v in parks_dict.items():
            if p not in DLC_PARKS_LIST:
                raise ValueError(f"Unknown DLC park identifier: {p}")
            if isinstance(v, str) or not isinstance(v, (bool, int)):
                raise TypeError(f"Value for park {p} must be boolean or 0/1, got {type(v)}")

        for p, v in parks_dict.items():
            key = f"is_purchased_se.illusionlabs.skate2.{p}"
            val = 1 if v else 0
            self.set_raw_value("integerdata", key, val)

    # --------------------------------------------------------------------------
    # Feature 7: Challenges
    # --------------------------------------------------------------------------

    _CATALOG_FILE = Path(__file__).resolve().parent / "challenge_catalog.json"
    _CHALLENGE_CATALOG: dict[str, dict[int, dict]] = {}

    @classmethod
    def _get_catalog(cls) -> dict[str, dict[int, dict]]:
        if not cls._CHALLENGE_CATALOG and cls._CATALOG_FILE.exists():
            try:
                with open(cls._CATALOG_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for p, items in raw.items():
                    cls._CHALLENGE_CATALOG[p] = {item["id"]: item for item in items}
            except Exception:
                pass
        return cls._CHALLENGE_CATALOG

    def get_challenges(self, park: str | None = None) -> list[dict[str, Any]]:
        conn = self._get_connection()
        challenges: list[dict[str, Any]] = []
        catalog = self._get_catalog()
        try:
            cur = conn.cursor()
            if park:
                cur.execute(
                    "SELECT key, value FROM integerdata WHERE key LIKE ?",
                    (f"challenge_%_location_{park}",),
                )
            else:
                cur.execute("SELECT key, value FROM integerdata WHERE key LIKE 'challenge_%'")
            pattern = re.compile(r"^challenge_(\d+)_location_([a-zA-Z0-9_]+)$")
            for row in cur.fetchall():
                k, v = row["key"], row["value"]
                m = pattern.match(k)
                if m:
                    cid = int(m.group(1))
                    pname = m.group(2)
                    if park is None or pname == park:
                        ch_dict: dict[str, Any] = {
                            "park": pname,
                            "challenge_id": cid,
                            "completed": 1 if v == 1 else 0,
                        }
                        meta = catalog.get(pname, {}).get(cid)
                        if meta:
                            ch_dict["title"] = meta.get("title", "")
                            ch_dict["description"] = meta.get("description", "")
                            ch_dict["info"] = meta.get("info", "")
                            ch_dict["duration"] = meta.get("duration", "")
                            ch_dict["requirements"] = meta.get("requirements", [])
                        challenges.append(ch_dict)
        finally:
            conn.close()

        challenges.sort(key=lambda x: (x["park"], x["challenge_id"]))
        return challenges

    def set_challenge(self, park: str, challenge_id: int, completed: int) -> None:
        if park not in ALL_PARK_NAMES:
            raise ValueError(f"Unknown skatepark name: {park}")
        if not isinstance(challenge_id, int) or challenge_id < 1 or challenge_id > 45:
            raise ValueError(f"Challenge ID must be an integer in 1..45, got {challenge_id}")
        if not isinstance(completed, int) or completed not in (0, 1):
            raise ValueError(f"Completed state must be 0 or 1, got {completed}")

        key = f"challenge_{challenge_id}_location_{park}"
        self.set_raw_value("integerdata", key, completed)

    # --------------------------------------------------------------------------
    # Feature 8: Highscores
    # --------------------------------------------------------------------------

    def get_highscores(self) -> list[dict[str, Any]]:
        conn = self._get_connection()
        scores: list[dict[str, Any]] = []
        try:
            cur = conn.cursor()
            for pid in range(9):
                comp_key = f"db_competition_skatepark{pid}"
                line_key = f"db_linescore_skatepark{pid}"
                cur.execute("SELECT value FROM integerdata WHERE key = ?", (comp_key,))
                r_comp = cur.fetchone()
                cur.execute("SELECT value FROM integerdata WHERE key = ?", (line_key,))
                r_line = cur.fetchone()
                scores.append(
                    {
                        "park_id": pid,
                        "competition": int(r_comp[0]) if r_comp and r_comp[0] is not None else 0,
                        "line": int(r_line[0]) if r_line and r_line[0] is not None else 0,
                    }
                )
        finally:
            conn.close()
        return scores

    def set_highscore(
        self,
        park_id: int,
        competition: int | None = None,
        line: int | None = None,
    ) -> None:
        if not isinstance(park_id, int) or park_id < 0 or park_id > 8:
            raise ValueError(f"Park ID must be in 0..8, got {park_id}")

        if competition is not None:
            if not isinstance(competition, int) or isinstance(competition, bool):
                raise TypeError(f"Competition score must be integer, got {type(competition)}")
            if competition < 0:
                raise ValueError(f"Competition score cannot be negative, got {competition}")
            self.set_raw_value("integerdata", f"db_competition_skatepark{park_id}", competition)

        if line is not None:
            if not isinstance(line, int) or isinstance(line, bool):
                raise TypeError(f"Line score must be integer, got {type(line)}")
            if line < 0:
                raise ValueError(f"Line score cannot be negative, got {line}")
            self.set_raw_value("integerdata", f"db_linescore_skatepark{park_id}", line)

    # --------------------------------------------------------------------------
    # Feature 9: Equipment Indices & Deck Metrics
    # --------------------------------------------------------------------------

    def get_equipment(self) -> dict[str, Any]:
        conn = self._get_connection()
        eq: dict[str, Any] = {
            "currentBoardIndex": 0,
            "currentDeckIndex": 0,
            "currentGriptapeIndex": 0,
            "currentWheelIndex": 0,
            "deck_wear_time": 0.0,
        }
        try:
            cur = conn.cursor()
            for key in ["currentBoardIndex", "currentDeckIndex", "currentGriptapeIndex", "currentWheelIndex"]:
                cur.execute("SELECT value FROM integerdata WHERE key = ?", (key,))
                r = cur.fetchone()
                if r and r[0] is not None:
                    eq[key] = int(r[0])

            cur.execute("SELECT value FROM floatdata WHERE key = 'deck_wear_time'")
            r = cur.fetchone()
            if r and r[0] is not None:
                eq["deck_wear_time"] = float(r[0])

            # Also fetch all db_metrics
            cur.execute("SELECT key, value FROM integerdata WHERE key LIKE 'db_metrics_%'")
            for row in cur.fetchall():
                eq[row[0]] = int(row[1])

            cur.execute("SELECT key, value FROM floatdata WHERE key LIKE 'db_metrics_%'")
            for row in cur.fetchall():
                eq[row[0]] = float(row[1])
        finally:
            conn.close()
        return eq

    def set_equipment(self, eq_dict: dict[str, Any]) -> None:
        for k, v in eq_dict.items():
            if k == "currentBoardIndex":
                if not isinstance(v, int) or isinstance(v, bool):
                    raise TypeError(f"{k} must be an integer")
                if v == 1 or v < 0 or v > 31:
                    raise ValueError(f"{k} must be 0 or 2..31, got {v}")
                self.set_raw_value("integerdata", k, v)
            elif k in ("currentDeckIndex", "currentGriptapeIndex", "currentWheelIndex"):
                if not isinstance(v, int) or isinstance(v, bool):
                    raise TypeError(f"{k} must be an integer")
                if v < 0:
                    raise ValueError(f"{k} cannot be negative")
                self.set_raw_value("integerdata", k, v)
            elif k == "deck_wear_time":
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    raise TypeError(f"{k} must be numeric")
                if v < 0.0:
                    raise ValueError(f"{k} cannot be negative")
                self.set_raw_value("floatdata", k, float(v))
            elif k.startswith("db_metrics_"):
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    raise TypeError(f"{k} must be numeric")
                if "_seconds_" in k or "highest_jump" in k or "dist_m" in k:
                    self.set_raw_value("floatdata", k, float(v))
                else:
                    self.set_raw_value("integerdata", k, int(v))
            else:
                if isinstance(v, float):
                    self.set_raw_value("floatdata", k, v)
                elif isinstance(v, int) and not isinstance(v, bool):
                    self.set_raw_value("integerdata", k, v)
                elif isinstance(v, str):
                    self.set_raw_value("stringdata", k, v)

    # --------------------------------------------------------------------------
    # Feature 10: Raw Explorer
    # --------------------------------------------------------------------------

    def raw_query(
        self,
        table: str,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
    ) -> dict[str, Any]:
        if table not in ALLOWED_TABLES:
            raise ValueError(f"Table '{table}' not in allowed tables: {ALLOWED_TABLES}")

        conn = self._get_connection()
        try:
            cur = conn.cursor()
            if search:
                count_query = f"SELECT count(*) FROM {table} WHERE key LIKE ?"
                cur.execute(count_query, (f"%{search}%",))
                total = cur.fetchone()[0]

                data_query = f"SELECT key, value FROM {table} WHERE key LIKE ? ORDER BY key LIMIT ? OFFSET ?"
                cur.execute(data_query, (f"%{search}%", limit, offset))
            else:
                count_query = f"SELECT count(*) FROM {table}"
                cur.execute(count_query)
                total = cur.fetchone()[0]

                data_query = f"SELECT key, value FROM {table} ORDER BY key LIMIT ? OFFSET ?"
                cur.execute(data_query, (limit, offset))

            rows: list[dict[str, Any]] = []
            for r in cur.fetchall():
                val = r[1]
                if table == "binarydata" and isinstance(val, (bytes, bytearray)):
                    val = f"<BLOB {len(val)} bytes>"
                elif table == "floatdata" and val is not None:
                    val = float(val)
                rows.append({"key": r[0], "value": val})

            return {"total": total, "limit": limit, "offset": offset, "rows": rows}
        finally:
            conn.close()

    def raw_execute(self, table: str, action: str, key: str, value: Any = None) -> None:
        if table not in ALLOWED_TABLES:
            raise ValueError(f"Table '{table}' not in allowed tables: {ALLOWED_TABLES}")
        action = action.lower()
        if action not in ("insert", "update", "delete"):
            raise ValueError(f"Action '{action}' must be insert, update, or delete")

        if action == "delete":
            self.delete_raw_value(table, key)
        else:
            self.set_raw_value(table, key, value)
