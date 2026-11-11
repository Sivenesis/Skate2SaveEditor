"""tests/test_m1_session_server.py

Comprehensive zero-dependency unit test suite for Milestone 1:
- Batch Launcher verification (run_save_editor.bat)
- SessionManager lifecycle, normalization, sample loader, HMAC, integrity, export
- Server HTTP endpoints, REST API, static assets, CORS, error handling
"""

import base64
import hashlib
import hmac
import http.client
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import Milestone 1 modules
try:
    from editor.session import SessionManager
except ImportError:
    SessionManager = None

try:
    from editor.server import Skate2RequestHandler, ThreadingHTTPServer, EditorRequestHandler
except ImportError:
    Skate2RequestHandler = None
    ThreadingHTTPServer = None
    EditorRequestHandler = None


# =====================================================================
# Unit Tests: Batch Launcher Script
# =====================================================================

class TestBatchLauncher(unittest.TestCase):
    """Verifies run_save_editor.bat structure, banner, and commands."""

    def setUp(self):
        self.bat_path = PROJECT_ROOT / "run_save_editor.bat"

    def test_launcher_file_exists(self):
        """run_save_editor.bat must exist in project root."""
        self.assertTrue(self.bat_path.exists(), f"Missing launcher script: {self.bat_path}")

    def test_launcher_banner_present(self):
        """Batch script must contain the exact required header banner."""
        content = self.bat_path.read_text(encoding="utf-8", errors="replace")
        self.assertIn("TOUCHGRIND SKATE 2 // SAVE EDITOR", content)
        self.assertIn("====================================================", content)

    def test_launcher_python_checks(self):
        """Batch script must probe python and fallback to py -3."""
        content = self.bat_path.read_text(encoding="utf-8", errors="replace")
        self.assertIn("python --version", content)
        self.assertIn("py -3 --version", content)

    def test_launcher_browser_and_server_commands(self):
        """Batch script must launch browser to localhost:8765 and run editor.server."""
        content = self.bat_path.read_text(encoding="utf-8", errors="replace")
        self.assertIn("http://localhost:", content)
        self.assertIn("-m editor.server", content)
        self.assertIn("pause", content)


# =====================================================================
# Unit Tests: SessionManager
# =====================================================================

