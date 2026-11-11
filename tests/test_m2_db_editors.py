"""Touchgrind Skate 2 - Milestone 2 DB Editors Unit Test Suite.

Exclusively Python standard library (unittest, sqlite3, plistlib, hmac, hashlib, etc.).
Tests:
- Feature 5: Registry DB Typed Table Editor
- Feature 6: DLC Park Unlocks
- Feature 7: 280+ Challenges Editor
- Feature 8: Highscores Editor
- Feature 9: Equipment Indices & Deck Metrics
- Feature 10: Raw Database Explorer
- Feature 11: CloudRegistry DB & Plist Editor
- Feature 12: Special Boards Manager
- Feature 13: HMAC-SHA256 Recalculation
- REST API endpoints for Registry and Cloud operations
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import plistlib
import shutil
import socket
import sqlite3
import struct
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

from editor.registry_editor import RegistryEditor, DLC_PARKS_LIST, ALL_PARK_NAMES
from editor.cloud_editor import CloudEditor, HMAC_SECRET, HMAC_REF_DIGEST
from editor.server import Server
from editor.session import SessionManager

REPO_ROOT = Path(__file__).resolve().parent.parent
try:
    from tests.synthetic_fixtures import get_synthetic_ref_dir
    REF_SAVE_DIR = get_synthetic_ref_dir()
except Exception:
    REF_SAVE_DIR = REPO_ROOT / "saves" / "iph1"


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ==============================================================================
# Unit Tests: RegistryEditor
# ==============================================================================

class TestRegistryEditorUnit(unittest.TestCase):
    """Exhaustive unit tests for RegistryEditor."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.temp_reg = Path(self.td.name) / "registry.db"
        shutil.copyfile(REF_SAVE_DIR / "Library" / "Documents" / "registry.db", self.temp_reg)
        self.editor = RegistryEditor(str(self.temp_reg))

    def tearDown(self):
        self.td.cleanup()

    # --- Schema & File Init ---

    def test_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            RegistryEditor(Path(self.td.name) / "nonexistent.db")

    def test_corrupt_database_header(self):
        corrupt = Path(self.td.name) / "corrupt.db"
        corrupt.write_bytes(b"\x00" * 512)
        with self.assertRaises(sqlite3.DatabaseError):
            RegistryEditor(corrupt)

    def test_missing_tables_raises_error(self):
        incomplete = Path(self.td.name) / "incomplete.db"
        conn = sqlite3.connect(incomplete)
        conn.execute("CREATE TABLE integerdata (key TEXT, value INTEGER)")
        conn.close()
        with self.assertRaises(ValueError):
            RegistryEditor(incomplete)

    # --- Typed Table Accessors ---

    def test_typed_tables_crud_operations(self):
        # Insert
        self.editor.set_raw_value("stringdata", "test_str", "skate_value")
        self.editor.set_raw_value("integerdata", "test_int", 123456)
        self.editor.set_raw_value("floatdata", "test_flt", 98.765)
        self.editor.set_raw_value("binarydata", "test_bin", b"\xde\xad\xbe\xef")

        # Read
        self.assertEqual(self.editor.get_raw_value("stringdata", "test_str"), "skate_value")
        self.assertEqual(self.editor.get_raw_value("integerdata", "test_int"), 123456)
        self.assertAlmostEqual(self.editor.get_raw_value("floatdata", "test_flt"), 98.765, places=3)
        self.assertEqual(self.editor.get_raw_value("binarydata", "test_bin"), b"\xde\xad\xbe\xef")

        # Update (no duplicates)
        self.editor.set_raw_value("integerdata", "test_int", 654321)
        self.assertEqual(self.editor.get_raw_value("integerdata", "test_int"), 654321)

        # Delete
        self.editor.delete_raw_value("integerdata", "test_int")
        self.assertIsNone(self.editor.get_raw_value("integerdata", "test_int"))

    def test_typed_tables_type_enforcement(self):
        with self.assertRaises(TypeError):
            self.editor.set_raw_value("integerdata", "k", "not_int")
        with self.assertRaises(TypeError):
            self.editor.set_raw_value("integerdata", "k", True)  # bool is not int
        with self.assertRaises(TypeError):
            self.editor.set_raw_value("floatdata", "k", "not_float")
        with self.assertRaises(TypeError):
            self.editor.set_raw_value("floatdata", "k", False)
        with self.assertRaises(TypeError):
            self.editor.set_raw_value("stringdata", "k", 12345)
        with self.assertRaises(TypeError):
            self.editor.set_raw_value("binarydata", "k", "not_bytes")

    def test_disallowed_table_raises_error(self):
        with self.assertRaises(ValueError):
            self.editor.get_raw_value("sqlite_master", "k")
        with self.assertRaises(ValueError):
            self.editor.set_raw_value("sqlite_master", "k", "v")
        with self.assertRaises(ValueError):
            self.editor.delete_raw_value("sqlite_master", "k")

    def test_sql_injection_defense(self):
        payload = "test_key'; DROP TABLE integerdata; --"
        self.editor.set_raw_value("integerdata", payload, 999)
        self.assertEqual(self.editor.get_raw_value("integerdata", payload), 999)

        conn = sqlite3.connect(self.temp_reg)
        exists = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='integerdata'").fetchone()[0]
        conn.close()
        self.assertEqual(exists, 1)

    # --- DLC Park Unlocks ---

    def test_get_parks(self):
        parks = self.editor.get_parks()
        self.assertEqual(len(parks), 8)
        for p in DLC_PARKS_LIST:
            self.assertIn(p, parks)
            self.assertTrue(parks[p])

    def test_set_parks(self):
        self.editor.set_parks({"themotel": False, "megaramp": 0})
        parks = self.editor.get_parks()
        self.assertFalse(parks["themotel"])
        self.assertFalse(parks["megaramp"])
        self.assertTrue(parks["thecarpark"])

    def test_set_parks_unknown_id(self):
        with self.assertRaises(ValueError):
            self.editor.set_parks({"alien_base": True})

    def test_set_parks_type_error(self):
        with self.assertRaises(TypeError):
            self.editor.set_parks({"thecarpark": "yes"})

    def test_set_parks_empty_noop(self):
        before = self.editor.get_parks()
        self.editor.set_parks({})
        after = self.editor.get_parks()
        self.assertEqual(before, after)

    # --- Challenges Editor ---

    def test_get_challenges_count_and_filter(self):
        all_ch = self.editor.get_challenges()
        completed = [c for c in all_ch if c["completed"] == 1]
        self.assertEqual(len(completed), 233)

        by_park = self.editor.get_challenges(park="backyard")
        self.assertEqual(len(by_park), 25)
        for c in by_park:
            self.assertEqual(c["park"], "backyard")

    def test_set_challenge_toggle(self):
        self.editor.set_challenge("backyard", 26, 1)
        ch26 = [c for c in self.editor.get_challenges("backyard") if c["challenge_id"] == 26]
        self.assertEqual(len(ch26), 1)
        self.assertEqual(ch26[0]["completed"], 1)

        self.editor.set_challenge("backyard", 26, 0)
        ch26_reset = [c for c in self.editor.get_challenges("backyard") if c["challenge_id"] == 26]
        self.assertEqual(ch26_reset[0]["completed"], 0)

    def test_challenge_bounds_and_validations(self):
        with self.assertRaises(ValueError):
            self.editor.set_challenge("backyard", 0, 1)
        with self.assertRaises(ValueError):
            self.editor.set_challenge("backyard", 46, 1)
        with self.assertRaises(ValueError):
            self.editor.set_challenge("invalid_park", 1, 1)
        with self.assertRaises(ValueError):
            self.editor.set_challenge("backyard", 1, 2)

    # --- Highscores Editor ---

    def test_get_and_set_highscores(self):
        scores = self.editor.get_highscores()
        self.assertEqual(len(scores), 9)
        s0 = [s for s in scores if s["park_id"] == 0][0]
        self.assertEqual(s0["competition"], 3204021)
        self.assertEqual(s0["line"], 4206639)

        self.editor.set_highscore(0, competition=8888888)
        s0_updated = [s for s in self.editor.get_highscores() if s["park_id"] == 0][0]
        self.assertEqual(s0_updated["competition"], 8888888)
        self.assertEqual(s0_updated["line"], 4206639)

        self.editor.set_highscore(0, line=9999999)
        s0_both = [s for s in self.editor.get_highscores() if s["park_id"] == 0][0]
        self.assertEqual(s0_both["line"], 9999999)

    def test_highscore_validation(self):
        with self.assertRaises(ValueError):
            self.editor.set_highscore(-1, competition=100)
        with self.assertRaises(ValueError):
            self.editor.set_highscore(9, competition=100)
        with self.assertRaises(ValueError):
            self.editor.set_highscore(0, competition=-1)
        with self.assertRaises(TypeError):
            self.editor.set_highscore(0, competition=12.34)

    # --- Equipment & Deck Metrics ---

    def test_equipment_get_and_set(self):
        eq = self.editor.get_equipment()
        self.assertEqual(eq["currentBoardIndex"], 0)
        self.assertEqual(eq["currentDeckIndex"], 20)
        self.assertEqual(eq["currentGriptapeIndex"], 16)
        self.assertEqual(eq["currentWheelIndex"], 22)
        self.assertIsInstance(eq["deck_wear_time"], float)

        self.editor.set_equipment({
            "currentBoardIndex": 12,
            "currentDeckIndex": 8,
            "deck_wear_time": 99.5,
            "db_metrics_air_seconds_deck_20": 450.2,
        })
        eq2 = self.editor.get_equipment()
        self.assertEqual(eq2["currentBoardIndex"], 12)
        self.assertEqual(eq2["currentDeckIndex"], 8)
        self.assertAlmostEqual(eq2["deck_wear_time"], 99.5)
        self.assertAlmostEqual(eq2["db_metrics_air_seconds_deck_20"], 450.2)

    def test_equipment_bounds_validation(self):
        with self.assertRaises(ValueError):
            self.editor.set_equipment({"currentBoardIndex": 1})  # 1 is invalid
        with self.assertRaises(ValueError):
            self.editor.set_equipment({"currentBoardIndex": 32})
        with self.assertRaises(ValueError):
            self.editor.set_equipment({"currentDeckIndex": -1})
        with self.assertRaises(ValueError):
            self.editor.set_equipment({"deck_wear_time": -5.0})
        with self.assertRaises(TypeError):
            self.editor.set_equipment({"currentDeckIndex": "five"})

    # --- Raw Explorer ---

    def test_raw_query_and_execute(self):
        res = self.editor.raw_query("integerdata", limit=10, offset=0)
        self.assertEqual(len(res["rows"]), 10)
        self.assertGreater(res["total"], 200)

        # Search
        res_search = self.editor.raw_query("integerdata", search="is_purchased")
        self.assertEqual(len(res_search["rows"]), 8)

        # Raw insert
        self.editor.raw_execute("stringdata", "insert", "raw_key", "raw_val")
        self.assertEqual(self.editor.get_raw_value("stringdata", "raw_key"), "raw_val")

        # Raw update
        self.editor.raw_execute("stringdata", "update", "raw_key", "raw_val_2")
        self.assertEqual(self.editor.get_raw_value("stringdata", "raw_key"), "raw_val_2")

        # Raw delete
        self.editor.raw_execute("stringdata", "delete", "raw_key")
        self.assertIsNone(self.editor.get_raw_value("stringdata", "raw_key"))


