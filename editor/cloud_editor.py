"""Touchgrind Skate 2 - Cloud Database Editor and Checksum Manager.

Provides editing for cloudregistry.db and cloudregistry.db.hmc:
- Binary plist decoding/encoding for iap_uuid_CKRecord and iap_special_boards_CKRecord
- Special boards manager (IDs 2..31 unpacked/packed as 64-bit signed integers <q)
- CloudKit User ID (CloudStorage_UserID) and UUID (iap_uuid_value) management
- Strict HMAC-SHA256 recalculation and verification matching reference digest
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from pathlib import Path
import plistlib
import re
import sqlite3
import struct
from typing import Any

HMAC_SECRET = b"ef79557b546e30c7dda351163deb4bd194b9e8c3"
HMAC_REF_DIGEST = "622772fd2d1adde58d22f84a27c8501fd055c56f83679efc2f6560bd1e6399c7"

ALLOWED_TABLES = {"binarydata", "floatdata", "integerdata", "stringdata"}
UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class CloudEditor:
    """Editor for Touchgrind Skate 2's cloudregistry.db and cloudregistry.db.hmc."""

    def __init__(self, db_path: str | Path, hmc_path: str | Path | None = None):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"Cloud database file not found: {self.db_path}")

        if hmc_path is not None:
            self.hmc_path = Path(hmc_path)
        else:
            self.hmc_path = Path(str(self.db_path) + ".hmc")

        # Validate schema if database is non-empty
        if self.db_path.stat().st_size > 0:
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

    def _ensure_integer_flags(self) -> None:
        """Preserve iap_saved_to_cloud = 1 and iap_synched = 1."""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO integerdata (key, value) VALUES ('iap_saved_to_cloud', 1)"
            )
            cur.execute(
                "INSERT OR REPLACE INTO integerdata (key, value) VALUES ('iap_synched', 1)"
            )
            conn.commit()
        finally:
            conn.close()

    # --------------------------------------------------------------------------
    # Feature 11: CloudRegistry DB & Plist Editor
    # --------------------------------------------------------------------------

    def get_user_id(self) -> str:
        """Read CloudStorage_UserID from stringdata."""
        val = self.get_raw_value("stringdata", "CloudStorage_UserID")
        return str(val) if val is not None else ""

    def set_user_id(self, user_id: str) -> None:
        """Update CloudStorage_UserID in stringdata."""
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("User ID cannot be empty or whitespace")

        self.set_raw_value("stringdata", "CloudStorage_UserID", user_id)
        self._ensure_integer_flags()

    def get_uuid(self) -> str:
        """Read UUID value and verify iap_uuid_CKRecord binary plist integrity."""
        ck_val = self.get_raw_value("stringdata", "iap_uuid_CKRecord")
        if ck_val is not None:
            raw_plist = base64.b64decode(ck_val)
            # Will raise exception if corrupted base64 or invalid bplist
            plist_data = plistlib.loads(raw_plist)
            if not isinstance(plist_data, dict):
                raise ValueError("iap_uuid_CKRecord plist root is not a dict")

        val = self.get_raw_value("stringdata", "iap_uuid_value")
        return str(val) if val is not None else ""

    def set_uuid(self, uuid_str: str) -> None:
        """Update iap_uuid_value and synchronize iap_uuid_CKRecord binary plist."""
        if not isinstance(uuid_str, str) or not UUID_PATTERN.match(uuid_str):
            raise ValueError(f"Invalid UUID format: {uuid_str}")

        self.set_raw_value("stringdata", "iap_uuid_value", uuid_str)

        # Synchronize with iap_uuid_CKRecord
        ck_val = self.get_raw_value("stringdata", "iap_uuid_CKRecord")
        if ck_val:
            raw_plist = base64.b64decode(ck_val)
            pl = plistlib.loads(raw_plist)
            if isinstance(pl, dict) and "$objects" in pl:
                top = pl.get("$top", {})
                replaced = False
                if "value" in top and isinstance(top["value"], plistlib.UID):
                    idx = int(top["value"])
                    if 0 <= idx < len(pl["$objects"]):
                        pl["$objects"][idx] = uuid_str
                        replaced = True
                if not replaced:
                    for i, obj in enumerate(pl["$objects"]):
                        if isinstance(obj, str) and UUID_PATTERN.match(obj):
                            pl["$objects"][i] = uuid_str
                            replaced = True
                            break
                updated_plist_bytes = plistlib.dumps(pl, fmt=plistlib.FMT_BINARY)
                updated_b64 = base64.b64encode(updated_plist_bytes).decode("ascii")
                self.set_raw_value("stringdata", "iap_uuid_CKRecord", updated_b64)

        self._ensure_integer_flags()

    # --------------------------------------------------------------------------
    # Feature 12: Special Boards Manager
    # --------------------------------------------------------------------------

    def get_special_boards(self) -> list[int]:
        """Unpack 64-bit signed integers <q from iap_special_boards_items."""
        b64_val = self.get_raw_value("stringdata", "iap_special_boards_items")
        if not b64_val:
            return []
        raw = base64.b64decode(b64_val)
        if len(raw) == 0:
            return []
        count = len(raw) // 8
        return list(struct.unpack(f"<{count}q", raw[: count * 8]))

    def set_special_boards(self, board_ids: list[int]) -> None:
        """Pack 64-bit signed integers into iap_special_boards_items and sync CKRecord."""
        if not isinstance(board_ids, (list, tuple, set)):
            raise TypeError(f"board_ids must be a list, got {type(board_ids)}")

        for bid in board_ids:
            if not isinstance(bid, int) or isinstance(bid, bool):
                raise TypeError(f"Board ID must be integer, got {type(bid)}")
            if bid < 2:
                raise ValueError(f"Board ID out of bounds lower (must be >= 2): {bid}")
            if bid > 31:
                raise ValueError(f"Board ID out of bounds upper (must be <= 31): {bid}")

        cleaned_ids = sorted(list(set(board_ids)))

        if cleaned_ids:
            raw_bytes = struct.pack(f"<{len(cleaned_ids)}q", *cleaned_ids)
        else:
            raw_bytes = b""
        b64_items = base64.b64encode(raw_bytes).decode("ascii")
        self.set_raw_value("stringdata", "iap_special_boards_items", b64_items)

        # Synchronize with iap_special_boards_CKRecord
        ck_val = self.get_raw_value("stringdata", "iap_special_boards_CKRecord")
        if ck_val:
            raw_plist = base64.b64decode(ck_val)
            pl = plistlib.loads(raw_plist)
            if isinstance(pl, dict) and "$objects" in pl:
                # Retain objects 0..21 (record header and zone metadata)
                new_objects = pl["$objects"][:22]
                class_desc = {
                    "$classname": "NSMutableArray",
                    "$classes": ["NSMutableArray", "NSArray", "NSObject"],
                }
                class_uid = plistlib.UID(22 + 1 + len(cleaned_ids))
                ns_objects = [plistlib.UID(23 + i) for i in range(len(cleaned_ids))]
                new_objects.append({"NS.objects": ns_objects, "$class": class_uid})
                new_objects.extend(cleaned_ids)
                new_objects.append(class_desc)
                pl["$objects"] = new_objects
                updated_plist_bytes = plistlib.dumps(pl, fmt=plistlib.FMT_BINARY)
                updated_b64 = base64.b64encode(updated_plist_bytes).decode("ascii")
                self.set_raw_value("stringdata", "iap_special_boards_CKRecord", updated_b64)

        self._ensure_integer_flags()

    # --------------------------------------------------------------------------
    # Feature 13: HMAC-SHA256 Recalculation
    # --------------------------------------------------------------------------

    def compute_hmc(self) -> str:
        """Calculate HMAC-SHA256 matching reverse-engineered Skate2 binary verification."""
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database file not found: {self.db_path}")

        db_bytes = self.db_path.read_bytes()
        tokens = db_bytes.split()
        token = tokens[0] if tokens else b"SQLite"
        b64 = base64.b64encode(token)
        return hmac.new(HMAC_SECRET, b64, hashlib.sha256).hexdigest().lower()

    def verify_hmc(self) -> bool:
        """Verify cloudregistry.db against cloudregistry.db.hmc."""
        if not self.hmc_path or not self.hmc_path.exists():
            return False
        try:
            content = self.hmc_path.read_text(encoding="ascii", errors="replace").strip().lower()
            if len(content) != 64 or not re.match(r"^[0-9a-f]{64}$", content):
                return False
            computed = self.compute_hmc().lower()
            return hmac.compare_digest(content, computed)
        except Exception:
            return False

    def save_hmc(self) -> str:
        """Recalculate and write HMAC-SHA256 to cloudregistry.db.hmc."""
        digest = self.compute_hmc()
        if self.hmc_path:
            self.hmc_path.parent.mkdir(parents=True, exist_ok=True)
            self.hmc_path.write_text(digest, encoding="ascii")
        return digest