class TestSessionManager(unittest.TestCase):
    """Exhaustive unit test suite for editor.session.SessionManager."""

    def setUp(self):
        if SessionManager is None:
            self.skipTest("editor.session.SessionManager not yet imported")
        self.sm = SessionManager()
        self.active_sessions = []
        try:
            from tests.synthetic_fixtures import get_synthetic_ref_dir
            self.sample_dir = get_synthetic_ref_dir()
        except Exception:
            self.sample_dir = PROJECT_ROOT / "saves" / "iph1"

    def tearDown(self):
        for sid in self.active_sessions:
            try:
                self.sm.close_session(sid)
            except Exception:
                pass

    def test_create_session(self):
        """create_session must return a valid UUID and allocate an isolated staging dir."""
        sid = self.sm.create_session()
        self.active_sessions.append(sid)
        self.assertIsInstance(sid, str)
        # Validate UUID format
        parsed_uuid = uuid.UUID(sid)
        self.assertEqual(str(parsed_uuid), sid)

        staged_dir = self.sm.get_staged_dir(sid)
        self.assertIsInstance(staged_dir, Path)
        self.assertTrue(staged_dir.exists())

    def test_canonical_paths(self):
        """Path getters must return exact canonical paths within staged directory."""
        sid = self.sm.create_session()
        self.active_sessions.append(sid)
        staged = self.sm.get_staged_dir(sid)

        reg_path = self.sm.get_registry_path(sid)
        self.assertEqual(reg_path, staged / "Library" / "Documents" / "registry.db")

        cloud_path = self.sm.get_cloud_path(sid)
        self.assertEqual(cloud_path, staged / "Library" / "Application Support" / "cloudregistry.db")

        hmc_path = self.sm.get_cloud_hmc_path(sid)
        self.assertEqual(hmc_path, staged / "Library" / "Application Support" / "cloudregistry.db.hmc")

        textures_path = self.sm.get_board_textures_path(sid)
        self.assertEqual(textures_path, staged / "Library" / "Documents" / "board_textures")

        parks_dir = self.sm.get_parks_dir(sid)
        self.assertEqual(parks_dir, staged / "Library" / "Documents")

    def test_empty_session_status(self):
        """Status on fresh session must report all flags False and counts 0."""
        sid = self.sm.create_session()
        self.active_sessions.append(sid)
        status = self.sm.get_status(sid)

        self.assertEqual(status["session_id"], sid)
        self.assertFalse(status["has_registry"])
        self.assertFalse(status["has_cloud"])
        self.assertEqual(status["parks"], [])
        self.assertEqual(status["replays_count"], 0)
        self.assertEqual(status["textures_count"], 0)

    def test_load_sample_success(self):
        """load_sample must copy reference save files and report accurate status."""
        if not self.sample_dir.exists():
            self.skipTest(f"Sample directory not found: {self.sample_dir}")

        sid, count = self.sm.load_sample(sample_dir=self.sample_dir)
        self.active_sessions.append(sid)
        self.assertGreater(count, 0)

        # Verify staged files exist
        reg_path = self.sm.get_registry_path(sid)
        cloud_path = self.sm.get_cloud_path(sid)
        hmc_path = self.sm.get_cloud_hmc_path(sid)
        self.assertTrue(reg_path.exists())
        self.assertTrue(cloud_path.exists())
        self.assertTrue(hmc_path.exists())

        # Verify status
        status = self.sm.get_status(sid)
        self.assertTrue(status["has_registry"])
        self.assertTrue(status["has_cloud"])
        self.assertIn("backyard", status["parks"])
        self.assertIn("thedocks", status["parks"])
        self.assertEqual(len(status["parks"]), 9)
        self.assertGreaterEqual(status["replays_count"], 80)
        self.assertGreaterEqual(status["textures_count"], 7)

    def test_hmac_calculation_and_verification(self):
        """HMAC calculation must match reverse-engineered SHA256 digest on cloudregistry.db."""
        sid, _ = self.sm.load_sample(sample_dir=self.sample_dir)
        self.active_sessions.append(sid)

        # Expected reverse-engineered digest
        expected_digest = "622772fd2d1adde58d22f84a27c8501fd055c56f83679efc2f6560bd1e6399c7"
        hmc_path = self.sm.get_cloud_hmc_path(sid)
        stored_digest = hmc_path.read_text(encoding="ascii").strip()
        self.assertEqual(stored_digest, expected_digest)

        # Test verify_hmc
        self.assertTrue(self.sm.verify_hmc(sid))

        # Corrupt hmc and verify failure
        hmc_path.write_text("0000000000000000000000000000000000000000000000000000000000000000", encoding="ascii")
        self.assertFalse(self.sm.verify_hmc(sid))

        # Recalculate and verify recovery
        recalculated = self.sm.recalculate_hmc(sid)
        self.assertEqual(recalculated, expected_digest)
        self.assertTrue(self.sm.verify_hmc(sid))

    def test_sqlite_integrity_checks(self):
        """PRAGMA integrity_check must succeed on staged databases."""
        sid, _ = self.sm.load_sample(sample_dir=self.sample_dir)
        self.active_sessions.append(sid)

        integrity = self.sm.verify_integrity(sid)
        self.assertTrue(integrity.get("registry", False))
        self.assertTrue(integrity.get("cloud", False))

    def test_loose_file_ingestion(self):
        """Loose files must be mapped directly to canonical sandbox paths."""
        sid = self.sm.create_session()
        self.active_sessions.append(sid)

        # Ingest registry.db
        dummy_db = b"SQLite format 3\x00" + b"\x00" * 500
        path1 = self.sm.ingest_file(sid, "registry.db", dummy_db)
        self.assertTrue(self.sm.get_registry_path(sid).exists())

        # Ingest cloudregistry.db
        path2 = self.sm.ingest_file(sid, "cloudregistry.db", dummy_db)
        self.assertTrue(self.sm.get_cloud_path(sid).exists())

        # Ingest cloudregistry.db.hmc
        path3 = self.sm.ingest_file(sid, "cloudregistry.db.hmc", b"test_digest_64_chars")
        self.assertTrue(self.sm.get_cloud_hmc_path(sid).exists())

        # Ingest texture
        path4 = self.sm.ingest_file(sid, "deck_baked_deck_2.png", b"\x89PNG\r\n\x1a\n_FAKE_PNG_")
        texture_file = self.sm.get_board_textures_path(sid) / "deck_baked_deck_2.png"
        self.assertTrue(texture_file.exists())

        # Ingest current board JPEG
        path5 = self.sm.ingest_file(sid, "my_current_board_texture.jpg", b"\xff\xd8\xff_FAKE_JPEG_")
        jpg_file = self.sm.get_board_textures_path(sid) / "my_current_board_texture.jpg"
        self.assertTrue(jpg_file.exists())

    def test_archive_normalization_layout1_iph1(self):
        """Layout 1: Zip with 'iph1/' root prefix must normalize cleanly."""
        sid = self.sm.create_session()
        self.active_sessions.append(sid)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("iph1/Library/Documents/registry.db", b"SQLite format 3\x00_REG_")
            zf.writestr("iph1/Library/Application Support/cloudregistry.db", b"SQLite format 3\x00_CLOUD_")
            zf.writestr("iph1/Library/Application Support/cloudregistry.db.hmc", "622772fd2d1adde58d22f84a27c8501fd055c56f83679efc2f6560bd1e6399c7")
            zf.writestr("iph1/Library/Documents/board_textures/deck_baked_deck_2.png", b"PNG_DATA")
            zf.writestr("iph1/Library/Documents/backyard/clipcounter", b"\x01\x00\x00\x00")
        zip_bytes = buf.getvalue()

        ingested = self.sm.ingest_archive(sid, zip_bytes)
        self.assertGreater(len(ingested), 0)

        status = self.sm.get_status(sid)
        self.assertTrue(status["has_registry"])
        self.assertTrue(status["has_cloud"])
        self.assertIn("backyard", status["parks"])

    def test_archive_normalization_layout2_root(self):
        """Layout 2: Zip with root 'Library/' and 'Documents/' must normalize cleanly."""
        sid = self.sm.create_session()
        self.active_sessions.append(sid)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("Library/Documents/registry.db", b"SQLite format 3\x00_REG_")
            zf.writestr("Library/Application Support/cloudregistry.db", b"SQLite format 3\x00_CLOUD_")
            zf.writestr("Library/Application Support/cloudregistry.db.hmc", "622772fd2d1adde58d22f84a27c8501fd055c56f83679efc2f6560bd1e6399c7")
            zf.writestr("Library/Documents/dairyfactory/clipcounter", b"\x02\x00\x00\x00")
        zip_bytes = buf.getvalue()

        ingested = self.sm.ingest_archive(sid, zip_bytes)
        self.assertGreater(len(ingested), 0)

        status = self.sm.get_status(sid)
        self.assertTrue(status["has_registry"])
        self.assertTrue(status["has_cloud"])
        self.assertIn("dairyfactory", status["parks"])

    def test_archive_normalization_layout3_loose(self):
        """Layout 3: Zip with loose files at archive root must map to canonical paths."""
        sid = self.sm.create_session()
        self.active_sessions.append(sid)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("registry.db", b"SQLite format 3\x00_REG_")
            zf.writestr("cloudregistry.db", b"SQLite format 3\x00_CLOUD_")
            zf.writestr("cloudregistry.db.hmc", "622772fd2d1adde58d22f84a27c8501fd055c56f83679efc2f6560bd1e6399c7")
            zf.writestr("deck_baked_deck_9.png", b"PNG_DATA_9")
        zip_bytes = buf.getvalue()

        ingested = self.sm.ingest_archive(sid, zip_bytes)
        self.assertGreater(len(ingested), 0)

        status = self.sm.get_status(sid)
        self.assertTrue(status["has_registry"])
        self.assertTrue(status["has_cloud"])
        self.assertEqual(status["textures_count"], 1)

    def test_zip_slip_prevention(self):
        """Archives with path traversal sequences ('..') must be rejected."""
        sid = self.sm.create_session()
        self.active_sessions.append(sid)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../evil.txt", b"malicious content")
        zip_bytes = buf.getvalue()

        with self.assertRaises(ValueError):
            self.sm.ingest_archive(sid, zip_bytes)

    def test_clean_export_round_trip(self):
        """export_zip must create a verified archive with iph1 prefix that re-ingests identically."""
        sid, _ = self.sm.load_sample(sample_dir=self.sample_dir)
        self.active_sessions.append(sid)

        # Export archive
        zip_data = self.sm.export_zip(sid, iph1_format=True)
        self.assertIsInstance(zip_data, bytes)
        self.assertTrue(zip_data.startswith(b"PK\x03\x04"))

        # Verify zip structure in memory
        buf = io.BytesIO(zip_data)
        with zipfile.ZipFile(buf, "r") as zf:
            names = zf.namelist()
            self.assertTrue(any(n.startswith("iph1/Library/Documents/registry.db") for n in names))
            self.assertTrue(any(n.startswith("iph1/Library/Application Support/cloudregistry.db") for n in names))
            self.assertTrue(any(n.startswith("iph1/Library/Application Support/cloudregistry.db.hmc") for n in names))

        # Re-ingest into a new session
        sid2 = self.sm.create_session()
        self.active_sessions.append(sid2)
        self.sm.ingest_archive(sid2, zip_data)

        status1 = self.sm.get_status(sid)
        status2 = self.sm.get_status(sid2)
        self.assertEqual(status1["has_registry"], status2["has_registry"])
        self.assertEqual(status1["has_cloud"], status2["has_cloud"])
        self.assertEqual(status1["parks"], status2["parks"])
        self.assertEqual(status1["replays_count"], status2["replays_count"])
        self.assertEqual(status1["textures_count"], status2["textures_count"])

    def test_session_cleanup_and_windows_locking(self):
        """close_session must remove staged directory cleanly without WinError 32."""
        sid, _ = self.sm.load_sample(sample_dir=self.sample_dir)
        session_dir = self.sm.get_session_dir(sid)
        self.assertTrue(session_dir.exists())

        # Perform an SQLite operation to engage database handle
        conn = sqlite3.connect(str(self.sm.get_registry_path(sid)))
        res = conn.execute("SELECT count(*) FROM integerdata").fetchone()
        self.assertGreater(res[0], 0)
        conn.close()

        # Close session
        self.sm.close_session(sid)
        self.assertFalse(session_dir.exists(), f"Session directory was not deleted: {session_dir}")

    def test_registered_connection_automatic_cleanup(self):
        """close_session must flush and close registered SQLite connections without manual pre-closing."""
        sid = self.sm.create_session()
        session_dir = self.sm.get_session_dir(sid)
        self.assertTrue(session_dir.exists())

        reg_path = self.sm.get_registry_path(sid)
        conn = sqlite3.connect(str(reg_path))
        try:
            conn.execute("CREATE TABLE cleanup_test (id INTEGER, val TEXT)")
            conn.execute("INSERT INTO cleanup_test VALUES (1, 'leak_check')")
            conn.commit()

            # Register connection with SessionManager
            self.sm.register_connection(sid, conn)

            # Close session without manually calling conn.close()
            self.sm.close_session(sid)

            # Staged session directory must be deleted cleanly without WinError 32
            self.assertFalse(
                session_dir.exists(),
                f"Session directory was not deleted: {session_dir}. Registered connection was not closed.",
            )

            # Verify the connection object was closed
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")
        finally:
            try:
                conn.close()
            except Exception:
                pass