# ==============================================================================
# Unit Tests: CloudEditor
# ==============================================================================

class TestCloudEditorUnit(unittest.TestCase):
    """Exhaustive unit tests for CloudEditor."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.temp_cloud = Path(self.td.name) / "cloudregistry.db"
        self.temp_hmc = Path(self.td.name) / "cloudregistry.db.hmc"
        shutil.copyfile(REF_SAVE_DIR / "Library" / "Application Support" / "cloudregistry.db", self.temp_cloud)
        shutil.copyfile(REF_SAVE_DIR / "Library" / "Application Support" / "cloudregistry.db.hmc", self.temp_hmc)
        self.editor = CloudEditor(str(self.temp_cloud), str(self.temp_hmc))

    def tearDown(self):
        self.td.cleanup()

    def test_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            CloudEditor(Path(self.td.name) / "nonexistent.db")

    def test_empty_file_does_not_crash(self):
        empty_f = Path(self.td.name) / "empty.db"
        empty_f.write_bytes(b"")
        ed = CloudEditor(empty_f)
        self.assertEqual(len(ed.compute_hmc()), 64)

    # --- User ID & UUID ---

    def test_user_id_read_and_update(self):
        self.assertEqual(self.editor.get_user_id(), "_00000000000000000000000000000000")
        new_uid = "_fa_new_test_uid_9876543210"
        self.editor.set_user_id(new_uid)
        self.assertEqual(self.editor.get_user_id(), new_uid)

    def test_user_id_empty_rejected(self):
        with self.assertRaises(ValueError):
            self.editor.set_user_id("")
        with self.assertRaises(ValueError):
            self.editor.set_user_id("   \t  ")

    def test_uuid_read_and_update_with_ckrecord_sync(self):
        self.assertEqual(self.editor.get_uuid(), "00000000-0000-0000-0000-000000000000")
        new_uuid = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
        self.editor.set_uuid(new_uuid)
        self.assertEqual(self.editor.get_uuid(), new_uuid)

        # Cross-check bplist
        conn = sqlite3.connect(self.temp_cloud)
        b64_val = conn.execute("SELECT value FROM stringdata WHERE key='iap_uuid_CKRecord'").fetchone()[0]
        conn.close()
        pl = plistlib.loads(base64.b64decode(b64_val))
        self.assertIn(new_uuid, pl["$objects"])

    def test_uuid_malformed_rejected(self):
        with self.assertRaises(ValueError):
            self.editor.set_uuid("not-a-valid-uuid-format")

    # --- Special Boards Manager ---

    def test_special_boards_reference(self):
        boards = self.editor.get_special_boards()
        self.assertEqual(boards, list(range(2, 32)))

    def test_set_special_boards_and_binary_packing(self):
        self.editor.set_special_boards([3, 7, 15, 25])
        self.assertEqual(self.editor.get_special_boards(), [3, 7, 15, 25])

        conn = sqlite3.connect(self.temp_cloud)
        b64_val = conn.execute("SELECT value FROM stringdata WHERE key='iap_special_boards_items'").fetchone()[0]
        conn.close()
        raw = base64.b64decode(b64_val)
        self.assertEqual(struct.unpack("<4q", raw), (3, 7, 15, 25))

    def test_set_special_boards_dedup_and_sort(self):
        self.editor.set_special_boards([20, 5, 20, 2, 5])
        self.assertEqual(self.editor.get_special_boards(), [2, 5, 20])

    def test_set_special_boards_bounds_and_types(self):
        with self.assertRaises(ValueError):
            self.editor.set_special_boards([0, 5])
        with self.assertRaises(ValueError):
            self.editor.set_special_boards([1, 5])
        with self.assertRaises(ValueError):
            self.editor.set_special_boards([5, 32])
        with self.assertRaises(TypeError):
            self.editor.set_special_boards([5, "10"])
        with self.assertRaises(TypeError):
            self.editor.set_special_boards([5, True])

    def test_special_boards_empty(self):
        self.editor.set_special_boards([])
        self.assertEqual(self.editor.get_special_boards(), [])

    # --- HMAC-SHA256 ---

    def test_compute_hmc_matches_reference(self):
        digest = self.editor.compute_hmc()
        self.assertEqual(digest, HMAC_REF_DIGEST)
        self.assertEqual(len(digest), 64)

    def test_verify_hmc_reference(self):
        self.assertTrue(self.editor.verify_hmc())

    def test_save_hmc(self):
        saved = self.editor.save_hmc()
        self.assertEqual(saved, HMAC_REF_DIGEST)
        self.assertEqual(self.temp_hmc.read_text(encoding="ascii").strip(), HMAC_REF_DIGEST)

    def test_verify_hmc_tampered_or_missing(self):
        self.temp_hmc.write_text("0" * 64)
        self.assertFalse(self.editor.verify_hmc())

        missing_hmc_ed = CloudEditor(str(self.temp_cloud), hmc_path=str(Path(self.td.name) / "none.hmc"))
        self.assertFalse(missing_hmc_ed.verify_hmc())


# ==============================================================================
# Integration Tests: Server REST Endpoints
# ==============================================================================

class TestServerM2Endpoints(unittest.TestCase):
    """End-to-end tests for all Milestone 2 server REST endpoints."""

    @classmethod
    def setUpClass(cls):
        cls.port = find_free_port()
        cls.server = Server(port=cls.port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.15)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.server.shutdown()
            cls.server.server_close()
            cls.server.session_manager.cleanup_all()
        except Exception:
            pass

    def setUp(self):
        # Create fresh session with sample save
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/session/load_sample", data=b"{}", method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.sid = data["session_id"]
        self.base = f"http://127.0.0.1:{self.port}/api/session/{self.sid}"

    def tearDown(self):
        del_req = urllib.request.Request(self.base, method="DELETE")
        try:
            with urllib.request.urlopen(del_req, timeout=3.0):
                pass
        except Exception:
            pass

    def test_rest_parks_get_and_post(self):
        # GET parks
        with urllib.request.urlopen(f"{self.base}/registry/parks", timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")
            self.assertEqual(len(data["parks"]), 8)
            self.assertTrue(all(data["parks"].values()))

        # POST lock all
        req = urllib.request.Request(f"{self.base}/registry/parks", data=json.dumps({"parks": {p: False for p in DLC_PARKS_LIST}}).encode("utf-8"), method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertFalse(any(data["parks"].values()))

        # POST unlock all
        req2 = urllib.request.Request(f"{self.base}/registry/parks", data=json.dumps({"unlock_all": True}).encode("utf-8"), method="POST")
        req2.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req2, timeout=3.0) as resp:
            data2 = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(all(data2["parks"].values()))

    def test_rest_challenges_get_and_post(self):
        # GET all challenges
        with urllib.request.urlopen(f"{self.base}/registry/challenges", timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")
            self.assertGreaterEqual(len(data["challenges"]), 200)

        # GET backyard challenges
        with urllib.request.urlopen(f"{self.base}/registry/challenges?park=backyard", timeout=3.0) as resp:
            data_by = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(len(data_by["challenges"]), 25)

        # POST single challenge update
        payload = json.dumps({"park": "backyard", "challenge_id": 26, "completed": 1}).encode("utf-8")
        req = urllib.request.Request(f"{self.base}/registry/challenges", data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")

    def test_rest_highscores_get_and_post(self):
        # GET highscores
        with urllib.request.urlopen(f"{self.base}/registry/highscores", timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")
            self.assertEqual(len(data["highscores"]), 9)

        # POST highscores update
        payload = json.dumps({"park_id": 0, "competition": 7777777, "line": 8888888}).encode("utf-8")
        req = urllib.request.Request(f"{self.base}/registry/highscores", data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")
            s0 = [s for s in data["highscores"] if s["park_id"] == 0][0]
            self.assertEqual(s0["competition"], 7777777)
            self.assertEqual(s0["line"], 8888888)

    def test_rest_equipment_get_and_post(self):
        # GET equipment
        with urllib.request.urlopen(f"{self.base}/registry/equipment", timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")
            self.assertIn("currentBoardIndex", data["equipment"])

        # POST equipment update
        payload = json.dumps({"currentBoardIndex": 18, "currentWheelIndex": 5}).encode("utf-8")
        req = urllib.request.Request(f"{self.base}/registry/equipment", data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["equipment"]["currentBoardIndex"], 18)
            self.assertEqual(data["equipment"]["currentWheelIndex"], 5)

    def test_rest_raw_query_and_execute(self):
        # GET raw query
        with urllib.request.urlopen(f"{self.base}/registry/raw?table=integerdata&limit=5", timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")
            self.assertEqual(len(data["rows"]), 5)

        # POST raw execute insert
        payload = json.dumps({"table": "stringdata", "action": "insert", "key": "rest_raw_k", "value": "rest_raw_v"}).encode("utf-8")
        req = urllib.request.Request(f"{self.base}/registry/raw", data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")

    def test_rest_cloud_data_and_update(self):
        # GET cloud data
        with urllib.request.urlopen(f"{self.base}/cloud/data", timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")
            self.assertTrue(data["hmac_valid"])
            self.assertEqual(len(data["special_boards"]), 30)

        # POST cloud update
        payload = json.dumps({"user_id": "_fa_custom_user", "special_boards": [2, 5, 10, 31]}).encode("utf-8")
        req = urllib.request.Request(f"{self.base}/cloud/update", data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["user_id"], "_fa_custom_user")
            self.assertEqual(data["special_boards"], [2, 5, 10, 31])
            self.assertTrue(data["hmac_valid"])

    def test_rest_cloud_recalculate_hmac(self):
        req = urllib.request.Request(f"{self.base}/cloud/recalculate_hmac", data=b"{}", method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")
            self.assertEqual(len(data["hmac"]), 64)


if __name__ == "__main__":
    unittest.main()