# =====================================================================
# Unit Tests: Server HTTP & REST Endpoints
# =====================================================================

class TestServerEndpoints(unittest.TestCase):
    """Integration test suite testing editor.server HTTP server on an ephemeral port."""

    @classmethod
    def setUpClass(cls):
        if Skate2RequestHandler is None or ThreadingHTTPServer is None:
            raise unittest.SkipTest("editor.server components not yet imported")

        # Bind to port 0 (OS allocates ephemeral port)
        cls.sm = SessionManager()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Skate2RequestHandler)
        cls.port = cls.server.server_address[1]
        cls.server.session_manager = cls.sm
        cls.server.RequestHandlerClass.session_manager = cls.sm

        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.05)  # Allow socket to listen

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.shutdown()
            cls.server.server_close()
            cls.thread.join(timeout=2.0)

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        """Issue HTTP request using pure Python standard library http.client."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = headers or {}
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        resp_headers = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, resp_headers, data

    def test_static_index(self):
        """GET / must return 200 with HTML content and exact header branding."""
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("content-type", "").lower())
        self.assertIn(b"TOUCHGRIND SKATE 2 // SAVE EDITOR", body)

    def test_static_css(self):
        """GET /style.css must return 200 with text/css."""
        status, headers, body = self.request("GET", "/style.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers.get("content-type", "").lower())

    def test_static_js(self):
        """GET /app.js must return 200 with application/javascript."""
        status, headers, body = self.request("GET", "/app.js")
        self.assertEqual(status, 200)
        ct = headers.get("content-type", "").lower()
        self.assertTrue("javascript" in ct or "text/javascript" in ct)

    def test_cors_preflight_and_headers(self):
        """OPTIONS preflight must return 204 with Access-Control-Allow-Origin: *."""
        status, headers, body = self.request("OPTIONS", "/api/session/create")
        self.assertIn(status, (200, 204))
        self.assertEqual(headers.get("access-control-allow-origin"), "*")
        self.assertIn("GET", headers.get("access-control-allow-methods", ""))
        self.assertIn("POST", headers.get("access-control-allow-methods", ""))

    def test_session_lifecycle_api(self):
        """Test POST create, GET status, and DELETE session API flow."""
        # 1. Create session
        status, headers, body = self.request("POST", "/api/session/create")
        self.assertIn(status, (200, 201))
        data = json.loads(body.decode("utf-8"))
        sid = data.get("session_id")
        self.assertIsNotNone(sid)

        # 2. Status
        status, headers, body = self.request("GET", f"/api/session/{sid}/status")
        self.assertEqual(status, 200)
        st_data = json.loads(body.decode("utf-8"))
        self.assertEqual(st_data["session_id"], sid)
        self.assertFalse(st_data["has_registry"])

        # 3. Delete
        status, headers, body = self.request("DELETE", f"/api/session/{sid}")
        self.assertEqual(status, 200)
        del_data = json.loads(body.decode("utf-8"))
        self.assertEqual(del_data["status"], "deleted")

        # 4. Status on deleted session must return 404
        status, headers, body = self.request("GET", f"/api/session/{sid}/status")
        self.assertEqual(status, 404)

    def test_load_sample_api(self):
        """POST /api/session/load_sample must create a session with sample files loaded."""
        status, headers, body = self.request("POST", "/api/session/load_sample")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        sid = data.get("session_id")
        self.assertIsNotNone(sid)
        self.assertGreater(data.get("files_loaded", 0), 0)

        # Verify status shows registry and cloud loaded
        status, headers, body = self.request("GET", f"/api/session/{sid}/status")
        self.assertEqual(status, 200)
        st_data = json.loads(body.decode("utf-8"))
        self.assertTrue(st_data["has_registry"])
        self.assertTrue(st_data["has_cloud"])

        # Cleanup
        self.request("DELETE", f"/api/session/{sid}")

    def test_upload_raw_file_api(self):
        """POST /api/session/<id>/upload_file with ?filename= must stage raw file."""
        # Create session
        status, _, body = self.request("POST", "/api/session/create")
        sid = json.loads(body.decode("utf-8"))["session_id"]

        # Upload dummy registry.db
        payload = b"SQLite format 3\x00_RAW_UPLOAD_"
        status, headers, body = self.request(
            "POST",
            f"/api/session/{sid}/upload_file?filename=registry.db",
            body=payload,
            headers={"Content-Type": "application/octet-stream"},
        )
        self.assertEqual(status, 200)

        # Check status reflects registry.db presence
        status, _, body = self.request("GET", f"/api/session/{sid}/status")
        st_data = json.loads(body.decode("utf-8"))
        self.assertTrue(st_data["has_registry"])

        # Cleanup
        self.request("DELETE", f"/api/session/{sid}")

    def test_upload_multipart_zip_api(self):
        """POST /api/session/<id>/upload with multipart/form-data must ingest archive."""
        # Create session
        status, _, body = self.request("POST", "/api/session/create")
        sid = json.loads(body.decode("utf-8"))["session_id"]

        # Build in-memory zip
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("registry.db", b"SQLite format 3\x00")
            zf.writestr("cloudregistry.db", b"SQLite format 3\x00")
        zip_bytes = buf.getvalue()

        # Build RFC multipart body
        boundary = "---------------------------974767299852498929531610575"
        body = (
            f"--{boundary}\r\n".encode("latin-1")
            + b'Content-Disposition: form-data; name="file"; filename="save.zip"\r\n'
            + b"Content-Type: application/zip\r\n\r\n"
            + zip_bytes
            + f"\r\n--{boundary}--\r\n".encode("latin-1")
        )

        status, headers, resp_body = self.request(
            "POST",
            f"/api/session/{sid}/upload",
            body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        self.assertEqual(status, 200)

        # Check status
        status, _, resp_body = self.request("GET", f"/api/session/{sid}/status")
        st_data = json.loads(resp_body.decode("utf-8"))
        self.assertTrue(st_data["has_registry"])
        self.assertTrue(st_data["has_cloud"])

        # Cleanup
        self.request("DELETE", f"/api/session/{sid}")

    def test_export_zip_api(self):
        """GET /api/session/<id>/export must stream clean application/zip."""
        status, _, body = self.request("POST", "/api/session/load_sample")
        sid = json.loads(body.decode("utf-8"))["session_id"]

        status, headers, zip_data = self.request("GET", f"/api/session/{sid}/export")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("content-type"), "application/zip")
        self.assertIn("attachment", headers.get("content-disposition", ""))
        self.assertTrue(zip_data.startswith(b"PK\x03\x04"))

        # Cleanup
        self.request("DELETE", f"/api/session/{sid}")

    def test_error_handling_api(self):
        """API must return proper 404, 400, and 405 JSON errors."""
        # Nonexistent session status
        status, headers, body = self.request("GET", "/api/session/nonexistent-session-id/status")
        self.assertEqual(status, 404)
        err = json.loads(body.decode("utf-8"))
        self.assertEqual(err.get("status"), "error")

        # Unknown route
        status, headers, body = self.request("GET", "/api/unknown/endpoint")
        self.assertEqual(status, 404)

        # Wrong method for known route (405 Method Not Allowed)
        status, headers, body = self.request("GET", "/api/session/create")
        self.assertEqual(status, 405)

        # Upload without filename
        status, _, body = self.request("POST", "/api/session/create")
        sid = json.loads(body.decode("utf-8"))["session_id"]

        status, headers, body = self.request("POST", f"/api/session/{sid}/upload_file", body=b"data")
        self.assertEqual(status, 400)

        self.request("DELETE", f"/api/session/{sid}")

    def test_http_keepalive_multiple_requests(self):
        """Persistent HTTP/1.1 connection must handle multiple sequential requests without body reuse or corruption."""
        sid = self.sm.create_session()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            try:
                body1 = b"PAYLOAD_FIRST_REQUEST_DATA_11111"
                conn.request(
                    "POST",
                    f"/api/session/{sid}/upload_file?filename=req1.txt",
                    body=body1,
                    headers={"Content-Length": str(len(body1))},
                )
                resp1 = conn.getresponse()
                resp1_data = resp1.read()
                self.assertEqual(resp1.status, 200)

                body2 = b"PAYLOAD_SECOND_DISTINCT_REQUEST_DATA_22222"
                conn.request(
                    "POST",
                    f"/api/session/{sid}/upload_file?filename=req2.txt",
                    body=body2,
                    headers={"Content-Length": str(len(body2))},
                )
                resp2 = conn.getresponse()
                resp2_data = resp2.read()
                self.assertEqual(resp2.status, 200)

                # Third request: verify socket remains synchronized for subsequent GET
                conn.request("GET", f"/api/session/{sid}/status")
                resp3 = conn.getresponse()
                resp3_data = resp3.read()
                self.assertEqual(resp3.status, 200)

                # Verify files staged on disk contain distinct payloads without stale body caching
                staged = self.sm.get_staged_dir(sid)
                file1_path = staged / "Library" / "Documents" / "req1.txt"
                file2_path = staged / "Library" / "Documents" / "req2.txt"

                self.assertTrue(file1_path.exists(), "req1.txt was not staged")
                self.assertTrue(file2_path.exists(), "req2.txt was not staged")
                self.assertEqual(file1_path.read_bytes(), body1)
                self.assertEqual(
                    file2_path.read_bytes(),
                    body2,
                    "Keep-alive body caching defect: req2 received stale payload from req1!",
                )
            finally:
                conn.close()
        finally:
            self.sm.close_session(sid)

    def test_empty_multipart_boundary(self):
        """Multipart upload with empty or whitespace boundary delimiter must return HTTP 400 Bad Request."""
        sid = self.sm.create_session()
        try:
            body = (
                b"--\r\n"
                b'Content-Disposition: form-data; name="file"; filename="payload.txt"\r\n'
                b"Content-Type: text/plain\r\n\r\n"
                b"line1--line2--line3\r\n"
                b"----\r\n"
            )

            # Case A: Explicit empty quotes boundary=""
            status, _, resp_body = self.request(
                "POST",
                f"/api/session/{sid}/upload",
                body=body,
                headers={"Content-Type": 'multipart/form-data; boundary=""'},
            )
            self.assertEqual(status, 400, "Empty boundary must return HTTP 400 Bad Request")
            err_data = json.loads(resp_body.decode("utf-8"))
            self.assertEqual(err_data.get("status"), "error")
            self.assertIn("boundary", err_data.get("message", "").lower())

            # Case B: Whitespace-only boundary
            status, _, resp_body = self.request(
                "POST",
                f"/api/session/{sid}/upload",
                body=body,
                headers={"Content-Type": 'multipart/form-data; boundary="   "'},
            )
            self.assertEqual(status, 400, "Whitespace boundary must return HTTP 400 Bad Request")

            # Case C: Missing boundary parameter entirely
            status, _, resp_body = self.request(
                "POST",
                f"/api/session/{sid}/upload",
                body=body,
                headers={"Content-Type": "multipart/form-data"},
            )
            self.assertEqual(status, 400, "Missing boundary parameter must return HTTP 400 Bad Request")
        finally:
            self.sm.close_session(sid)

    def test_corrupt_zip_member_payload(self):
        """Ingest archive with corrupted member payload bytes and assert ValueError with HTTP 400."""
        sid = self.sm.create_session()
        try:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(
                    "registry.db",
                    b"uncompressed_payload_string_with_enough_length_to_push_central_dir_far_away_" * 20,
                )
            data = bytearray(buf.getvalue())
            data[50:70] = b"\x00" * 20
            corrupt_zip = bytes(data)

            # 1. Direct SessionManager ingestion must raise ValueError (not raw zlib.error or BadZipFile)
            with self.assertRaises(ValueError) as ctx:
                self.sm.ingest_archive(sid, corrupt_zip)
            self.assertIn("corrupted", str(ctx.exception).lower())

            # 2. Server HTTP upload API must return HTTP 400 Bad Request (not HTTP 500)
            status, _, resp_body = self.request(
                "POST",
                f"/api/session/{sid}/upload",
                body=corrupt_zip,
                headers={"Content-Type": "application/zip"},
            )
            self.assertEqual(status, 400, "Corrupted member payload must return HTTP 400 Bad Request")
            err_data = json.loads(resp_body.decode("utf-8"))
            self.assertEqual(err_data.get("status"), "error")
            self.assertIn("corrupted", err_data.get("message", "").lower())
        finally:
            self.sm.close_session(sid)


# =====================================================================
# Main Runner
# =====================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
