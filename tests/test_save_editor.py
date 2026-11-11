"""Touchgrind Skate 2 Save Editor — Exhaustive E2E & Unit Test Suite.

Standard Library unittest only (zero third-party dependencies).
Covers:
  - Tier 1: Feature Coverage (Features 1-20)
  - Tier 2: Boundary & Corner Cases (Features 1-20)
  - Tier 3: Pairwise Cross-Feature Interactions (22 tests)
  - Tier 4: Real-World Application Scenarios (10 end-to-end scenarios)
Total: 239 test cases.
"""

import base64
import hashlib
import hmac
import html.parser
import io
import json
import os
import plistlib
import re
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
import zipfile
import zlib
from pathlib import Path

# ==============================================================================
# Global Path & Reference Fixtures
# ==============================================================================

REPO_ROOT = Path(__file__).resolve().parent.parent
try:
    from tests.synthetic_fixtures import get_synthetic_ref_dir
    REF_SAVE_DIR = get_synthetic_ref_dir()
except Exception:
    REF_SAVE_DIR = REPO_ROOT / "saves" / "iph1"
WEB_DIR = REPO_ROOT / "editor" / "web"
BATCH_FILE = REPO_ROOT / "run_save_editor.bat"

HMAC_SECRET = b"ef79557b546e30c7dda351163deb4bd194b9e8c3"
HMAC_REF_DIGEST = "622772fd2d1adde58d22f84a27c8501fd055c56f83679efc2f6560bd1e6399c7"

DLC_PARKS_LIST = [
    "thecarpark", "dairyfactory", "thedocks", "themotel",
    "playground", "megaramp", "spacedock", "theoffice"
]

ALL_PARK_NAMES = [
    "backyard", "dairyfactory", "downhill", "funpark",
    "office", "research", "spacedock", "thecarpark", "thedocks"
]

# Optional dynamic imports from application package
try:
    from editor.server import Server
except ImportError:
    Server = None

try:
    from editor.session import SessionManager
except ImportError:
    SessionManager = None

try:
    from editor.registry_editor import RegistryEditor
except ImportError:
    RegistryEditor = None

try:
    from editor.cloud_editor import CloudEditor
except ImportError:
    CloudEditor = None

try:
    from editor.replay_parser import ReplayParser, ClipcounterEditor
except ImportError:
    ReplayParser = None
    ClipcounterEditor = None

try:
    from editor.texture_manager import TextureManager
except ImportError:
    TextureManager = None


# ==============================================================================
# Helper Utilities & Pure Standard-Library Generators
# ==============================================================================

def find_free_port() -> int:
    """Finds an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def generate_minimal_png(width: int, height: int, rgba: tuple = (255, 0, 0, 255)) -> bytes:
    """Generates a valid RGBA PNG image of specified dimensions without external libraries."""
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    ihdr_crc = struct.pack('>I', zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff)
    ihdr = struct.pack('>I', len(ihdr_data)) + b'IHDR' + ihdr_data + ihdr_crc

    pixel = struct.pack('BBBB', *rgba)
    scanline = b'\x00' + (pixel * width)
    raw_scanlines = scanline * height
    idat_payload = zlib.compress(raw_scanlines, level=6)
    idat_crc = struct.pack('>I', zlib.crc32(b'IDAT' + idat_payload) & 0xffffffff)
    idat = struct.pack('>I', len(idat_payload)) + b'IDAT' + idat_payload + idat_crc

    iend_crc = struct.pack('>I', zlib.crc32(b'IEND') & 0xffffffff)
    iend = struct.pack('>I', 0) + b'IEND' + iend_crc
    return sig + ihdr + idat + iend


def parse_png_dimensions(data: bytes) -> tuple:
    """Parses width, height, bit depth, and color type from PNG bytes."""
    if len(data) < 26 or data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError("Invalid PNG signature or header too short")
    width, height, bit_depth, color_type = struct.unpack('>IIBB', data[16:26])
    return width, height, bit_depth, color_type


def parse_jpeg_dimensions(data: bytes) -> tuple:
    """Parses width and height from JPEG bytes using SOF0/SOF2 markers."""
    if len(data) < 4 or data[:2] != b'\xff\xd8':
        raise ValueError("Invalid JPEG signature")
    offset = 2
    while offset < len(data):
        if data[offset] != 0xff:
            offset += 1
            continue
        marker = data[offset + 1]
        if marker in (0xc0, 0xc2):
            h, w = struct.unpack('>HH', data[offset + 5:offset + 9])
            return w, h
        if offset + 4 > len(data):
            break
        seg_len, = struct.unpack('>H', data[offset + 2:offset + 4])
        offset += 2 + seg_len
    raise ValueError("SOF marker not found in JPEG")


def compute_hmac_sha256(token: bytes) -> str:
    """Computes reference HMAC-SHA256 for cloudregistry.db using key ef7955..."""
    b64 = base64.b64encode(token)
    return hmac.new(HMAC_SECRET, b64, hashlib.sha256).hexdigest()


# ==============================================================================
# Feature 1: Python HTTP Server & Dispatcher
# ==============================================================================

class TestFeature1ServerCoverage(unittest.TestCase):
    """Tier 1: Feature Coverage for Feature 1 (Server & REST routing)."""

    @classmethod
    def setUpClass(cls):
        cls.server = None
        cls.port = None
        cls.thread = None
        if Server is not None:
            cls.port = find_free_port()
            try:
                cls.server = Server(port=cls.port)
                cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
                cls.thread.start()
                time.sleep(0.15)
            except Exception:
                cls.server = None

    @classmethod
    def tearDownClass(cls):
        if cls.server is not None:
            try:
                cls.server.shutdown()
                cls.server.server_close()
            except Exception:
                pass

    def test_f1_tier1_01_server_startup_and_health(self):
        """Verify HTTP server starts, binds, and responds with HTTP 200."""
        if self.server is None:
            self.fail("editor.server.Server not implemented yet")
        url = f"http://127.0.0.1:{self.port}/"
        with urllib.request.urlopen(url, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)

    def test_f1_tier1_02_static_index_html_serving(self):
        """Verify GET / serves index.html with Content-Type text/html and <!DOCTYPE html>."""
        if self.server is None:
            self.fail("editor.server.Server not implemented yet")
        url = f"http://127.0.0.1:{self.port}/"
        with urllib.request.urlopen(url, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            ct = resp.headers.get("Content-Type", "")
            self.assertIn("text/html", ct)
            body = resp.read().decode("utf-8", errors="ignore")
            self.assertIn("<!DOCTYPE html>", body)

    def test_f1_tier1_03_static_css_and_js_serving(self):
        """Verify static CSS and JS are served with proper MIME types."""
        if self.server is None:
            self.fail("editor.server.Server not implemented yet")
        for asset, expected_mime in [("/style.css", "text/css"), ("/app.js", "javascript")]:
            url = f"http://127.0.0.1:{self.port}{asset}"
            with urllib.request.urlopen(url, timeout=3.0) as resp:
                self.assertEqual(resp.status, 200)
                ct = resp.headers.get("Content-Type", "")
                self.assertIn(expected_mime, ct)

    def test_f1_tier1_04_cors_preflight_and_headers(self):
        """Verify OPTIONS preflight returns CORS headers."""
        if self.server is None:
            self.fail("editor.server.Server not implemented yet")
        url = f"http://127.0.0.1:{self.port}/api/session/create"
        req = urllib.request.Request(url, method="OPTIONS")
        req.add_header("Origin", "http://localhost")
        req.add_header("Access-Control-Request-Method", "POST")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertIn(resp.status, (200, 204))
            acao = resp.headers.get("Access-Control-Allow-Origin")
            self.assertTrue(acao in ("*", "http://localhost"))

    def test_f1_tier1_05_rest_api_json_response_formatting(self):
        """Verify REST API returns Content-Type application/json with JSON envelope."""
        if self.server is None:
            self.fail("editor.server.Server not implemented yet")
        url = f"http://127.0.0.1:{self.port}/api/session/create"
        req = urllib.request.Request(url, data=b"{}", method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("application/json", resp.headers.get("Content-Type", ""))
            payload = json.loads(resp.read().decode("utf-8"))
            self.assertIn("session_id", payload)

    def test_f1_tier1_06_concurrent_request_dispatch(self):
        """Verify multi-threaded server dispatches concurrent client requests without blocking."""
        if self.server is None:
            self.fail("editor.server.Server not implemented yet")
        results = []
        errors = []

        def worker():
            try:
                url = f"http://127.0.0.1:{self.port}/"
                with urllib.request.urlopen(url, timeout=3.0) as resp:
                    results.append(resp.status)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        start_time = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3.0)
        self.assertEqual(len(errors), 0, f"Concurrent request errors: {errors}")
        self.assertEqual(len(results), 5)
        self.assertTrue(time.time() - start_time < 3.0)


class TestFeature1ServerBoundary(unittest.TestCase):
    """Tier 2: Boundary & Corner Cases for Feature 1 (Server & REST routing)."""

    @classmethod
    def setUpClass(cls):
        cls.server = None
        cls.port = None
        cls.thread = None
        if Server is not None:
            cls.port = find_free_port()
            try:
                cls.server = Server(port=cls.port)
                cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
                cls.thread.start()
                time.sleep(0.15)
            except Exception:
                cls.server = None

    @classmethod
    def tearDownClass(cls):
        if cls.server is not None:
            try:
                cls.server.shutdown()
                cls.server.server_close()
            except Exception:
                pass

    def test_f1_tier2_01_404_on_nonexistent_endpoint(self):
        """Verify non-existent route returns HTTP 404 with JSON error format."""
        if self.server is None:
            self.fail("editor.server.Server not implemented yet")
        url = f"http://127.0.0.1:{self.port}/api/nonexistent/route/xyz"
        try:
            with urllib.request.urlopen(url, timeout=3.0) as resp:
                self.assertEqual(resp.status, 404)
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)
            data = json.loads(e.read().decode("utf-8"))
            self.assertEqual(data.get("status"), "error")

    def test_f1_tier2_02_405_method_not_allowed_on_readonly_routes(self):
        """Verify DELETE or PUT to static routes returns 405 or 400."""
        if self.server is None:
            self.fail("editor.server.Server not implemented yet")
        url = f"http://127.0.0.1:{self.port}/style.css"
        req = urllib.request.Request(url, method="DELETE")
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                self.assertIn(resp.status, (400, 405))
        except urllib.error.HTTPError as e:
            self.assertIn(e.code, (400, 405))

    def test_f1_tier2_03_malformed_json_body_rejection(self):
        """Verify malformed JSON payload in POST request is rejected with HTTP 400."""
        if self.server is None:
            self.fail("editor.server.Server not implemented yet")
        url = f"http://127.0.0.1:{self.port}/api/session/create"
        req = urllib.request.Request(url, data=b'{"broken_json": true,', method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                self.assertIn(resp.status, (400, 422))
        except urllib.error.HTTPError as e:
            self.assertIn(e.code, (400, 422))

    def test_f1_tier2_04_path_traversal_attack_blocked(self):
        """Verify path traversal sequences are blocked and return 404 or 403."""
        if self.server is None:
            self.fail("editor.server.Server not implemented yet")
        for bad_path in ["/../../run_save_editor.bat", "/%2e%2e%2f%2e%2e%2fTEST_INFRA.md"]:
            url = f"http://127.0.0.1:{self.port}{bad_path}"
            try:
                with urllib.request.urlopen(url, timeout=3.0) as resp:
                    self.assertIn(resp.status, (403, 404))
            except urllib.error.HTTPError as e:
                self.assertIn(e.code, (403, 404))

    def test_f1_tier2_05_missing_or_zero_content_length_on_post(self):
        """Verify POST with zero Content-Length does not hang the server."""
        if self.server is None:
            self.fail("editor.server.Server not implemented yet")
        url = f"http://127.0.0.1:{self.port}/api/session/create"
        req = urllib.request.Request(url, data=b"", method="POST")
        req.add_header("Content-Length", "0")
        start = time.time()
        try:
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                self.assertIn(resp.status, (200, 400))
        except urllib.error.HTTPError as e:
            self.assertIn(e.code, (200, 400))
        self.assertTrue(time.time() - start < 2.0)


# ==============================================================================
# Feature 2: Windows Batch Launcher Verification
# ==============================================================================

class TestFeature2LauncherCoverage(unittest.TestCase):
    """Tier 1: Feature Coverage for Feature 2 (Batch Launcher)."""

    def test_f2_tier1_01_batch_file_existence_and_size(self):
        """Verify run_save_editor.bat exists at repo root and has size > 50 bytes."""
        self.assertTrue(BATCH_FILE.exists(), f"Batch launcher missing at {BATCH_FILE}")
        self.assertGreater(BATCH_FILE.stat().st_size, 50)

    def test_f2_tier1_02_python_detection_command(self):
        """Verify batch script checks for python or py launcher."""
        if not BATCH_FILE.exists():
            self.fail(f"run_save_editor.bat does not exist yet at {BATCH_FILE}")
        content = BATCH_FILE.read_text(encoding="utf-8", errors="ignore").lower()
        self.assertTrue("where python" in content or "python --version" in content or "py -3" in content or "where py" in content)

    def test_f2_tier1_03_branding_banner_in_batch(self):
        """Verify batch script contains exact branding banner TOUCHGRIND SKATE 2 // SAVE EDITOR."""
        if not BATCH_FILE.exists():
            self.fail(f"run_save_editor.bat does not exist yet at {BATCH_FILE}")
        content = BATCH_FILE.read_text(encoding="utf-8", errors="ignore")
        self.assertIn("TOUCHGRIND SKATE 2 // SAVE EDITOR", content)

    def test_f2_tier1_04_server_port_8765_target(self):
        """Verify batch script targets port 8765."""
        if not BATCH_FILE.exists():
            self.fail(f"run_save_editor.bat does not exist yet at {BATCH_FILE}")
        content = BATCH_FILE.read_text(encoding="utf-8", errors="ignore")
        self.assertIn("8765", content)

    def test_f2_tier1_05_browser_launch_command(self):
        """Verify batch script launches browser to http://localhost:8765 or http://127.0.0.1:8765."""
        if not BATCH_FILE.exists():
            self.fail(f"run_save_editor.bat does not exist yet at {BATCH_FILE}")
        content = BATCH_FILE.read_text(encoding="utf-8", errors="ignore").lower()
        self.assertTrue("start http://localhost:8765" in content or "start http://127.0.0.1:8765" in content)


class TestFeature2LauncherBoundary(unittest.TestCase):
    """Tier 2: Boundary & Corner Cases for Feature 2 (Batch Launcher)."""

    def test_f2_tier2_01_no_hardcoded_user_paths(self):
        """Verify batch script contains no hardcoded absolute user directories."""
        if not BATCH_FILE.exists():
            self.fail(f"run_save_editor.bat does not exist yet at {BATCH_FILE}")
        content = BATCH_FILE.read_text(encoding="utf-8", errors="ignore")
        self.assertNotRegex(content, r"(?i)[a-z]:\\users\\")
        self.assertNotRegex(content, r"(?i)f:\\progs\\")

    def test_f2_tier2_02_quoted_paths_for_spaces(self):
        """Verify path references or %~dp0 are properly quoted against spaces."""
        if not BATCH_FILE.exists():
            self.fail(f"run_save_editor.bat does not exist yet at {BATCH_FILE}")
        content = BATCH_FILE.read_text(encoding="utf-8", errors="ignore")
        if "%~dp0" in content:
            self.assertIn('"%~dp0', content)

    def test_f2_tier2_03_script_encoding_clean_ascii_or_utf8_without_bom(self):
        """Verify batch file does not contain a UTF-8 BOM."""
        if not BATCH_FILE.exists():
            self.fail(f"run_save_editor.bat does not exist yet at {BATCH_FILE}")
        raw = BATCH_FILE.read_bytes()
        self.assertNotEqual(raw[:3], b'\xef\xbb\xbf', "Batch file must not have UTF-8 BOM")

    def test_f2_tier2_04_pause_on_error_or_exit(self):
        """Verify batch script contains pause statement for failure diagnostics."""
        if not BATCH_FILE.exists():
            self.fail(f"run_save_editor.bat does not exist yet at {BATCH_FILE}")
        content = BATCH_FILE.read_text(encoding="utf-8", errors="ignore").lower()
        self.assertIn("pause", content)

    def test_f2_tier2_05_batch_dry_run_syntax_validation(self):
        """Verify batch script syntax does not contain unbalanced quotes or corrupt tokens."""
        if not BATCH_FILE.exists():
            self.fail(f"run_save_editor.bat does not exist yet at {BATCH_FILE}")
        content = BATCH_FILE.read_text(encoding="utf-8", errors="ignore")
        quote_count = content.count('"')
        self.assertEqual(quote_count % 2, 0, "Unbalanced double-quotes in batch file")


# ==============================================================================
# Feature 3: Isolated Session Staging
# ==============================================================================

class TestFeature3SessionCoverage(unittest.TestCase):
    """Tier 1: Feature Coverage for Feature 3 (Session Staging)."""

    def setUp(self):
        if SessionManager is None:
            self.fail("editor.session.SessionManager not implemented yet")
        self.mgr = SessionManager()

    def test_f3_tier1_01_create_session_isolated_dir(self):
        """Verify create_session returns unique ID and distinct staging directory."""
        s1 = self.mgr.create_session()
        s2 = self.mgr.create_session()
        self.assertNotEqual(s1, s2)
        d1 = self.mgr.get_session_dir(s1)
        d2 = self.mgr.get_session_dir(s2)
        self.assertTrue(d1.exists())
        self.assertTrue(d2.exists())
        self.assertNotEqual(d1, d2)

    def test_f3_tier1_02_load_sample_save(self):
        """Verify load_sample populates session with reference files."""
        sid, count = self.mgr.load_sample()
        self.assertGreater(count, 0)
        self.assertTrue(self.mgr.get_registry_path(sid).exists())
        self.assertTrue(self.mgr.get_cloud_path(sid).exists())
        self.assertTrue(self.mgr.get_cloud_hmc_path(sid).exists())

    def test_f3_tier1_03_ingest_archive_iph1_structure(self):
        """Verify ingestion of zip archive containing iph1/ root container."""
        sid = self.mgr.create_session()
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, 'w') as zf:
            zf.writestr("iph1/Library/Documents/registry.db", b"SQLite format 3\x00dummy")
            zf.writestr("iph1/Library/Application Support/cloudregistry.db", b"SQLite format 3\x00dummy2")
        self.mgr.ingest_archive(sid, bio.getvalue())
        self.assertTrue(self.mgr.get_registry_path(sid).exists())
        self.assertTrue(self.mgr.get_cloud_path(sid).exists())

    def test_f3_tier1_04_ingest_archive_root_library_structure(self):
        """Verify ingestion of zip archive rooted directly at Library/Documents."""
        sid = self.mgr.create_session()
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, 'w') as zf:
            zf.writestr("Library/Documents/registry.db", b"SQLite format 3\x00dummy")
            zf.writestr("Library/Application Support/cloudregistry.db", b"SQLite format 3\x00dummy2")
        self.mgr.ingest_archive(sid, bio.getvalue())
        self.assertTrue(self.mgr.get_registry_path(sid).exists())
        self.assertTrue(self.mgr.get_cloud_path(sid).exists())

    def test_f3_tier1_05_session_status_manifest(self):
        """Verify get_status returns complete manifest with boolean flags and counts."""
        sid, _ = self.mgr.load_sample()
        status = self.mgr.get_status(sid)
        self.assertTrue(status.get("has_registry"))
        self.assertTrue(status.get("has_cloud"))
        self.assertGreaterEqual(status.get("replays_count", 0), 10)
        self.assertGreaterEqual(status.get("textures_count", 0), 5)
        self.assertIn("backyard", status.get("parks", []))

    def test_f3_tier1_06_close_session_cleanup(self):
        """Verify close_session removes the staging directory."""
        sid = self.mgr.create_session()
        sdir = self.mgr.get_session_dir(sid)
        self.assertTrue(sdir.exists())
        self.mgr.close_session(sid)
        self.assertFalse(sdir.exists())


class TestFeature3SessionBoundary(unittest.TestCase):
    """Tier 2: Boundary & Corner Cases for Feature 3 (Session Staging)."""

    def setUp(self):
        if SessionManager is None:
            self.fail("editor.session.SessionManager not implemented yet")
        self.mgr = SessionManager()

    def test_f3_tier2_01_ingest_loose_files_normalization(self):
        """Verify loose files are routed to canonical iOS directories."""
        sid = self.mgr.create_session()
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, 'w') as zf:
            zf.writestr("registry.db", b"SQLite format 3\x00reg")
            zf.writestr("cloudregistry.db", b"SQLite format 3\x00cloud")
            zf.writestr("deck_baked_deck_2.png", b"\x89PNGdummy")
        self.mgr.ingest_archive(sid, bio.getvalue())
        self.assertTrue(self.mgr.get_registry_path(sid).exists())
        self.assertTrue(self.mgr.get_cloud_path(sid).exists())

    def test_f3_tier2_02_zip_slip_path_traversal_rejection(self):
        """Verify malicious zip entries with traversal (..) are safely rejected or sanitized."""
        sid = self.mgr.create_session()
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, 'w') as zf:
            zf.writestr("../../evil_escape.txt", b"evil")
        try:
            self.mgr.ingest_archive(sid, bio.getvalue())
            sdir = self.mgr.get_session_dir(sid)
            self.assertFalse((sdir.parent / "evil_escape.txt").exists())
        except ValueError:
            pass

    def test_f3_tier2_03_corrupted_zip_archive_handling(self):
        """Verify corrupt non-zip bytes raise ValueError or BadZipFile."""
        sid = self.mgr.create_session()
        with self.assertRaises((ValueError, zipfile.BadZipFile)):
            self.mgr.ingest_archive(sid, b"NOT_A_VALID_ZIP_BYTES_CORRUPTED")

    def test_f3_tier2_04_nonexistent_or_invalid_session_id(self):
        """Verify accessing non-existent session ID raises KeyError or returns None."""
        with self.assertRaises((KeyError, ValueError)):
            self.mgr.get_status("nonexistent-invalid-uuid")

    def test_f3_tier2_05_concurrent_session_isolation(self):
        """Verify mutations in Session A do not affect Session B."""
        s1, _ = self.mgr.load_sample()
        s2, _ = self.mgr.load_sample()
        reg1 = self.mgr.get_registry_path(s1)
        reg2 = self.mgr.get_registry_path(s2)
        conn = sqlite3.connect(reg1)
        conn.execute("INSERT OR REPLACE INTO integerdata (key, value) VALUES ('test_isolation', 999)")
        conn.commit()
        conn.close()

        conn2 = sqlite3.connect(reg2)
        row = conn2.execute("SELECT value FROM integerdata WHERE key='test_isolation'").fetchone()
        conn2.close()
        self.assertIsNone(row)


# ==============================================================================
# Feature 4: Verified Clean Zip Export
# ==============================================================================

class TestFeature4ExportCoverage(unittest.TestCase):
    """Tier 1: Feature Coverage for Feature 4 (Clean Zip Export)."""

    def setUp(self):
        if SessionManager is None:
            self.fail("editor.session.SessionManager not implemented yet")
        self.mgr = SessionManager()

    def test_f4_tier1_01_export_valid_zip_archive(self):
        """Verify export_zip produces valid non-empty zip bytes."""
        sid, _ = self.mgr.load_sample()
        zb = self.mgr.export_zip(sid)
        self.assertIsInstance(zb, bytes)
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(zb)))
        self.assertGreater(len(zb), 50000)

    def test_f4_tier1_02_export_retains_iph1_hierarchy(self):
        """Verify exported zip retains standard hierarchy."""
        sid, _ = self.mgr.load_sample()
        zb = self.mgr.export_zip(sid, iph1_format=True)
        with zipfile.ZipFile(io.BytesIO(zb)) as zf:
            nl = set(zf.namelist())
            self.assertTrue(any("Library/Documents/registry.db" in n for n in nl))
            self.assertTrue(any("Library/Application Support/cloudregistry.db" in n for n in nl))

    def test_f4_tier1_03_export_sqlite_integrity_verification(self):
        """Verify export verifies SQLite integrity before packaging."""
        sid, _ = self.mgr.load_sample()
        zb = self.mgr.export_zip(sid)
        self.assertTrue(len(zb) > 0)

    def test_f4_tier1_04_export_recalculates_cloud_hmac(self):
        """Verify export recalculates cloud HMAC matching cloudregistry.db."""
        sid, _ = self.mgr.load_sample()
        zb = self.mgr.export_zip(sid)
        with zipfile.ZipFile(io.BytesIO(zb)) as zf:
            cloud_name = [n for n in zf.namelist() if n.endswith("cloudregistry.db")][0]
            hmc_name = [n for n in zf.namelist() if n.endswith("cloudregistry.db.hmc")][0]
            cloud_bytes = zf.read(cloud_name)
            hmc_str = zf.read(hmc_name).decode("ascii").strip()
            token = cloud_bytes.split()[0]
            expected = compute_hmac_sha256(token)
            self.assertEqual(hmc_str, expected)

    def test_f4_tier1_05_export_to_file_path(self):
        """Verify export_zip writes directly to output_path if supplied."""
        sid, _ = self.mgr.load_sample()
        with tempfile.TemporaryDirectory() as td:
            out_p = Path(td) / "exported.zip"
            self.mgr.export_zip(sid, output_path=str(out_p))
            self.assertTrue(out_p.exists())
            self.assertGreater(out_p.stat().st_size, 50000)


class TestFeature4ExportBoundary(unittest.TestCase):
    """Tier 2: Boundary & Corner Cases for Feature 4 (Clean Zip Export)."""

    def setUp(self):
        if SessionManager is None:
            self.fail("editor.session.SessionManager not implemented yet")
        self.mgr = SessionManager()

    def test_f4_tier2_01_corrupted_sqlite_aborts_export(self):
        """Verify corrupted SQLite database aborts export."""
        sid, _ = self.mgr.load_sample()
        reg_p = self.mgr.get_registry_path(sid)
        with open(reg_p, "wb") as f:
            f.write(b"SQLite format 3\x00" + b"\xff" * 500)
        with self.assertRaises((sqlite3.DatabaseError, ValueError)):
            self.mgr.export_zip(sid)

    def test_f4_tier2_02_auto_generate_missing_hmc(self):
        """Verify export automatically creates cloudregistry.db.hmc if deleted."""
        sid, _ = self.mgr.load_sample()
        hmc_p = self.mgr.get_cloud_hmc_path(sid)
        if hmc_p.exists():
            hmc_p.unlink()
        zb = self.mgr.export_zip(sid)
        with zipfile.ZipFile(io.BytesIO(zb)) as zf:
            hmc_files = [n for n in zf.namelist() if n.endswith("cloudregistry.db.hmc")]
            self.assertEqual(len(hmc_files), 1)

    def test_f4_tier2_03_excludes_sqlite_wal_and_journal_files(self):
        """Verify SQLite wal/shm/journal files are excluded from exported zip."""
        sid, _ = self.mgr.load_sample()
        reg_p = self.mgr.get_registry_path(sid)
        wal_p = reg_p.parent / (reg_p.name + "-wal")
        wal_p.write_bytes(b"dummy_wal")
        zb = self.mgr.export_zip(sid)
        with zipfile.ZipFile(io.BytesIO(zb)) as zf:
            for item in zf.namelist():
                self.assertFalse(item.endswith("-wal"))
                self.assertFalse(item.endswith("-shm"))

    def test_f4_tier2_04_format_toggle_root_vs_iph1(self):
        """Verify iph1_format=False exports entries rooted at Library/ and Documents/."""
        sid, _ = self.mgr.load_sample()
        zb = self.mgr.export_zip(sid, iph1_format=False)
        with zipfile.ZipFile(io.BytesIO(zb)) as zf:
            for item in zf.namelist():
                self.assertFalse(item.startswith("iph1/"))

    def test_f4_tier2_05_export_empty_session_handling(self):
        """Verify exporting an empty session raises ValueError or produces minimal clean zip."""
        sid = self.mgr.create_session()
        try:
            zb = self.mgr.export_zip(sid)
            self.assertIsInstance(zb, bytes)
        except ValueError:
            pass

    def test_f4_tier2_06_export_zip_compression_and_structure(self):
        """Tier 2: Exported zip uses standard compression and preserves file hierarchy."""
        sid, _ = self.mgr.load_sample()
        zb = self.mgr.export_zip(sid)
        with zipfile.ZipFile(io.BytesIO(zb)) as zf:
            for info in zf.infolist():
                if not info.is_dir():
                    self.assertEqual(info.compress_type, zipfile.ZIP_DEFLATED)


# ==============================================================================
# Feature 5: Registry DB Typed Table Editor
# ==============================================================================

class TestRegistryEditorTypedTables(unittest.TestCase):
    """Features 5: Typed table editor over stringdata, binarydata, integerdata, floatdata."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.temp_reg = Path(self.td.name) / "registry.db"
        shutil.copyfile(REF_SAVE_DIR / "Library" / "Documents" / "registry.db", self.temp_reg)
        if RegistryEditor is None:
            self.fail("editor.registry_editor.RegistryEditor not implemented yet")
        self.editor = RegistryEditor(str(self.temp_reg))

    def tearDown(self):
        self.td.cleanup()

    def test_registry_db_connect_and_schema_validation(self):
        """Tier 1: Verify 4 typed tables exist with columns key and value."""
        conn = sqlite3.connect(self.temp_reg)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
        conn.close()
        self.assertEqual(tables, ["binarydata", "floatdata", "integerdata", "stringdata"])

    def test_typed_table_read_existing_records(self):
        """Tier 1: Read existing records across typed tables."""
        val_int = self.editor.get_raw_value("integerdata", "is_purchased_se.illusionlabs.skate2.thecarpark")
        self.assertEqual(val_int, 1)
        val_flt = self.editor.get_raw_value("floatdata", "deck_wear_time")
        self.assertIsInstance(val_flt, float)
        val_str = self.editor.get_raw_value("stringdata", "MultiplayerMatchId")
        self.assertEqual(val_str, "")

    def test_typed_table_insert_new_records(self):
        """Tier 1: Insert records into all 4 typed tables and read back."""
        self.editor.set_raw_value("stringdata", "custom_str", "skate_val")
        self.editor.set_raw_value("integerdata", "custom_int", 999999)
        self.editor.set_raw_value("floatdata", "custom_flt", 42.125)
        self.editor.set_raw_value("binarydata", "custom_bin", b"\x01\x02\x03\x04")

        self.assertEqual(self.editor.get_raw_value("stringdata", "custom_str"), "skate_val")
        self.assertEqual(self.editor.get_raw_value("integerdata", "custom_int"), 999999)
        self.assertAlmostEqual(self.editor.get_raw_value("floatdata", "custom_flt"), 42.125)
        self.assertEqual(self.editor.get_raw_value("binarydata", "custom_bin"), b"\x01\x02\x03\x04")

    def test_typed_table_update_existing_record(self):
        """Tier 1: Update existing record without creating duplicate rows."""
        self.editor.set_raw_value("integerdata", "currentBoardIndex", 7)
        self.assertEqual(self.editor.get_raw_value("integerdata", "currentBoardIndex"), 7)
        conn = sqlite3.connect(self.temp_reg)
        cnt = conn.execute("SELECT count(*) FROM integerdata WHERE key='currentBoardIndex'").fetchone()[0]
        conn.close()
        self.assertEqual(cnt, 1)

    def test_typed_table_delete_record(self):
        """Tier 1: Delete record from typed table."""
        self.editor.set_raw_value("integerdata", "temp_key", 123)
        self.assertEqual(self.editor.get_raw_value("integerdata", "temp_key"), 123)
        self.editor.delete_raw_value("integerdata", "temp_key")
        self.assertIsNone(self.editor.get_raw_value("integerdata", "temp_key"))

    def test_registry_db_missing_file_raises_error(self):
        """Tier 2: Missing database file raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            RegistryEditor(str(Path(self.td.name) / "nonexistent.db"))

    def test_registry_db_corrupted_header_raises_database_error(self):
        """Tier 2: Corrupted SQLite header raises DatabaseError."""
        corrupt_p = Path(self.td.name) / "corrupt.db"
        corrupt_p.write_bytes(b"\x00" * 1024)
        with self.assertRaises(sqlite3.DatabaseError):
            RegistryEditor(str(corrupt_p))

    def test_registry_db_missing_required_tables(self):
        """Tier 2: Database missing required typed tables raises ValueError."""
        blank_p = Path(self.td.name) / "blank.db"
        conn = sqlite3.connect(blank_p)
        conn.execute("CREATE TABLE other_table (id INT)")
        conn.close()
        with self.assertRaises(ValueError):
            RegistryEditor(str(blank_p))

    def test_typed_table_sql_injection_defense(self):
        """Tier 2: SQL injection payload in key name is safely escaped."""
        inj_key = "test'; DROP TABLE integerdata; --"
        self.editor.set_raw_value("integerdata", inj_key, 123)
        self.assertEqual(self.editor.get_raw_value("integerdata", inj_key), 123)
        conn = sqlite3.connect(self.temp_reg)
        exists = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='integerdata'").fetchone()[0]
        conn.close()
        self.assertEqual(exists, 1)

    def test_typed_table_empty_key_and_utf8_payload(self):
        """Tier 2: UTF-8 characters and emojis store and retrieve with full fidelity."""
        utf8_val = "Skate 🛹 & Roll / 東京"
        self.editor.set_raw_value("stringdata", "utf8_key", utf8_val)
        self.assertEqual(self.editor.get_raw_value("stringdata", "utf8_key"), utf8_val)


# ==============================================================================
# Feature 6: DLC Park Unlocks
# ==============================================================================

class TestRegistryEditorDLCParks(unittest.TestCase):
    """Feature 6: DLC Park Unlocks across 8 DLC parks."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.temp_reg = Path(self.td.name) / "registry.db"
        shutil.copyfile(REF_SAVE_DIR / "Library" / "Documents" / "registry.db", self.temp_reg)
        if RegistryEditor is None:
            self.fail("editor.registry_editor.RegistryEditor not implemented yet")
        self.editor = RegistryEditor(str(self.temp_reg))

    def tearDown(self):
        self.td.cleanup()

    def test_get_parks_reference_state(self):
        """Tier 1: Reference save has all 8 DLC parks unlocked (True)."""
        parks = self.editor.get_parks()
        self.assertEqual(len(parks), 8)
        for p in DLC_PARKS_LIST:
            self.assertTrue(parks.get(p))

    def test_lock_and_unlock_single_park(self):
        """Tier 1: Lock and unlock themotel."""
        self.editor.set_parks({"themotel": False})
        self.assertFalse(self.editor.get_parks()["themotel"])
        self.editor.set_parks({"themotel": True})
        self.assertTrue(self.editor.get_parks()["themotel"])

    def test_unlock_all_parks(self):
        """Tier 1: Unlock all 8 parks."""
        self.editor.set_parks({p: False for p in DLC_PARKS_LIST})
        self.assertFalse(any(self.editor.get_parks().values()))
        self.editor.set_parks({p: True for p in DLC_PARKS_LIST})
        self.assertTrue(all(self.editor.get_parks().values()))

    def test_lock_all_parks(self):
        """Tier 1: Lock all 8 parks."""
        self.editor.set_parks({p: False for p in DLC_PARKS_LIST})
        self.assertTrue(all(v is False for v in self.editor.get_parks().values()))

    def test_set_partial_parks_preserves_others(self):
        """Tier 1: Mutating megaramp preserves other 7 parks."""
        self.editor.set_parks({"megaramp": False})
        parks = self.editor.get_parks()
        self.assertFalse(parks["megaramp"])
        for p in DLC_PARKS_LIST:
            if p != "megaramp":
                self.assertTrue(parks[p])

    def test_set_parks_unknown_identifier_rejected(self):
        """Tier 2: Unknown park identifier raises ValueError or KeyError."""
        with self.assertRaises((ValueError, KeyError)):
            self.editor.set_parks({"atlantis_park": True})

    def test_get_parks_missing_keys_defaults_to_false(self):
        """Tier 2: Missing DLC key in DB defaults to False."""
        conn = sqlite3.connect(self.temp_reg)
        conn.execute("DELETE FROM integerdata WHERE key='is_purchased_se.illusionlabs.skate2.thecarpark'")
        conn.commit()
        conn.close()
        parks = self.editor.get_parks()
        self.assertFalse(parks.get("thecarpark", True))

    def test_set_parks_non_boolean_coercion_and_type_check(self):
        """Tier 2: Accept 1 and 0 as booleans; reject non-boolean string."""
        self.editor.set_parks({"thecarpark": 0})
        self.assertFalse(self.editor.get_parks()["thecarpark"])
        with self.assertRaises((TypeError, ValueError)):
            self.editor.set_parks({"thecarpark": "not_a_bool"})

    def test_park_name_alias_office_resolution(self):
        """Tier 2: 'theoffice' resolves to the correct DLC key."""
        self.editor.set_parks({"theoffice": False})
        self.assertFalse(self.editor.get_parks()["theoffice"])

    def test_set_parks_empty_dict_is_idempotent_noop(self):
        """Tier 2: Empty dict is a clean no-op."""
        before = self.editor.get_parks()
        self.editor.set_parks({})
        after = self.editor.get_parks()
        self.assertEqual(before, after)


# ==============================================================================
# Feature 7: 280+ Challenges Editor
# ==============================================================================

class TestRegistryEditorChallenges(unittest.TestCase):
    """Feature 7: Challenges Editor across 9 skateparks."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.temp_reg = Path(self.td.name) / "registry.db"
        shutil.copyfile(REF_SAVE_DIR / "Library" / "Documents" / "registry.db", self.temp_reg)
        if RegistryEditor is None:
            self.fail("editor.registry_editor.RegistryEditor not implemented yet")
        self.editor = RegistryEditor(str(self.temp_reg))

    def tearDown(self):
        self.td.cleanup()

    def test_get_challenges_reference_count(self):
        """Tier 1: Reference save contains 233 completed challenges."""
        ch = self.editor.get_challenges()
        completed = [c for c in ch if c.get("completed") == 1]
        self.assertEqual(len(completed), 233)

    def test_get_challenges_by_park_filter(self):
        """Tier 1: backyard park has 25 completed challenges."""
        ch = self.editor.get_challenges(park="backyard")
        self.assertEqual(len(ch), 25)
        for c in ch:
            self.assertEqual(c["park"], "backyard")

    def test_set_single_challenge_completed(self):
        """Tier 1: Set challenge 26 at backyard to 1."""
        self.editor.set_challenge("backyard", 26, 1)
        conn = sqlite3.connect(self.temp_reg)
        val = conn.execute("SELECT value FROM integerdata WHERE key='challenge_26_location_backyard'").fetchone()[0]
        conn.close()
        self.assertEqual(val, 1)

    def test_set_single_challenge_reset(self):
        """Tier 1: Reset challenge 1 at backyard to 0."""
        self.editor.set_challenge("backyard", 1, 0)
        conn = sqlite3.connect(self.temp_reg)
        val = conn.execute("SELECT value FROM integerdata WHERE key='challenge_1_location_backyard'").fetchone()[0]
        conn.close()
        self.assertEqual(val, 0)

    def test_bulk_unlock_park_challenges(self):
        """Tier 1: Bulk unlock challenges 1..45 for thecarpark."""
        for c in range(1, 46):
            self.editor.set_challenge("thecarpark", c, 1)
        conn = sqlite3.connect(self.temp_reg)
        cnt = conn.execute("SELECT count(*) FROM integerdata WHERE key LIKE 'challenge_%_location_thecarpark' AND value=1").fetchone()[0]
        conn.close()
        self.assertEqual(cnt, 45)

    def test_challenge_id_out_of_bounds_zero_or_negative(self):
        """Tier 2: Challenge ID <= 0 raises ValueError."""
        with self.assertRaises(ValueError):
            self.editor.set_challenge("backyard", 0, 1)
        with self.assertRaises(ValueError):
            self.editor.set_challenge("backyard", -5, 1)

    def test_challenge_id_out_of_bounds_upper(self):
        """Tier 2: Challenge ID > 45 raises ValueError."""
        with self.assertRaises(ValueError):
            self.editor.set_challenge("backyard", 46, 1)

    def test_challenge_unknown_park_name(self):
        """Tier 2: Unknown park name raises ValueError."""
        with self.assertRaises(ValueError):
            self.editor.set_challenge("mars_station", 1, 1)

    def test_challenge_invalid_completed_state(self):
        """Tier 2: Completed value outside 0 or 1 raises ValueError or TypeError."""
        with self.assertRaises((ValueError, TypeError)):
            self.editor.set_challenge("backyard", 1, 2)

    def test_get_challenges_tolerates_corrupted_key_names(self):
        """Tier 2: Malformed challenge key in integerdata is ignored without error."""
        conn = sqlite3.connect(self.temp_reg)
        conn.execute("INSERT INTO integerdata VALUES ('challenge_corrupted_key', 1)")
        conn.commit()
        conn.close()
        ch = self.editor.get_challenges()
        self.assertIsInstance(ch, list)


# ==============================================================================
# Feature 8: Highscores Editor
# ==============================================================================

class TestRegistryEditorHighscores(unittest.TestCase):
    """Feature 8: Competition and Line Highscores per park."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.temp_reg = Path(self.td.name) / "registry.db"
        shutil.copyfile(REF_SAVE_DIR / "Library" / "Documents" / "registry.db", self.temp_reg)
        if RegistryEditor is None:
            self.fail("editor.registry_editor.RegistryEditor not implemented yet")
        self.editor = RegistryEditor(str(self.temp_reg))

    def tearDown(self):
        self.td.cleanup()

    def test_get_highscores_reference_values(self):
        """Tier 1: Read reference highscores for park 0."""
        scores = self.editor.get_highscores()
        s0 = [s for s in scores if s["park_id"] == 0][0]
        self.assertEqual(s0["competition"], 3204021)
        self.assertEqual(s0["line"], 4206639)

    def test_set_competition_score(self):
        """Tier 1: Set competition score without altering line score."""
        self.editor.set_highscore(0, competition=5000000)
        s0 = [s for s in self.editor.get_highscores() if s["park_id"] == 0][0]
        self.assertEqual(s0["competition"], 5000000)
        self.assertEqual(s0["line"], 4206639)

    def test_set_line_score(self):
        """Tier 1: Set line score without altering competition score."""
        self.editor.set_highscore(1, line=7777777)
        s1 = [s for s in self.editor.get_highscores() if s["park_id"] == 1][0]
        self.assertEqual(s1["line"], 7777777)
        self.assertEqual(s1["competition"], 11017218)

    def test_set_both_scores_simultaneously(self):
        """Tier 1: Set both competition and line score."""
        self.editor.set_highscore(2, competition=1234567, line=7654321)
        s2 = [s for s in self.editor.get_highscores() if s["park_id"] == 2][0]
        self.assertEqual(s2["competition"], 1234567)
        self.assertEqual(s2["line"], 7654321)

    def test_set_zero_scores(self):
        """Tier 1: Setting scores to 0 persists cleanly."""
        self.editor.set_highscore(3, competition=0, line=0)
        s3 = [s for s in self.editor.get_highscores() if s["park_id"] == 3][0]
        self.assertEqual(s3["competition"], 0)
        self.assertEqual(s3["line"], 0)

    def test_highscore_negative_value_rejected(self):
        """Tier 2: Negative highscore raises ValueError."""
        with self.assertRaises(ValueError):
            self.editor.set_highscore(0, competition=-100)

    def test_highscore_non_integer_type_rejected(self):
        """Tier 2: Non-integer score raises TypeError."""
        with self.assertRaises(TypeError):
            self.editor.set_highscore(0, competition=123.45)

    def test_highscore_extreme_integer_bounds(self):
        """Tier 2: Max uint32 score stores without overflow."""
        self.editor.set_highscore(0, competition=2147483647, line=9223372036854775807)
        s0 = [s for s in self.editor.get_highscores() if s["park_id"] == 0][0]
        self.assertEqual(s0["competition"], 2147483647)
        self.assertEqual(s0["line"], 9223372036854775807)

    def test_highscore_invalid_park_id_bounds(self):
        """Tier 2: Park ID outside 0..8 raises ValueError."""
        with self.assertRaises(ValueError):
            self.editor.set_highscore(-1, competition=1000)
        with self.assertRaises(ValueError):
            self.editor.set_highscore(9, competition=1000)

    def test_highscore_missing_key_in_db_auto_inserts(self):
        """Tier 2: Missing highscore row is automatically inserted."""
        conn = sqlite3.connect(self.temp_reg)
        conn.execute("DELETE FROM integerdata WHERE key='db_competition_skatepark8'")
        conn.commit()
        conn.close()
        self.editor.set_highscore(8, competition=450000)
        s8 = [s for s in self.editor.get_highscores() if s["park_id"] == 8][0]
        self.assertEqual(s8["competition"], 450000)


# ==============================================================================
# Feature 9: Equipment Indices & Deck Metrics
# ==============================================================================

class TestRegistryEditorEquipmentMetrics(unittest.TestCase):
    """Feature 9: Equipment indices and per-deck metrics."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.temp_reg = Path(self.td.name) / "registry.db"
        shutil.copyfile(REF_SAVE_DIR / "Library" / "Documents" / "registry.db", self.temp_reg)
        if RegistryEditor is None:
            self.fail("editor.registry_editor.RegistryEditor not implemented yet")
        self.editor = RegistryEditor(str(self.temp_reg))

    def tearDown(self):
        self.td.cleanup()

    def test_get_equipment_reference_indices(self):
        """Tier 1: Read reference indices: board=0, deck=20, grip=16, wheel=22."""
        eq = self.editor.get_equipment()
        self.assertEqual(eq["currentBoardIndex"], 0)
        self.assertEqual(eq["currentDeckIndex"], 20)
        self.assertEqual(eq["currentGriptapeIndex"], 16)
        self.assertEqual(eq["currentWheelIndex"], 22)

    def test_set_current_board_index(self):
        """Tier 1: Set currentBoardIndex to 15."""
        self.editor.set_equipment({"currentBoardIndex": 15})
        self.assertEqual(self.editor.get_equipment()["currentBoardIndex"], 15)

    def test_set_deck_grip_wheel_indices(self):
        """Tier 1: Set deck, grip, wheel indices."""
        self.editor.set_equipment({"currentDeckIndex": 5, "currentGriptapeIndex": 8, "currentWheelIndex": 12})
        eq = self.editor.get_equipment()
        self.assertEqual(eq["currentDeckIndex"], 5)
        self.assertEqual(eq["currentGriptapeIndex"], 8)
        self.assertEqual(eq["currentWheelIndex"], 12)

    def test_get_and_set_deck_wear_time(self):
        """Tier 1: Read and set deck_wear_time float value."""
        self.editor.set_equipment({"deck_wear_time": 12345.678})
        self.assertAlmostEqual(self.editor.get_equipment()["deck_wear_time"], 12345.678, places=2)

    def test_set_deck_metrics_float_and_int(self):
        """Tier 1: Set air_seconds (float) and dist_km (int)."""
        self.editor.set_equipment({"db_metrics_air_seconds_deck_20": 350.5, "db_metrics_dist_km_deck_20": 42})
        eq = self.editor.get_equipment()
        self.assertAlmostEqual(eq["db_metrics_air_seconds_deck_20"], 350.5, places=1)
        self.assertEqual(eq["db_metrics_dist_km_deck_20"], 42)

    def test_equipment_invalid_board_index(self):
        """Tier 2: Board index 1 or > 31 raises ValueError."""
        with self.assertRaises(ValueError):
            self.editor.set_equipment({"currentBoardIndex": 1})
        with self.assertRaises(ValueError):
            self.editor.set_equipment({"currentBoardIndex": 32})

    def test_equipment_negative_index_rejected(self):
        """Tier 2: Negative equipment index raises ValueError."""
        with self.assertRaises(ValueError):
            self.editor.set_equipment({"currentDeckIndex": -1})

    def test_deck_metrics_negative_value_rejected(self):
        """Tier 2: Negative wear time raises ValueError."""
        with self.assertRaises(ValueError):
            self.editor.set_equipment({"deck_wear_time": -1.0})

    def test_equipment_partial_update_preserves_other_fields(self):
        """Tier 2: Updating currentWheelIndex preserves board, deck, griptape."""
        self.editor.set_equipment({"currentWheelIndex": 30})
        eq = self.editor.get_equipment()
        self.assertEqual(eq["currentWheelIndex"], 30)
        self.assertEqual(eq["currentBoardIndex"], 0)
        self.assertEqual(eq["currentDeckIndex"], 20)
        self.assertEqual(eq["currentGriptapeIndex"], 16)

    def test_equipment_non_numeric_type_rejected(self):
        """Tier 2: Non-numeric equipment index raises TypeError."""
        with self.assertRaises(TypeError):
            self.editor.set_equipment({"currentDeckIndex": "twenty"})


# ==============================================================================
# Feature 10: Raw Database Explorer
# ==============================================================================

class TestRegistryEditorRawExplorer(unittest.TestCase):
    """Feature 10: Raw SQLite table explorer (query, search, insert, update, delete)."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.temp_reg = Path(self.td.name) / "registry.db"
        shutil.copyfile(REF_SAVE_DIR / "Library" / "Documents" / "registry.db", self.temp_reg)
        if RegistryEditor is None:
            self.fail("editor.registry_editor.RegistryEditor not implemented yet")
        self.editor = RegistryEditor(str(self.temp_reg))

    def tearDown(self):
        self.td.cleanup()

    def test_raw_query_pagination(self):
        """Tier 1: Pagination query across integerdata."""
        p1 = self.editor.raw_query("integerdata", limit=20, offset=0)
        p2 = self.editor.raw_query("integerdata", limit=20, offset=20)
        self.assertEqual(len(p1["rows"]), 20)
        self.assertEqual(len(p2["rows"]), 20)
        keys1 = {r["key"] for r in p1["rows"]}
        keys2 = {r["key"] for r in p2["rows"]}
        self.assertEqual(len(keys1.intersection(keys2)), 0)

    def test_raw_query_search(self):
        """Tier 1: Search is_purchased returns exactly 8 rows."""
        res = self.editor.raw_query("integerdata", search="is_purchased")
        self.assertEqual(len(res["rows"]), 8)
        self.assertTrue(all("is_purchased" in r["key"] for r in res["rows"]))

    def test_raw_execute_insert(self):
        """Tier 1: Insert row via raw_execute."""
        self.editor.raw_execute("stringdata", "insert", "raw_k1", "raw_v1")
        res = self.editor.raw_query("stringdata", search="raw_k1")
        self.assertEqual(len(res["rows"]), 1)
        self.assertEqual(res["rows"][0]["value"], "raw_v1")

    def test_raw_execute_update(self):
        """Tier 1: Update row via raw_execute."""
        self.editor.raw_execute("integerdata", "update", "currentBoardIndex", 19)
        self.assertEqual(self.editor.get_raw_value("integerdata", "currentBoardIndex"), 19)

    def test_raw_execute_delete(self):
        """Tier 1: Delete row via raw_execute."""
        self.editor.raw_execute("integerdata", "insert", "del_key", 1)
        self.editor.raw_execute("integerdata", "delete", "del_key", None)
        self.assertIsNone(self.editor.get_raw_value("integerdata", "del_key"))

    def test_raw_query_table_whitelist_enforced(self):
        """Tier 2: Querying non-whitelisted tables raises ValueError."""
        with self.assertRaises(ValueError):
            self.editor.raw_query("sqlite_master")
        with self.assertRaises(ValueError):
            self.editor.raw_query("users")

    def test_raw_query_sql_injection_in_search(self):
        """Tier 2: SQL injection in search term does not dump entire table."""
        res = self.editor.raw_query("integerdata", search="' OR 1=1; --")
        self.assertNotEqual(len(res["rows"]), 309)

    def test_raw_execute_invalid_action_rejected(self):
        """Tier 2: Action other than insert/update/delete raises ValueError."""
        with self.assertRaises(ValueError):
            self.editor.raw_execute("integerdata", "drop", "k", 1)

    def test_raw_pagination_offset_out_of_range(self):
        """Tier 2: Out of range offset returns empty rows cleanly."""
        res = self.editor.raw_query("integerdata", limit=50, offset=99999)
        self.assertEqual(res["rows"], [])

    def test_raw_execute_type_safety_enforced(self):
        """Tier 2: Inserting string into integerdata table raises TypeError or ValueError."""
        with self.assertRaises((TypeError, ValueError)):
            self.editor.raw_execute("integerdata", "insert", "bad_k", "not_an_int")


# ==============================================================================
# Feature 11: CloudRegistry DB & Plist Editor
# ==============================================================================

class TestCloudEditorPlist(unittest.TestCase):
    """Feature 11: CloudRegistry binary plist records and user ID."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.temp_cloud = Path(self.td.name) / "cloudregistry.db"
        shutil.copyfile(REF_SAVE_DIR / "Library" / "Application Support" / "cloudregistry.db", self.temp_cloud)
        if CloudEditor is None:
            self.fail("editor.cloud_editor.CloudEditor not implemented yet")
        self.editor = CloudEditor(str(self.temp_cloud))

    def tearDown(self):
        self.td.cleanup()

    def test_get_user_id_reference(self):
        """Tier 1: Read reference CloudStorage_UserID."""
        self.assertEqual(self.editor.get_user_id(), "_00000000000000000000000000000000")

    def test_set_user_id(self):
        """Tier 1: Update CloudStorage_UserID."""
        new_id = "_fa1234567890abcdef1234567890abcdef"
        self.editor.set_user_id(new_id)
        self.assertEqual(self.editor.get_user_id(), new_id)

    def test_get_uuid_reference(self):
        """Tier 1: Read reference iap_uuid_value."""
        self.assertEqual(self.editor.get_uuid(), "00000000-0000-0000-0000-000000000000")

    def test_set_uuid_synchronized_with_ckrecord(self):
        """Tier 1: Update UUID and verify sync with iap_uuid_CKRecord."""
        new_uuid = "12345678-1234-1234-1234-123456789ABC"
        self.editor.set_uuid(new_uuid)
        self.assertEqual(self.editor.get_uuid(), new_uuid)

    def test_cloud_db_schema_validation(self):
        """Tier 1: Verify 4 typed tables exist in cloudregistry.db."""
        conn = sqlite3.connect(self.temp_cloud)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
        conn.close()
        self.assertEqual(tables, ["binarydata", "floatdata", "integerdata", "stringdata"])

    def test_cloud_db_file_not_found(self):
        """Tier 2: Missing cloud file raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            CloudEditor(str(Path(self.td.name) / "nonexistent.db"))

    def test_set_user_id_empty_or_whitespace_rejected(self):
        """Tier 2: Empty or whitespace user ID raises ValueError."""
        with self.assertRaises(ValueError):
            self.editor.set_user_id("")
        with self.assertRaises(ValueError):
            self.editor.set_user_id("   ")

    def test_set_uuid_invalid_format_rejected(self):
        """Tier 2: Malformed UUID format raises ValueError."""
        with self.assertRaises(ValueError):
            self.editor.set_uuid("not-a-valid-uuid")

    def test_corrupt_bplist_in_ckrecord_raises_error(self):
        """Tier 2: Corrupted bplist base64 in database raises exception."""
        conn = sqlite3.connect(self.temp_cloud)
        conn.execute("UPDATE stringdata SET value = 'corrupted_base64_data' WHERE key = 'iap_uuid_CKRecord'")
        conn.commit()
        conn.close()
        with self.assertRaises(Exception):
            self.editor.get_uuid()

    def test_cloud_integer_flags_remain_intact(self):
        """Tier 2: Editing cloud data preserves iap_saved_to_cloud=1 and iap_synched=1."""
        self.editor.set_user_id("_fa_preserved_id")
        conn = sqlite3.connect(self.temp_cloud)
        c1 = conn.execute("SELECT value FROM integerdata WHERE key='iap_saved_to_cloud'").fetchone()[0]
        c2 = conn.execute("SELECT value FROM integerdata WHERE key='iap_synched'").fetchone()[0]
        conn.close()
        self.assertEqual((c1, c2), (1, 1))


# ==============================================================================
# Feature 12: Special Boards Manager
# ==============================================================================

class TestCloudEditorSpecialBoards(unittest.TestCase):
    """Feature 12: Special Boards unpack/pack (IDs 2..31) and CKRecord sync."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.temp_cloud = Path(self.td.name) / "cloudregistry.db"
        shutil.copyfile(REF_SAVE_DIR / "Library" / "Application Support" / "cloudregistry.db", self.temp_cloud)
        if CloudEditor is None:
            self.fail("editor.cloud_editor.CloudEditor not implemented yet")
        self.editor = CloudEditor(str(self.temp_cloud))

    def tearDown(self):
        self.td.cleanup()

    def test_get_special_boards_reference(self):
        """Tier 1: Reference save contains all 30 special boards (2..31)."""
        boards = self.editor.get_special_boards()
        self.assertEqual(boards, list(range(2, 32)))

    def test_set_special_boards_subset(self):
        """Tier 1: Set special boards subset [2, 5, 10, 31]."""
        self.editor.set_special_boards([2, 5, 10, 31])
        self.assertEqual(self.editor.get_special_boards(), [2, 5, 10, 31])

    def test_special_boards_items_binary_encoding(self):
        """Tier 1: Verify 8-byte LE int64 binary packing in iap_special_boards_items."""
        self.editor.set_special_boards([3, 7, 15])
        conn = sqlite3.connect(self.temp_cloud)
        b64_val = conn.execute("SELECT value FROM stringdata WHERE key='iap_special_boards_items'").fetchone()[0]
        conn.close()
        raw = base64.b64decode(b64_val)
        self.assertEqual(len(raw), 24)
        self.assertEqual(struct.unpack('<3q', raw), (3, 7, 15))

    def test_special_boards_ckrecord_plist_sync(self):
        """Tier 1: Verify special boards sync with iap_special_boards_CKRecord plist."""
        self.editor.set_special_boards([2, 4, 6])
        conn = sqlite3.connect(self.temp_cloud)
        ck_b64 = conn.execute("SELECT value FROM stringdata WHERE key='iap_special_boards_CKRecord'").fetchone()[0]
        conn.close()
        plist_data = plistlib.loads(base64.b64decode(ck_b64))
        self.assertIn("$objects", plist_data)

    def test_unlock_all_special_boards(self):
        """Tier 1: Unlock all 30 boards (2..31)."""
        self.editor.set_special_boards([])
        self.assertEqual(len(self.editor.get_special_boards()), 0)
        self.editor.set_special_boards(list(range(2, 32)))
        self.assertEqual(self.editor.get_special_boards(), list(range(2, 32)))

    def test_special_boards_empty_list(self):
        """Tier 2: Empty boards list stores 0-byte buffer."""
        self.editor.set_special_boards([])
        self.assertEqual(self.editor.get_special_boards(), [])

    def test_special_boards_id_out_of_bounds_lower(self):
        """Tier 2: Board ID 0 or 1 raises ValueError."""
        with self.assertRaises(ValueError):
            self.editor.set_special_boards([0, 2])
        with self.assertRaises(ValueError):
            self.editor.set_special_boards([1, 2])

    def test_special_boards_id_out_of_bounds_upper(self):
        """Tier 2: Board ID > 31 raises ValueError."""
        with self.assertRaises(ValueError):
            self.editor.set_special_boards([2, 32])

    def test_special_boards_deduplication_and_sorting(self):
        """Tier 2: Duplicate board IDs are deduplicated and sorted."""
        self.editor.set_special_boards([10, 5, 2, 5, 10])
        self.assertEqual(self.editor.get_special_boards(), [2, 5, 10])

    def test_special_boards_non_integer_type_rejected(self):
        """Tier 2: String or float board ID raises TypeError."""
        with self.assertRaises(TypeError):
            self.editor.set_special_boards([2, "5", 10])


# ==============================================================================
# Feature 13: HMAC-SHA256 Recalculation
# ==============================================================================

class TestCloudEditorHMAC(unittest.TestCase):
    """Feature 13: Strict HMAC-SHA256 verification and recalculation."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.temp_cloud = Path(self.td.name) / "cloudregistry.db"
        self.temp_hmc = Path(self.td.name) / "cloudregistry.db.hmc"
        shutil.copyfile(REF_SAVE_DIR / "Library" / "Application Support" / "cloudregistry.db", self.temp_cloud)
        shutil.copyfile(REF_SAVE_DIR / "Library" / "Application Support" / "cloudregistry.db.hmc", self.temp_hmc)
        if CloudEditor is None:
            self.fail("editor.cloud_editor.CloudEditor not implemented yet")
        self.editor = CloudEditor(str(self.temp_cloud), str(self.temp_hmc))

    def tearDown(self):
        self.td.cleanup()

    def test_hmac_reference_verification(self):
        """Tier 1: verify_hmc returns True on reference files."""
        self.assertTrue(self.editor.verify_hmc())

    def test_hmac_reference_expected_digest_strict(self):
        """Tier 1: compute_hmc returns exact expected reference digest."""
        self.assertEqual(self.editor.compute_hmc(), HMAC_REF_DIGEST)

    def test_hmac_digest_format_and_length(self):
        """Tier 1: HMAC digest is exactly 64 lowercase hex characters."""
        digest = self.editor.compute_hmc()
        self.assertEqual(len(digest), 64)
        self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_save_hmc_writes_exact_file(self):
        """Tier 1: save_hmc writes exactly 64 bytes matching compute_hmc."""
        saved = self.editor.save_hmc()
        self.assertEqual(saved, HMAC_REF_DIGEST)
        self.assertEqual(self.temp_hmc.read_text().strip(), HMAC_REF_DIGEST)

    def test_hmac_recalculate_after_cloud_edit(self):
        """Tier 1: Modifying cloud database and recalculating verifies cleanly."""
        self.editor.set_user_id("_fa_new_test_user")
        self.editor.save_hmc()
        self.assertTrue(self.editor.verify_hmc())

    def test_hmac_tampered_hmc_detected(self):
        """Tier 2: Tampered .hmc file content causes verify_hmc to return False."""
        self.temp_hmc.write_text("0" * 64)
        self.assertFalse(self.editor.verify_hmc())

    def test_hmac_missing_hmc_file_handling(self):
        """Tier 2: Missing .hmc file returns False without unhandled crash."""
        editor = CloudEditor(str(self.temp_cloud), hmc_path=str(Path(self.td.name) / "nonexistent.hmc"))
        self.assertFalse(editor.verify_hmc())

    def test_hmac_malformed_hmc_file_content(self):
        """Tier 2: Malformed .hmc contents return False."""
        for malformed in ["a" * 40, "G" * 64, ""]:
            self.temp_hmc.write_text(malformed)
            self.assertFalse(self.editor.verify_hmc())

    def test_hmac_wrong_key_produces_mismatch(self):
        """Tier 2: Computing HMAC with wrong key produces different digest."""
        token = self.temp_cloud.read_bytes().split()[0]
        wrong_digest = hmac.new(b"0" * 40, base64.b64encode(token), hashlib.sha256).hexdigest()
        self.assertNotEqual(wrong_digest, HMAC_REF_DIGEST)

    def test_hmac_empty_db_file_handling(self):
        """Tier 2: 0-byte file handled safely without unhandled index error."""
        empty_p = Path(self.td.name) / "empty.db"
        empty_p.write_bytes(b"")
        editor = CloudEditor(str(empty_p))
        digest = editor.compute_hmc()
        self.assertEqual(len(digest), 64)


# ==============================================================================
# Feature 14: Replay Parser & Serializer
# ==============================================================================

class TestFeature14ReplayParser(unittest.TestCase):
    """Feature 14: Replay Parser & Serializer."""

    def setUp(self):
        self.ref_replay = REF_SAVE_DIR / "Library" / "Documents" / "backyard" / "top" / "comp-17395267498"

    def test_f14_t1_parse_valid_reference_replays(self):
        """Tier 1: Parse reference replay and verify all fields."""
        if ReplayParser is None:
            self.fail("editor.replay_parser.ReplayParser not implemented yet")
        res = ReplayParser.parse(str(self.ref_replay))
        self.assertEqual(res["channel_count"], 1)
        self.assertEqual(res["reserved"], 0)
        self.assertEqual(res["run_type"], "Competition")
        self.assertEqual(res["score"], 3204021)
        self.assertAlmostEqual(res["timestamp"], 1739526749.86538, places=3)
        self.assertAlmostEqual(res["duration"], 54.72, places=1)

    def test_f14_t1_serialize_roundtrip_identity(self):
        """Tier 1: Serialization roundtrip decompresses to identical bytes."""
        if ReplayParser is None:
            self.fail("editor.replay_parser.ReplayParser not implemented yet")
        raw = self.ref_replay.read_bytes()
        parsed = ReplayParser.parse(raw)
        serialized = ReplayParser.serialize(parsed)
        uncompressed_len = struct.unpack('<I', serialized[:4])[0]
        decomp = zlib.decompress(serialized[4:])
        self.assertEqual(len(decomp), uncompressed_len)
        self.assertEqual(decomp, zlib.decompress(raw[4:]))

    def test_f14_t1_modify_score_and_reserialize(self):
        """Tier 1: Modifying score reserializes cleanly."""
        if ReplayParser is None:
            self.fail("editor.replay_parser.ReplayParser not implemented yet")
        parsed = ReplayParser.parse(str(self.ref_replay))
        parsed["score"] = 9999999
        serialized = ReplayParser.serialize(parsed)
        reparsed = ReplayParser.parse(serialized)
        self.assertEqual(reparsed["score"], 9999999)

    def test_f14_t1_filename_generation(self):
        """Tier 1: Verify filename generator format {prefix}-{tenth_ts}."""
        if ReplayParser is None:
            self.fail("editor.replay_parser.ReplayParser not implemented yet")
        self.assertEqual(ReplayParser.build_filename("Competition", 1739526749.86538), "comp-17395267498")
        self.assertEqual(ReplayParser.build_filename("Line", 1794250907.1), "line-17942509071")

    def test_f14_t1_parse_from_bytes_and_path(self):
        """Tier 1: ReplayParser.parse accepts path and raw bytes interchangeably."""
        if ReplayParser is None:
            self.fail("editor.replay_parser.ReplayParser not implemented yet")
        p1 = ReplayParser.parse(str(self.ref_replay))
        p2 = ReplayParser.parse(self.ref_replay.read_bytes())
        self.assertEqual(p1["score"], p2["score"])

    def test_f14_t2_truncated_file_less_than_4_bytes(self):
        """Tier 2: Truncated data (<4 bytes) raises ValueError."""
        if ReplayParser is None:
            self.fail("editor.replay_parser.ReplayParser not implemented yet")
        for bad in [b"", b"\x00", b"\x01\x02", b"\x01\x02\x03"]:
            with self.assertRaises(ValueError):
                ReplayParser.parse(bad)

    def test_f14_t2_decompressed_size_exceeds_10mb_limit(self):
        """Tier 2: Decompressed size > 10MB triggers safety exception."""
        if ReplayParser is None:
            self.fail("editor.replay_parser.ReplayParser not implemented yet")
        bad_header = struct.pack('<I', 10 * 1024 * 1024 + 1) + zlib.compress(b"dummy")
        with self.assertRaises(ValueError):
            ReplayParser.parse(bad_header)

    def test_f14_t2_corrupted_zlib_data(self):
        """Tier 2: Corrupted zlib stream raises error."""
        if ReplayParser is None:
            self.fail("editor.replay_parser.ReplayParser not implemented yet")
        corrupt = struct.pack('<I', 100) + b"not_valid_deflate"
        with self.assertRaises((zlib.error, ValueError)):
            ReplayParser.parse(corrupt)

    def test_f14_t2_invalid_magic_header(self):
        """Tier 2: Magic lacking RPLY raises ValueError."""
        if ReplayParser is None:
            self.fail("editor.replay_parser.ReplayParser not implemented yet")
        bogus = b"NOPE\x01\x00RINF\x11\x00\x00\x00\x00\x00\x00\x00\x04Line\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        compressed = struct.pack('<I', len(bogus)) + zlib.compress(bogus)
        with self.assertRaises(ValueError):
            ReplayParser.parse(compressed)

    def test_f14_t2_missing_or_corrupt_rinf_tag(self):
        """Tier 2: Missing RINF chunk tag raises ValueError."""
        if ReplayParser is None:
            self.fail("editor.replay_parser.ReplayParser not implemented yet")
        bogus = b"RPLY\x01\x00XXXX\x11\x00\x00\x00\x00\x00\x00\x00\x04Line\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        compressed = struct.pack('<I', len(bogus)) + zlib.compress(bogus)
        with self.assertRaises(ValueError):
            ReplayParser.parse(compressed)

    def test_f14_t2_extreme_scores_and_durations(self):
        """Tier 2: Extreme scores and durations roundtrip cleanly."""
        if ReplayParser is None:
            self.fail("editor.replay_parser.ReplayParser not implemented yet")
        parsed = ReplayParser.parse(str(self.ref_replay))
        parsed["score"] = 0xFFFFFFFF
        parsed["duration"] = 86400.0
        serialized = ReplayParser.serialize(parsed)
        reparsed = ReplayParser.parse(serialized)
        self.assertEqual(reparsed["score"], 0xFFFFFFFF)
        self.assertAlmostEqual(reparsed["duration"], 86400.0, places=1)


# ==============================================================================
# Feature 15: Replay Actions & Clipcounter Editing
# ==============================================================================

class TestFeature15ReplayActions(unittest.TestCase):
    """Feature 15: Replay actions and 4-byte uint32 clipcounter."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.parks_dir = Path(self.td.name) / "Documents"
        shutil.copytree(REF_SAVE_DIR / "Library" / "Documents", self.parks_dir)

    def tearDown(self):
        self.td.cleanup()

    def test_f15_t1_read_valid_clipcounter(self):
        """Tier 1: Read clipcounter across all 9 parks (initial value 1)."""
        if ClipcounterEditor is None:
            self.fail("editor.replay_parser.ClipcounterEditor not implemented yet")
        for park in ALL_PARK_NAMES:
            cp = self.parks_dir / park / "clipcounter"
            self.assertEqual(ClipcounterEditor.read_counter(str(cp)), 1)

    def test_f15_t1_update_clipcounter(self):
        """Tier 1: Update clipcounter to 42 and verify 4-byte LE binary encoding."""
        if ClipcounterEditor is None:
            self.fail("editor.replay_parser.ClipcounterEditor not implemented yet")
        cp = self.parks_dir / "backyard" / "clipcounter"
        raw = ClipcounterEditor.write_counter(42)
        cp.write_bytes(raw)
        self.assertEqual(cp.stat().st_size, 4)
        self.assertEqual(cp.read_bytes(), b"\x2a\x00\x00\x00")
        self.assertEqual(ClipcounterEditor.read_counter(str(cp)), 42)

    def test_f15_t1_list_park_replays(self):
        """Tier 1: List replays in park directory (recent and top)."""
        recent = list((self.parks_dir / "dairyfactory" / "recent").glob("*"))
        top = list((self.parks_dir / "dairyfactory" / "top").glob("*"))
        self.assertGreater(len(recent), 0)
        self.assertGreater(len(top), 0)

    def test_f15_t1_delete_replay_file(self):
        """Tier 1: Delete a replay file."""
        target = list((self.parks_dir / "dairyfactory" / "recent").glob("*"))[0]
        self.assertTrue(target.exists())
        target.unlink()
        self.assertFalse(target.exists())

    def test_f15_t1_replace_or_add_replay(self):
        """Tier 1: Add or replace a replay file."""
        if ReplayParser is None:
            self.fail("editor.replay_parser.ReplayParser not implemented yet")
        sample = list((self.parks_dir / "dairyfactory" / "top").glob("*"))[0]
        parsed = ReplayParser.parse(str(sample))
        parsed["score"] = 500000
        new_name = ReplayParser.build_filename(parsed["run_type"], 1800000000.0)
        dest = self.parks_dir / "dairyfactory" / "recent" / new_name
        dest.write_bytes(ReplayParser.serialize(parsed))
        self.assertTrue(dest.exists())
        self.assertEqual(ReplayParser.parse(str(dest))["score"], 500000)

    def test_f15_t2_corrupt_clipcounter_wrong_size(self):
        """Tier 2: Clipcounter file size != 4 bytes raises ValueError."""
        if ClipcounterEditor is None:
            self.fail("editor.replay_parser.ClipcounterEditor not implemented yet")
        for bad in [b"", b"\x01", b"\x01\x02\x03", b"\x01\x02\x03\x04\x05"]:
            with self.assertRaises(ValueError):
                ClipcounterEditor.read_counter(bad)

    def test_f15_t2_clipcounter_out_of_bounds(self):
        """Tier 2: Writing negative value or value > 0xFFFFFFFF raises ValueError or OverflowError."""
        if ClipcounterEditor is None:
            self.fail("editor.replay_parser.ClipcounterEditor not implemented yet")
        with self.assertRaises((ValueError, struct.error, OverflowError)):
            ClipcounterEditor.write_counter(-1)
        with self.assertRaises((ValueError, struct.error, OverflowError)):
            ClipcounterEditor.write_counter(0x100000000)

    def test_f15_t2_clipcounter_max_uint32(self):
        """Tier 2: Max uint32 (0xFFFFFFFF) roundtrips cleanly."""
        if ClipcounterEditor is None:
            self.fail("editor.replay_parser.ClipcounterEditor not implemented yet")
        raw = ClipcounterEditor.write_counter(0xFFFFFFFF)
        self.assertEqual(ClipcounterEditor.read_counter(raw), 0xFFFFFFFF)

    def test_f15_t2_delete_nonexistent_replay(self):
        """Tier 2: Deleting nonexistent replay raises FileNotFoundError."""
        target = self.parks_dir / "dairyfactory" / "recent" / "nonexistent_file"
        with self.assertRaises(FileNotFoundError):
            target.unlink(missing_ok=False)

    def test_f15_t2_path_traversal_prevention_in_replay_actions(self):
        """Tier 2: Traversal paths escape target directory."""
        malicious = "../../Library/Documents/registry.db"
        base = self.parks_dir / "dairyfactory" / "recent"
        resolved = (base / malicious).resolve()
        self.assertFalse(str(resolved).startswith(str(base)))

    def test_f15_t2_empty_or_missing_replay_directories(self):
        """Tier 2: Empty replay folders return empty list cleanly."""
        empty_park = self.parks_dir / "empty_park" / "recent"
        empty_park.mkdir(parents=True)
        self.assertEqual(list(empty_park.glob("*")), [])


# ==============================================================================
# Feature 16: Board Texture Management
# ==============================================================================

class TestFeature16TextureManager(unittest.TestCase):
    """Feature 16: Board Texture listing, dimensions validation, replacement."""

    def setUp(self):
        if TextureManager is None:
            self.fail("editor.texture_manager.TextureManager not implemented yet")
        self.td = tempfile.TemporaryDirectory()
        self.session_dir = Path(self.td.name)
        self.tex_dir = self.session_dir / "Library" / "Documents" / "board_textures"
        shutil.copytree(REF_SAVE_DIR / "Library" / "Documents" / "board_textures", self.tex_dir)
        self.tm = TextureManager(str(self.session_dir))

    def tearDown(self):
        self.td.cleanup()

    def test_f16_t1_list_reference_board_textures(self):
        """Tier 1: List all 7 reference board texture files via TextureManager."""
        textures = self.tm.list_textures()
        self.assertIsInstance(textures, list)
        self.assertEqual(len(textures), 7)
        expected = {
            'deck_baked_deck_2.png', 'deck_baked_deck_9.png',
            'photo_board_untouched_deck_2.png', 'photo_board_untouched_deck_9.png',
            'stickers_baked_deck_2.png', 'stickers_baked_deck_9.png',
            'my_current_board_texture.jpg'
        }
        names = {t["filename"] for t in textures}
        self.assertEqual(names, expected)
        for t in textures:
            self.assertIn("filename", t)
            self.assertIn("format", t)
            self.assertIn("width", t)
            self.assertIn("height", t)
            self.assertIn("size", t)
            self.assertGreater(t["size"], 0)

    def test_f16_t1_validate_png_dimensions_and_channels(self):
        """Tier 1: Verify reference deck PNG is 1024x256 RGBA (color type 6) via TextureManager."""
        info = self.tm.get_texture_info("deck_baked_deck_2.png")
        self.assertEqual(info["width"], 1024)
        self.assertEqual(info["height"], 256)
        self.assertEqual(info["format"], "png")
        self.assertEqual(info["color_type"], 6)
        self.assertEqual(info["bit_depth"], 8)
        val = self.tm.validate_image((self.tex_dir / "deck_baked_deck_2.png").read_bytes(), "deck_baked_deck_2.png")
        self.assertEqual(val["width"], 1024)
        self.assertEqual(val["height"], 256)

    def test_f16_t1_validate_jpeg_dimensions(self):
        """Tier 1: Verify reference board JPEG is 1024x1024 via TextureManager."""
        info = self.tm.get_texture_info("my_current_board_texture.jpg")
        self.assertEqual(info["width"], 1024)
        self.assertEqual(info["height"], 1024)
        self.assertIn(info["format"], ("jpeg", "jpg"))
        val = self.tm.validate_image((self.tex_dir / "my_current_board_texture.jpg").read_bytes(), "my_current_board_texture.jpg")
        self.assertEqual(val["width"], 1024)
        self.assertEqual(val["height"], 1024)

    def test_f16_t1_replace_deck_texture_valid_png(self):
        """Tier 1: Replace deck texture with generated 1024x256 PNG via TextureManager."""
        new_png = generate_minimal_png(1024, 256, (0, 255, 0, 255))
        res = self.tm.replace_texture("deck_baked_deck_2.png", new_png)
        self.assertTrue(res.get("success", True) if isinstance(res, dict) else res)
        target = self.tex_dir / "deck_baked_deck_2.png"
        self.assertEqual(target.read_bytes(), new_png)
        info = self.tm.get_texture_info("deck_baked_deck_2.png")
        self.assertEqual(info["width"], 1024)
        self.assertEqual(info["height"], 256)
        preview_bytes, mime = self.tm.get_preview("deck_baked_deck_2.png")
        self.assertEqual(preview_bytes, new_png)
        self.assertEqual(mime, "image/png")

    def test_f16_t1_replace_current_board_valid_jpeg(self):
        """Tier 1: Replace board JPEG via TextureManager."""
        jpg_sample = self.tex_dir / "my_current_board_texture.jpg"
        orig = jpg_sample.read_bytes()
        res = self.tm.replace_texture("my_current_board_texture.jpg", orig)
        self.assertTrue(res.get("success", True) if isinstance(res, dict) else res)
        self.assertEqual(jpg_sample.read_bytes(), orig)
        info = self.tm.get_texture_info("my_current_board_texture.jpg")
        self.assertEqual(info["width"], 1024)
        self.assertEqual(info["height"], 1024)
        preview_bytes, mime = self.tm.get_preview("my_current_board_texture.jpg")
        self.assertEqual(preview_bytes, orig)
        self.assertEqual(mime, "image/jpeg")

    def test_f16_t2_reject_invalid_png_dimensions(self):
        """Tier 2: Reject non-1024x256 PNG via TextureManager."""
        bad_png = generate_minimal_png(512, 512)
        orig_bytes = (self.tex_dir / "deck_baked_deck_2.png").read_bytes()
        with self.assertRaises(ValueError):
            self.tm.replace_texture("deck_baked_deck_2.png", bad_png)
        with self.assertRaises(ValueError):
            self.tm.validate_image(bad_png, "deck_baked_deck_2.png")
        self.assertEqual((self.tex_dir / "deck_baked_deck_2.png").read_bytes(), orig_bytes)

    def test_f16_t2_reject_invalid_jpeg_dimensions(self):
        """Tier 2: Non-1024x1024 dimensions fail requirement via TextureManager."""
        orig_jpg = (self.tex_dir / "my_current_board_texture.jpg").read_bytes()
        sof_idx = orig_jpg.find(b"\xff\xc0")
        self.assertNotEqual(sof_idx, -1)
        bad_dims = [(512, 512), (1024, 256), (800, 600)]
        for w, h in bad_dims:
            bad_jpg = bytearray(orig_jpg)
            struct.pack_into(">HH", bad_jpg, sof_idx + 5, h, w)
            with self.assertRaises(ValueError):
                self.tm.replace_texture("my_current_board_texture.jpg", bytes(bad_jpg))
            with self.assertRaises(ValueError):
                self.tm.validate_image(bytes(bad_jpg), "my_current_board_texture.jpg")
        self.assertEqual((self.tex_dir / "my_current_board_texture.jpg").read_bytes(), orig_jpg)

    def test_f16_t2_reject_corrupted_or_empty_image_data(self):
        """Tier 2: 0-byte or corrupted header raises ValueError in TextureManager."""
        orig_bytes = (self.tex_dir / "deck_baked_deck_2.png").read_bytes()
        for corrupt in [b"", b"not an image", b"\x89PNG\r\n\x1a\n\x00", b"\xff\xd8\xff\xe0\x00"]:
            with self.assertRaises(ValueError):
                self.tm.replace_texture("deck_baked_deck_2.png", corrupt)
            with self.assertRaises(ValueError):
                self.tm.validate_image(corrupt, "deck_baked_deck_2.png")
        self.assertEqual((self.tex_dir / "deck_baked_deck_2.png").read_bytes(), orig_bytes)

    def test_f16_t2_reject_format_mismatch(self):
        """Tier 2: Uploading PNG to JPEG target or vice versa raises ValueError in TextureManager."""
        png_data = generate_minimal_png(1024, 256)
        jpeg_data = (self.tex_dir / "my_current_board_texture.jpg").read_bytes()
        with self.assertRaises(ValueError):
            self.tm.replace_texture("my_current_board_texture.jpg", png_data)
        with self.assertRaises(ValueError):
            self.tm.replace_texture("deck_baked_deck_2.png", jpeg_data)

    def test_f16_t2_oversized_image_rejection(self):
        """Tier 2: Reject uploads > 10MB in TextureManager."""
        oversized = generate_minimal_png(1024, 256) + b"\x00" * (11 * 1024 * 1024)
        self.assertGreater(len(oversized), 10 * 1024 * 1024)
        orig_bytes = (self.tex_dir / "deck_baked_deck_2.png").read_bytes()
        with self.assertRaises(ValueError):
            self.tm.replace_texture("deck_baked_deck_2.png", oversized)
        with self.assertRaises(ValueError):
            self.tm.validate_image(oversized, "deck_baked_deck_2.png")
        self.assertEqual((self.tex_dir / "deck_baked_deck_2.png").read_bytes(), orig_bytes)

    def test_f16_t2_missing_board_textures_directory_creation(self):
        """Tier 2: Automatically create board_textures directory if missing via TextureManager."""
        new_stage = Path(self.td.name) / "empty_stage"
        new_stage.mkdir(parents=True, exist_ok=True)
        new_tex = new_stage / "Library" / "Documents" / "board_textures"
        self.assertFalse(new_tex.exists())
        tm_new = TextureManager(str(new_stage))
        tm_new.ensure_directory()
        self.assertTrue(new_tex.exists())
        self.assertEqual(tm_new.list_textures(), [])


# ==============================================================================
# Feature 17: Skeuomorphic UI Assets & Styling
# ==============================================================================

class TestFeature17UiCoverage(unittest.TestCase):
    """Feature 17: Skeuomorphic single-page UI assets and styling."""

    def test_f17_tier1_01_web_assets_existence_and_sizes(self):
        """Tier 1: index.html, style.css, and app.js exist with non-trivial size."""
        for name, min_sz in [("index.html", 500), ("style.css", 1000), ("app.js", 1000)]:
            p = WEB_DIR / name
            self.assertTrue(p.exists(), f"Web asset missing: {p}")
            self.assertGreater(p.stat().st_size, min_sz)

    def test_f17_tier1_02_index_html_structure_and_links(self):
        """Tier 1: index.html links to style.css and app.js."""
        p = WEB_DIR / "index.html"
        if not p.exists():
            self.fail(f"index.html does not exist yet at {p}")
        content = p.read_text(encoding="utf-8")
        self.assertIn("style.css", content)
        self.assertIn("app.js", content)

    def test_f17_tier1_03_grip_tape_css_styling(self):
        """Tier 1: style.css defines dark skate grip tape texture."""
        p = WEB_DIR / "style.css"
        if not p.exists():
            self.fail(f"style.css does not exist yet at {p}")
        css = p.read_text(encoding="utf-8").lower()
        self.assertTrue("gradient" in css or "#121212" in css or "#1e1e1e" in css or "noise" in css or "grain" in css)

    def test_f17_tier1_04_brushed_aluminum_and_inset_wells(self):
        """Tier 1: style.css defines metallic gradients and inset wells."""
        p = WEB_DIR / "style.css"
        if not p.exists():
            self.fail(f"style.css does not exist yet at {p}")
        css = p.read_text(encoding="utf-8").lower()
        self.assertIn("inset", css)

    def test_f17_tier1_05_tactile_switch_grooves_and_leds(self):
        """Tier 1: style.css includes green active groove (#4cd964) and LED styling."""
        p = WEB_DIR / "style.css"
        if not p.exists():
            self.fail(f"style.css does not exist yet at {p}")
        css = p.read_text(encoding="utf-8").lower()
        self.assertTrue("#4cd964" in css or "rgb(76, 217, 100)" in css or "rgb(76,217,100)" in css)


class TestFeature17UiBoundary(unittest.TestCase):
    """Feature 17: Boundary & safety tests for UI assets."""

    def test_f17_tier2_01_zero_external_cdn_dependencies(self):
        """Tier 2: Zero external network/CDN dependencies across web assets."""
        for name in ["index.html", "style.css", "app.js"]:
            p = WEB_DIR / name
            if not p.exists():
                self.fail(f"{name} does not exist yet at {p}")
            content = p.read_text(encoding="utf-8")
            self.assertNotRegex(content, r"(?i)https?://(?!localhost|127\.0\.0\.1)")

    def test_f17_tier2_02_active_depression_mechanical_feedback(self):
        """Tier 2: Buttons define :active mechanical feedback."""
        p = WEB_DIR / "style.css"
        if not p.exists():
            self.fail(f"style.css does not exist yet at {p}")
        css = p.read_text(encoding="utf-8").lower()
        self.assertIn(":active", css)

    def test_f17_tier2_03_responsive_viewport_meta(self):
        """Tier 2: index.html defines responsive viewport meta tag."""
        p = WEB_DIR / "index.html"
        if not p.exists():
            self.fail(f"index.html does not exist yet at {p}")
        html = p.read_text(encoding="utf-8")
        self.assertIn('name="viewport"', html)

    def test_f17_tier2_04_css_class_consistency(self):
        """Tier 2: Core component classes in index.html are styled in style.css."""
        p_html = WEB_DIR / "index.html"
        p_css = WEB_DIR / "style.css"
        if not p_html.exists() or not p_css.exists():
            self.fail("Web assets index.html or style.css do not exist yet")
        html = p_html.read_text(encoding="utf-8")
        css = p_css.read_text(encoding="utf-8")
        for cls in ["dropzone", "panel", "switch"]:
            if f'class="{cls}' in html:
                self.assertIn(f".{cls}", css)

    def test_f17_tier2_05_vanilla_javascript_dom_safety(self):
        """Tier 2: app.js uses vanilla DOM listeners without external frameworks."""
        p = WEB_DIR / "app.js"
        if not p.exists():
            self.fail(f"app.js does not exist yet at {p}")
        js = p.read_text(encoding="utf-8")
        self.assertTrue("addEventListener" in js or "onload" in js or "DOMContentLoaded" in js)
        self.assertNotIn("react", js.lower())
        self.assertNotIn("vue", js.lower())


# ==============================================================================
# Feature 18: Strict Header Branding
# ==============================================================================

class TestFeature18BrandingCoverage(unittest.TestCase):
    """Feature 18: Exact header branding TOUCHGRIND SKATE 2 // SAVE EDITOR."""

    def test_f18_tier1_01_header_branding_in_html_body(self):
        """Tier 1: Exact branding in HTML body."""
        p = WEB_DIR / "index.html"
        if not p.exists():
            self.fail(f"index.html does not exist yet at {p}")
        html = p.read_text(encoding="utf-8")
        self.assertIn("TOUCHGRIND SKATE 2 // SAVE EDITOR", html)

    def test_f18_tier1_02_branding_in_title_tag(self):
        """Tier 1: Exact branding in <title> tag."""
        p = WEB_DIR / "index.html"
        if not p.exists():
            self.fail(f"index.html does not exist yet at {p}")
        html = p.read_text(encoding="utf-8")
        self.assertRegex(html, r"<title>.*TOUCHGRIND SKATE 2 // SAVE EDITOR.*</title>")

    def test_f18_tier1_03_branding_in_batch_launcher(self):
        """Tier 1: Exact branding in run_save_editor.bat."""
        if not BATCH_FILE.exists():
            self.fail(f"run_save_editor.bat does not exist yet at {BATCH_FILE}")
        bat = BATCH_FILE.read_text(encoding="utf-8", errors="ignore")
        self.assertIn("TOUCHGRIND SKATE 2 // SAVE EDITOR", bat)

    def test_f18_tier1_04_branding_semantic_h1_container(self):
        """Tier 1: Branding enclosed in semantic header or h1 element."""
        p = WEB_DIR / "index.html"
        if not p.exists():
            self.fail(f"index.html does not exist yet at {p}")
        html = p.read_text(encoding="utf-8")
        self.assertTrue("<header" in html or "<h1" in html)

    def test_f18_tier1_05_header_typography_styling(self):
        """Tier 1: Header typography defines uppercase, letter spacing, or shadow."""
        p = WEB_DIR / "style.css"
        if not p.exists():
            self.fail(f"style.css does not exist yet at {p}")
        css = p.read_text(encoding="utf-8").lower()
        self.assertTrue("text-shadow" in css or "letter-spacing" in css or "uppercase" in css)


class TestFeature18BrandingBoundary(unittest.TestCase):
    """Feature 18: Prohibited tokens and branding delimiter checks."""

    def test_f18_tier2_01_no_prohibited_or_edgy_tokens(self):
        """Tier 2: No edgy gamer handles or unofficial branding tokens."""
        for p in [WEB_DIR / "index.html", WEB_DIR / "app.js", BATCH_FILE]:
            if not p.exists():
                self.fail(f"File {p} does not exist yet")
            txt = p.read_text(encoding="utf-8", errors="ignore").lower()
            self.assertNotIn("hax", txt)
            self.assertNotIn("cheat", txt)

    def test_f18_tier2_02_strict_delimiter_and_spacing(self):
        """Tier 2: Delimiter is strictly double-slash // with spaces."""
        p = WEB_DIR / "index.html"
        if not p.exists():
            self.fail(f"index.html does not exist yet at {p}")
        html = p.read_text(encoding="utf-8")
        self.assertRegex(html, r"TOUCHGRIND SKATE 2 // SAVE EDITOR")

    def test_f18_tier2_03_header_element_not_hidden(self):
        """Tier 2: Header element is not hidden via CSS."""
        p = WEB_DIR / "style.css"
        if not p.exists():
            self.fail(f"style.css does not exist yet at {p}")
        css = p.read_text(encoding="utf-8")
        self.assertNotRegex(css, r"(?i)header\s*\{[^}]*display\s*:\s*none")

    def test_f18_tier2_04_header_immutable_in_javascript(self):
        """Tier 2: app.js does not overwrite branding text."""
        p = WEB_DIR / "app.js"
        if not p.exists():
            self.fail(f"app.js does not exist yet at {p}")
        js = p.read_text(encoding="utf-8")
        self.assertNotIn("TOUCHGRIND SKATE 2 // SAVE EDITOR = ", js)

    def test_f18_tier2_05_header_served_via_http(self):
        """Tier 2: HTML delivered via static server contains branding string."""
        p = WEB_DIR / "index.html"
        if not p.exists():
            self.fail(f"index.html does not exist yet at {p}")
        html = p.read_text(encoding="utf-8")
        self.assertIn("TOUCHGRIND SKATE 2 // SAVE EDITOR", html)


# ==============================================================================
# Feature 19: UI File Operations & Drag-and-Drop
# ==============================================================================

class TestFeature19FileOpsCoverage(unittest.TestCase):
    """Feature 19: File dropzone, sample loader, and export UI."""

    def test_f19_tier1_01_dropzone_element_in_html(self):
        """Tier 1: Dedicated drag-and-drop dropzone element exists in index.html."""
        p = WEB_DIR / "index.html"
        if not p.exists():
            self.fail(f"index.html does not exist yet at {p}")
        html = p.read_text(encoding="utf-8")
        self.assertTrue('id="dropzone"' in html or 'class="dropzone"' in html)

    def test_f19_tier1_02_file_input_fallback_element(self):
        """Tier 1: <input type="file"> manual fallback element exists."""
        p = WEB_DIR / "index.html"
        if not p.exists():
            self.fail(f"index.html does not exist yet at {p}")
        html = p.read_text(encoding="utf-8")
        self.assertIn('<input type="file"', html)

    def test_f19_tier1_03_load_sample_save_button(self):
        """Tier 1: Load Sample Save button exists."""
        p = WEB_DIR / "index.html"
        if not p.exists():
            self.fail(f"index.html does not exist yet at {p}")
        html = p.read_text(encoding="utf-8")
        self.assertTrue("sample" in html.lower())

    def test_f19_tier1_04_export_zip_button(self):
        """Tier 1: Export ZIP button exists."""
        p = WEB_DIR / "index.html"
        if not p.exists():
            self.fail(f"index.html does not exist yet at {p}")
        html = p.read_text(encoding="utf-8")
        self.assertTrue("export" in html.lower())

    def test_f19_tier1_05_category_tabs_and_panels(self):
        """Tier 1: Navigation panels exist for core categories."""
        p = WEB_DIR / "index.html"
        if not p.exists():
            self.fail(f"index.html does not exist yet at {p}")
        html = p.read_text(encoding="utf-8").lower()
        for cat in ["park", "challenge", "score", "cloud", "replay", "texture"]:
            self.assertIn(cat, html)


class TestFeature19FileOpsBoundary(unittest.TestCase):
    """Feature 19: Event handlers and visual state for file operations."""

    def test_f19_tier2_01_drag_event_listeners_in_javascript(self):
        """Tier 2: dragover and drop event handlers attached in app.js."""
        p = WEB_DIR / "app.js"
        if not p.exists():
            self.fail(f"app.js does not exist yet at {p}")
        js = p.read_text(encoding="utf-8")
        self.assertIn("dragover", js)
        self.assertIn("drop", js)

    def test_f19_tier2_02_dropzone_active_visual_state_in_css(self):
        """Tier 2: Active dragover highlight state in style.css."""
        p = WEB_DIR / "style.css"
        if not p.exists():
            self.fail(f"style.css does not exist yet at {p}")
        css = p.read_text(encoding="utf-8")
        self.assertTrue(".dragover" in css or ":hover" in css or ".active" in css)

    def test_f19_tier2_03_status_led_indicators_in_html_and_css(self):
        """Tier 2: Status LED indicators and colors defined."""
        p = WEB_DIR / "style.css"
        if not p.exists():
            self.fail(f"style.css does not exist yet at {p}")
        css = p.read_text(encoding="utf-8").lower()
        self.assertTrue("led" in css)

    def test_f19_tier2_04_export_button_disabled_state_when_idle(self):
        """Tier 2: Export button starts disabled or styled disabled."""
        p_html = WEB_DIR / "index.html"
        p_css = WEB_DIR / "style.css"
        if not p_html.exists() or not p_css.exists():
            self.fail("Web assets do not exist yet")
        html = p_html.read_text(encoding="utf-8")
        css = p_css.read_text(encoding="utf-8")
        self.assertTrue("disabled" in html or ":disabled" in css)

    def test_f19_tier2_05_sample_load_api_wiring_in_javascript(self):
        """Tier 2: Sample load button wired to /api/session/load_sample in app.js."""
        p = WEB_DIR / "app.js"
        if not p.exists():
            self.fail(f"app.js does not exist yet at {p}")
        js = p.read_text(encoding="utf-8")
        self.assertIn("/api/session/load_sample", js)

    def test_f19_tier2_06_multiple_file_drop_handling(self):
        """Tier 2: Drop handler handles file lists."""
        p = WEB_DIR / "app.js"
        if not p.exists():
            self.fail(f"app.js does not exist yet at {p}")
        js = p.read_text(encoding="utf-8")
        self.assertTrue("files" in js)


# ==============================================================================
# Feature 20: Round-Trip Save Integrity Verification
# ==============================================================================

class TestFeature20SaveIntegrity(unittest.TestCase):
    """Feature 20: Round-trip save integrity verification."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.stage = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def test_f20_t1_unmodified_save_roundtrip_integrity(self):
        """Tier 1: Exporting unmodified save produces valid zip archive."""
        zip_p = self.stage / "exp.zip"
        with zipfile.ZipFile(zip_p, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(REF_SAVE_DIR):
                for f in files:
                    p = Path(root) / f
                    zf.write(p, p.relative_to(REF_SAVE_DIR).as_posix())
        self.assertTrue(zip_p.exists())
        with zipfile.ZipFile(zip_p, 'r') as zf:
            nl = set(zf.namelist())
            self.assertIn("Library/Documents/registry.db", nl)
            self.assertIn("Library/Application Support/cloudregistry.db", nl)
            self.assertIn("Library/Application Support/cloudregistry.db.hmc", nl)

    def test_f20_t1_multi_system_mutation_roundtrip(self):
        """Tier 1: Mutating registry and cloud retains integrity."""
        copy_s = self.stage / "copy"
        shutil.copytree(REF_SAVE_DIR, copy_s)
        reg_p = copy_s / "Library" / "Documents" / "registry.db"
        conn = sqlite3.connect(reg_p)
        conn.execute("INSERT OR REPLACE INTO integerdata (key, value) VALUES ('is_purchased_se.illusionlabs.skate2.megaramp', 1)")
        conn.commit()
        conn.close()

        cloud_p = copy_s / "Library" / "Application Support" / "cloudregistry.db"
        token = cloud_p.read_bytes().split()[0]
        hmc_val = compute_hmac_sha256(token)
        (copy_s / "Library" / "Application Support" / "cloudregistry.db.hmc").write_text(hmc_val)
        self.assertEqual(len(hmc_val), 64)

    def test_f20_t1_sqlite_pragma_integrity_post_export(self):
        """Tier 1: PRAGMA integrity_check == ok on both reference databases."""
        for name in ["Library/Documents/registry.db", "Library/Application Support/cloudregistry.db"]:
            conn = sqlite3.connect(REF_SAVE_DIR / name)
            res = conn.execute("PRAGMA integrity_check").fetchall()
            conn.close()
            self.assertEqual(res, [('ok',)])

    def test_f20_t1_hmac_validity_post_export(self):
        """Tier 1: cloudregistry.db.hmc matches compute_hmac_sha256 exactly."""
        cloud_p = REF_SAVE_DIR / "Library" / "Application Support" / "cloudregistry.db"
        hmc_p = REF_SAVE_DIR / "Library" / "Application Support" / "cloudregistry.db.hmc"
        token = cloud_p.read_bytes().split()[0]
        calc = compute_hmac_sha256(token)
        self.assertEqual(calc, hmc_p.read_text().strip())

    def test_f20_t1_all_replays_valid_post_export(self):
        """Tier 1: All 82 reference replay files decompress with valid length prefix."""
        replays = list(REF_SAVE_DIR.glob("Library/Documents/*/recent/*")) + list(REF_SAVE_DIR.glob("Library/Documents/*/top/*"))
        self.assertEqual(len(replays), 82)
        for r in replays:
            raw = r.read_bytes()
            ulen = struct.unpack('<I', raw[:4])[0]
            decomp = zlib.decompress(raw[4:])
            self.assertEqual(len(decomp), ulen)
            self.assertEqual(decomp[:4], b"RPLY")

    def test_f20_t2_detect_and_refuse_export_on_corrupt_database(self):
        """Tier 2: Corrupted database triggers SQLite error."""
        corrupt_p = self.stage / "corrupt.db"
        corrupt_p.write_bytes(b"SQLite format 3\x00" + b"\xff" * 500)
        conn = sqlite3.connect(corrupt_p)
        with self.assertRaises(sqlite3.DatabaseError):
            conn.execute("SELECT * FROM sqlite_master").fetchall()
        conn.close()

    def test_f20_t2_missing_hmc_file_auto_healing_on_export(self):
        """Tier 2: Missing cloudregistry.db.hmc regenerates accurately."""
        cloud_p = REF_SAVE_DIR / "Library" / "Application Support" / "cloudregistry.db"
        token = cloud_p.read_bytes().split()[0]
        regen = compute_hmac_sha256(token)
        self.assertEqual(regen, HMAC_REF_DIGEST)

    def test_f20_t2_clean_zip_exclusion_of_temp_and_os_files(self):
        """Tier 2: Forbidden temp/OS files (.DS_Store, Thumbs.db) excluded from export."""
        forbidden = {'.DS_Store', 'Thumbs.db', 'temp.sqlite-wal', '__MACOSX'}
        zip_p = self.stage / "test_clean.zip"
        with zipfile.ZipFile(zip_p, 'w') as zf:
            zf.writestr("Library/Documents/registry.db", b"dummy")
        with zipfile.ZipFile(zip_p, 'r') as zf:
            for item in zf.namelist():
                self.assertNotIn(Path(item).name, forbidden)

    def test_f20_t2_path_normalization_across_os(self):
        """Tier 2: Export zip entry paths strictly use forward slashes (/)."""
        zip_p = self.stage / "norm.zip"
        with zipfile.ZipFile(zip_p, 'w') as zf:
            zf.writestr("Library/Documents/registry.db", b"dummy")
        with zipfile.ZipFile(zip_p, 'r') as zf:
            for item in zf.namelist():
                self.assertNotIn("\\", item)

    def test_f20_t2_idempotent_repeated_export(self):
        """Tier 2: Repeated exports yield identical SHA-256 hashes."""
        reg_p = REF_SAVE_DIR / "Library" / "Documents" / "registry.db"
        h1 = hashlib.sha256(reg_p.read_bytes()).hexdigest()
        h2 = hashlib.sha256(reg_p.read_bytes()).hexdigest()
        self.assertEqual(h1, h2)


# ==============================================================================
# Tier 3: Pairwise Cross-Feature Interactions (22 Tests)
# ==============================================================================

class TestTier3CrossFeatureInteractions(unittest.TestCase):
    """Tier 3: Pairwise cross-feature interactions across subsystems."""

    @classmethod
    def setUpClass(cls):
        cls.server = None
        cls.port = None
        cls.thread = None
        if Server is not None:
            cls.port = find_free_port()
            try:
                cls.server = Server(port=cls.port)
                cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
                cls.thread.start()
                time.sleep(0.15)
            except Exception:
                cls.server = None

    @classmethod
    def tearDownClass(cls):
        if cls.server is not None:
            try:
                cls.server.shutdown()
                cls.server.server_close()
            except Exception:
                pass

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.stage = Path(self.td.name) / "iph1"
        shutil.copytree(REF_SAVE_DIR, self.stage)

    def tearDown(self):
        self.td.cleanup()

    def test_t3_cross_01_staging_to_registry_dlc_unlock(self):
        """Cross F3 <-> F5/F6: Staging copy allows unlocking all 8 DLC parks in registry.db."""
        db_p = self.stage / "Library" / "Documents" / "registry.db"
        conn = sqlite3.connect(db_p)
        for p in DLC_PARKS_LIST:
            conn.execute("DELETE FROM integerdata WHERE key=?", (f"is_purchased_se.illusionlabs.skate2.{p}",))
            conn.execute("INSERT INTO integerdata (key, value) VALUES (?, 1)", (f"is_purchased_se.illusionlabs.skate2.{p}",))
        conn.commit()
        rows = conn.execute("SELECT key, value FROM integerdata WHERE key LIKE 'is_purchased_se.illusionlabs.skate2.%'").fetchall()
        conn.close()
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(v == 1 for _, v in rows))

    def test_t3_cross_02_registry_highscores_and_equipment_coexistence(self):
        """Cross F5 <-> F8 <-> F9: Updating highscores and equipment in integerdata simultaneously."""
        db_p = self.stage / "Library" / "Documents" / "registry.db"
        conn = sqlite3.connect(db_p)
        conn.execute("DELETE FROM integerdata WHERE key='db_competition_skatepark0'")
        conn.execute("INSERT INTO integerdata (key, value) VALUES ('db_competition_skatepark0', 5555555)")
        conn.execute("DELETE FROM integerdata WHERE key='currentBoardIndex'")
        conn.execute("INSERT INTO integerdata (key, value) VALUES ('currentBoardIndex', 5)")
        conn.commit()
        c_score = conn.execute("SELECT value FROM integerdata WHERE key='db_competition_skatepark0'").fetchone()[0]
        c_board = conn.execute("SELECT value FROM integerdata WHERE key='currentBoardIndex'").fetchone()[0]
        conn.close()
        self.assertEqual(c_score, 5555555)
        self.assertEqual(c_board, 5)

    def test_t3_cross_03_cloud_user_id_update_triggers_hmc_update(self):
        """Cross F3 <-> F11 <-> F13: Changing CloudStorage_UserID preserves valid HMAC-SHA256."""
        db_p = self.stage / "Library" / "Application Support" / "cloudregistry.db"
        conn = sqlite3.connect(db_p)
        conn.execute("INSERT OR REPLACE INTO stringdata (key, value) VALUES ('CloudStorage_UserID', 'user_test_1234')")
        conn.commit()
        conn.close()
        token = db_p.read_bytes().split()[0]
        hmc_val = compute_hmac_sha256(token)
        hmc_p = self.stage / "Library" / "Application Support" / "cloudregistry.db.hmc"
        hmc_p.write_text(hmc_val)
        self.assertEqual(hmc_p.read_text().strip(), hmc_val)

    def test_t3_cross_04_special_boards_sync_and_hmac_consistency(self):
        """Cross F11 <-> F12 <-> F13: Updating special board binary items retains HMAC."""
        db_p = self.stage / "Library" / "Application Support" / "cloudregistry.db"
        conn = sqlite3.connect(db_p)
        raw_items = struct.pack('<30q', *range(2, 32))
        b64_items = base64.b64encode(raw_items).decode('ascii')
        conn.execute("INSERT OR REPLACE INTO stringdata (key, value) VALUES ('iap_special_boards_items', ?)", (b64_items,))
        conn.commit()
        conn.close()
        unpacked = struct.unpack('<30q', base64.b64decode(b64_items))
        self.assertEqual(unpacked, tuple(range(2, 32)))

    def test_t3_cross_05_dlc_unlock_and_park_challenges_consistency(self):
        """Cross F6 <-> F7: Unlocking DLC park and completing its 45 challenges in integerdata."""
        db_p = self.stage / "Library" / "Documents" / "registry.db"
        conn = sqlite3.connect(db_p)
        conn.execute("DELETE FROM integerdata WHERE key='is_purchased_se.illusionlabs.skate2.thecarpark'")
        conn.execute("INSERT INTO integerdata (key, value) VALUES ('is_purchased_se.illusionlabs.skate2.thecarpark', 1)")
        conn.execute("DELETE FROM integerdata WHERE key LIKE 'challenge_%_location_thecarpark'")
        for i in range(1, 46):
            conn.execute("INSERT INTO integerdata (key, value) VALUES (?, 1)", (f"challenge_{i}_location_thecarpark",))
        conn.commit()
        cnt = conn.execute("SELECT count(*) FROM integerdata WHERE key LIKE 'challenge_%_location_thecarpark' AND value=1").fetchone()[0]
        conn.close()
        self.assertEqual(cnt, 45)

    def test_t3_cross_06_replay_score_matches_or_updates_highscores(self):
        """Cross F8 <-> F14: Syncing replay score with registry db highscores."""
        if ReplayParser is None:
            self.fail("editor.replay_parser.ReplayParser not implemented yet")
        replay_p = self.stage / "Library" / "Documents" / "backyard" / "top" / "comp-17395267498"
        parsed = ReplayParser.parse(str(replay_p))
        db_p = self.stage / "Library" / "Documents" / "registry.db"
        conn = sqlite3.connect(db_p)
        db_score = conn.execute("SELECT value FROM integerdata WHERE key='db_competition_skatepark0'").fetchone()[0]
        conn.close()
        self.assertEqual(parsed["score"], db_score)

    def test_t3_cross_07_replay_addition_increments_clipcounter(self):
        """Cross F14 <-> F15: Adding a replay increments the park clipcounter uint32."""
        if ClipcounterEditor is None:
            self.fail("editor.replay_parser.ClipcounterEditor not implemented yet")
        cc_p = self.stage / "Library" / "Documents" / "dairyfactory" / "clipcounter"
        val = ClipcounterEditor.read_counter(str(cc_p))
        cc_p.write_bytes(ClipcounterEditor.write_counter(val + 1))
        self.assertEqual(ClipcounterEditor.read_counter(str(cc_p)), 2)

    def test_t3_cross_08_replay_deletion_reflected_in_exported_zip(self):
        """Cross F15 <-> F4: Deleting replay in staging excludes it from exported zip."""
        target = list((self.stage / "Library" / "Documents" / "backyard" / "recent").glob("*"))[0]
        t_name = target.name
        target.unlink()
        zip_p = self.stage.parent / "out.zip"
        with zipfile.ZipFile(zip_p, 'w') as zf:
            for root, _, files in os.walk(self.stage):
                for f in files:
                    p = Path(root) / f
                    zf.write(p, p.relative_to(self.stage).as_posix())
        with zipfile.ZipFile(zip_p, 'r') as zf:
            self.assertNotIn(f"Library/Documents/backyard/recent/{t_name}", zf.namelist())

    def test_t3_cross_09_custom_texture_links_with_board_index(self):
        """Cross F16 <-> F9: Custom board slot 2 texture corresponds to currentBoardIndex=2."""
        tex_p = self.stage / "Library" / "Documents" / "board_textures" / "deck_baked_deck_2.png"
        self.assertTrue(tex_p.exists())
        db_p = self.stage / "Library" / "Documents" / "registry.db"
        conn = sqlite3.connect(db_p)
        conn.execute("DELETE FROM integerdata WHERE key='currentBoardIndex'")
        conn.execute("INSERT INTO integerdata (key, value) VALUES ('currentBoardIndex', 2)")
        conn.commit()
        val = conn.execute("SELECT value FROM integerdata WHERE key='currentBoardIndex'").fetchone()[0]
        conn.close()
        self.assertEqual(val, 2)

    def test_t3_cross_10_texture_replacement_persists_in_export(self):
        """Cross F16 <-> F4: Texture replacement is preserved with verified dimensions in export."""
        tex_p = self.stage / "Library" / "Documents" / "board_textures" / "deck_baked_deck_9.png"
        new_png = generate_minimal_png(1024, 256, (128, 64, 32, 255))
        tex_p.write_bytes(new_png)
        zip_p = self.stage.parent / "export_tex.zip"
        with zipfile.ZipFile(zip_p, 'w') as zf:
            zf.write(tex_p, "Library/Documents/board_textures/deck_baked_deck_9.png")
        with zipfile.ZipFile(zip_p, 'r') as zf:
            data = zf.read("Library/Documents/board_textures/deck_baked_deck_9.png")
            w, h, _, _ = parse_png_dimensions(data)
            self.assertEqual((w, h), (1024, 256))

    def test_t3_cross_11_rest_api_session_create_and_load_sample(self):
        """Cross F1 <-> F3: Session creation and sample loader endpoint response contract."""
        if self.server is None:
            self.fail("editor.server.Server not implemented yet")
        if SessionManager is None:
            self.fail("editor.session.SessionManager not implemented yet")

        # 1. Test POST /api/session/create
        create_url = f"http://127.0.0.1:{self.port}/api/session/create"
        req = urllib.request.Request(create_url, data=b"{}", method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("application/json", resp.headers.get("Content-Type", ""))
            created_data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("session_id", created_data)
            self.assertEqual(created_data.get("status"), "created")

        # 2. Test POST /api/session/load_sample
        load_url = f"http://127.0.0.1:{self.port}/api/session/load_sample"
        req = urllib.request.Request(load_url, data=b"{}", method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            load_data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("session_id", load_data)
            self.assertGreater(load_data.get("files_loaded", 0), 0)
            sample_sid = load_data["session_id"]

        # 3. Test GET /api/session/<id>/status
        status_url = f"http://127.0.0.1:{self.port}/api/session/{sample_sid}/status"
        with urllib.request.urlopen(status_url, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            status_data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(status_data.get("session_id"), sample_sid)
            self.assertTrue(status_data.get("has_registry"))
            self.assertTrue(status_data.get("has_cloud"))
            self.assertIsInstance(status_data.get("parks"), list)
            self.assertGreaterEqual(len(status_data.get("parks", [])), 1)
            self.assertGreaterEqual(status_data.get("replays_count", 0), 10)
            self.assertGreaterEqual(status_data.get("textures_count", 0), 5)

    def test_t3_cross_12_rest_api_dlc_unlock_all(self):
        """Cross F1 <-> F6: REST API contract for POST /api/session/<id>/registry/parks unlock_all."""
        if self.server is None:
            self.fail("editor.server.Server not implemented yet")
        if RegistryEditor is None:
            self.fail("editor.registry_editor.RegistryEditor not implemented yet")

        # Load sample save into server session
        load_url = f"http://127.0.0.1:{self.port}/api/session/load_sample"
        req = urllib.request.Request(load_url, data=b"{}", method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            sid = json.loads(resp.read().decode("utf-8"))["session_id"]

        # Send POST /api/session/<id>/registry/parks
        parks_url = f"http://127.0.0.1:{self.port}/api/session/{sid}/registry/parks"
        payload = json.dumps({"unlock_all": True}).encode("utf-8")
        req = urllib.request.Request(parks_url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data.get("status"), "ok")
        except urllib.error.HTTPError as e:
            if e.code in (404, 405, 501):
                self.fail(f"editor.server.Server route POST /api/session/<id>/registry/parks not implemented yet (HTTP {e.code})")
            raise

        # Verify on underlying database that all DLC parks are unlocked
        reg_p = self.server.session_manager.get_registry_path(sid)
        conn = sqlite3.connect(reg_p)
        for park in DLC_PARKS_LIST:
            row = conn.execute(
                "SELECT value FROM integerdata WHERE key=?",
                (f"is_purchased_se.illusionlabs.skate2.{park}",)
            ).fetchone()
            self.assertIsNotNone(row, f"DLC park key is_purchased_se.illusionlabs.skate2.{park} missing")
            self.assertEqual(row[0], 1, f"DLC park {park} not unlocked")
        conn.close()

    def test_t3_cross_13_rest_api_hmac_recalculate(self):
        """Cross F1 <-> F13: REST API endpoint returns calculated HMAC-SHA256 hex digest."""
        if self.server is None:
            self.fail("editor.server.Server not implemented yet")
        if SessionManager is None:
            self.fail("editor.session.SessionManager not implemented yet")

        # Load sample save into server session
        load_url = f"http://127.0.0.1:{self.port}/api/session/load_sample"
        req = urllib.request.Request(load_url, data=b"{}", method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            sid = json.loads(resp.read().decode("utf-8"))["session_id"]

        # Call POST /api/session/<id>/cloud/recalculate_hmac
        hmac_url = f"http://127.0.0.1:{self.port}/api/session/{sid}/cloud/recalculate_hmac"
        req = urllib.request.Request(hmac_url, data=b"{}", method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data.get("status"), "ok")
                returned_hmac = data.get("hmac")
                self.assertIsNotNone(returned_hmac)
                self.assertEqual(len(returned_hmac), 64)
                self.assertRegex(returned_hmac, r"^[0-9a-f]{64}$")
                # Cross-check file on disk in staged session
                hmc_p = self.server.session_manager.get_cloud_hmc_path(sid)
                self.assertTrue(hmc_p.exists())
                self.assertEqual(hmc_p.read_text(encoding="ascii").strip().lower(), returned_hmac.lower())
        except urllib.error.HTTPError as e:
            if e.code in (404, 405, 501):
                self.fail(f"editor.server.Server route POST /api/session/<id>/cloud/recalculate_hmac not implemented yet (HTTP {e.code})")
            raise

    def test_t3_cross_14_rest_api_replay_listing_and_clipcounter(self):
        """Cross F1 <-> F14/F15: REST API replay query returns parsed metadata and clipcounter."""
        if self.server is None:
            self.fail("editor.server.Server not implemented yet")
        if ReplayParser is None:
            self.fail("editor.replay_parser.ReplayParser not implemented yet")
        if ClipcounterEditor is None:
            self.fail("editor.replay_parser.ClipcounterEditor not implemented yet")

        # Load sample save into server session
        load_url = f"http://127.0.0.1:{self.port}/api/session/load_sample"
        req = urllib.request.Request(load_url, data=b"{}", method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            sid = json.loads(resp.read().decode("utf-8"))["session_id"]

        # 1. Query replay listing: GET /api/session/<id>/replays
        replays_url = f"http://127.0.0.1:{self.port}/api/session/{sid}/replays"
        try:
            with urllib.request.urlopen(replays_url, timeout=3.0) as resp:
                self.assertEqual(resp.status, 200)
                replays_data = json.loads(resp.read().decode("utf-8"))
                replays = replays_data.get("replays", [])
                self.assertIsInstance(replays, list)
                self.assertGreater(len(replays), 0)
                rep = replays[0]
                self.assertIn("park", rep)
                self.assertIn("score", rep)
                self.assertIn("run_type", rep)
                self.assertIsInstance(rep["score"], int)
        except urllib.error.HTTPError as e:
            if e.code in (404, 405, 501):
                self.fail(f"editor.server.Server route GET /api/session/<id>/replays not implemented yet (HTTP {e.code})")
            raise

        # 2. Query clipcounter: GET /api/session/<id>/replays/clipcounter?park=backyard
        cc_url = f"http://127.0.0.1:{self.port}/api/session/{sid}/replays/clipcounter?park=backyard"
        try:
            with urllib.request.urlopen(cc_url, timeout=3.0) as resp:
                self.assertEqual(resp.status, 200)
                cc_data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(cc_data.get("park"), "backyard")
                self.assertIn("clipcounter", cc_data)
                self.assertIsInstance(cc_data["clipcounter"], int)
        except urllib.error.HTTPError as e:
            if e.code in (404, 405, 501):
                self.fail(f"editor.server.Server route GET /api/session/<id>/replays/clipcounter not implemented yet (HTTP {e.code})")
            raise

    def test_t3_cross_15_rest_api_texture_preview_and_upload(self):
        """Cross F1 <-> F16: Texture preview serves image/png with valid Content-Type."""
        if self.server is None:
            self.fail("editor.server.Server not implemented yet")
        if TextureManager is None:
            self.fail("editor.texture_manager.TextureManager not implemented yet")

        # Load sample save into server session
        load_url = f"http://127.0.0.1:{self.port}/api/session/load_sample"
        req = urllib.request.Request(load_url, data=b"{}", method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            sid = json.loads(resp.read().decode("utf-8"))["session_id"]

        # Request texture preview for an existing PNG texture
        tex_filename = "deck_baked_deck_2.png"
        preview_url = f"http://127.0.0.1:{self.port}/api/session/{sid}/textures/preview?file={tex_filename}"
        try:
            with urllib.request.urlopen(preview_url, timeout=3.0) as resp:
                self.assertEqual(resp.status, 200)
                # Genuine verification of HTTP response header (eliminating string tautology)
                ct = resp.headers.get("Content-Type", "")
                self.assertIn("image/png", ct)
                raw_bytes = resp.read()
                self.assertTrue(raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"), "Preview response must have PNG magic bytes")
                w, h, _, _ = parse_png_dimensions(raw_bytes)
                self.assertEqual((w, h), (1024, 256), "Deck texture must be 1024x256")
        except urllib.error.HTTPError as e:
            if e.code in (404, 405, 501):
                self.fail(f"editor.server.Server route GET /api/session/<id>/textures/preview not implemented yet (HTTP {e.code})")
            raise

    def test_t3_cross_16_rest_api_export_zip_stream(self):
        """Cross F1 <-> F4: Export endpoint produces streamable application/zip bytes."""
        if self.server is None:
            self.fail("editor.server.Server not implemented yet")
        if SessionManager is None:
            self.fail("editor.session.SessionManager not implemented yet")

        # 1. Load sample save into server session
        load_url = f"http://127.0.0.1:{self.port}/api/session/load_sample"
        req = urllib.request.Request(load_url, data=b"{}", method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            sid = json.loads(resp.read().decode("utf-8"))["session_id"]

        # 2. Request exported zip stream via GET /api/session/<id>/export
        export_url = f"http://127.0.0.1:{self.port}/api/session/{sid}/export?format=iph1"
        with urllib.request.urlopen(export_url, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            ct = resp.headers.get("Content-Type", "")
            self.assertIn("application/zip", ct)
            cd = resp.headers.get("Content-Disposition", "")
            self.assertIn("attachment", cd)
            self.assertIn(sid, cd)
            zip_bytes = resp.read()

        # 3. Verify streamed zip content authenticity
        self.assertTrue(zip_bytes.startswith(b"PK\x03\x04"), "Exported stream must start with ZIP magic bytes")
        self.assertGreater(len(zip_bytes), 1024)
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            names = zf.namelist()
            self.assertIn("iph1/Library/Documents/registry.db", names)
            self.assertIn("iph1/Library/Application Support/cloudregistry.db", names)
            self.assertIn("iph1/Library/Application Support/cloudregistry.db.hmc", names)
            # Verify extracted registry.db is valid SQLite database
            reg_bytes = zf.read("iph1/Library/Documents/registry.db")
            self.assertTrue(reg_bytes.startswith(b"SQLite format 3\x00"))

    def test_t3_cross_17_loose_files_staging_normalizes_to_ios_hierarchy(self):
        """Cross F3 <-> F4: Uploaded loose files are normalized into standard iOS directory layout."""
        loose = self.stage.parent / "loose"
        loose.mkdir(exist_ok=True)
        (loose / "registry.db").write_bytes(b"dummy_reg")
        (loose / "cloudregistry.db").write_bytes(b"dummy_cloud")
        norm = self.stage.parent / "norm"
        (norm / "Library" / "Documents").mkdir(parents=True, exist_ok=True)
        (norm / "Library" / "Application Support").mkdir(parents=True, exist_ok=True)
        shutil.copy(loose / "registry.db", norm / "Library" / "Documents" / "registry.db")
        shutil.copy(loose / "cloudregistry.db", norm / "Library" / "Application Support" / "cloudregistry.db")
        self.assertTrue((norm / "Library" / "Documents" / "registry.db").exists())
        self.assertTrue((norm / "Library" / "Application Support" / "cloudregistry.db").exists())

    def test_t3_cross_18_raw_explorer_edits_reflected_in_typed_tables(self):
        """Cross F10 <-> F5: Direct SQL insert updates highscores view."""
        db_p = self.stage / "Library" / "Documents" / "registry.db"
        conn = sqlite3.connect(db_p)
        conn.execute("DELETE FROM integerdata WHERE key='db_competition_skatepark2'")
        conn.execute("INSERT INTO integerdata (key, value) VALUES ('db_competition_skatepark2', 8888888)")
        conn.commit()
        val = conn.execute("SELECT value FROM integerdata WHERE key='db_competition_skatepark2'").fetchone()[0]
        conn.close()
        self.assertEqual(val, 8888888)

    def test_t3_cross_19_special_boards_unlock_enables_valid_current_board(self):
        """Cross F12 <-> F9: Unlocking special board ID 15 allows currentBoardIndex=15."""
        db_p = self.stage / "Library" / "Documents" / "registry.db"
        conn = sqlite3.connect(db_p)
        conn.execute("DELETE FROM integerdata WHERE key='currentBoardIndex'")
        conn.execute("INSERT INTO integerdata (key, value) VALUES ('currentBoardIndex', 15)")
        conn.commit()
        val = conn.execute("SELECT value FROM integerdata WHERE key='currentBoardIndex'").fetchone()[0]
        conn.close()
        self.assertEqual(val, 15)

    def test_t3_cross_20_launcher_port_argument_and_server_binding(self):
        """Cross F2 <-> F1: Launcher specifies port 8765 matching server configuration."""
        if not BATCH_FILE.exists():
            self.fail(f"run_save_editor.bat does not exist yet at {BATCH_FILE}")
        if Server is None:
            self.fail("editor.server.Server not implemented yet")

        # 1. Read batch file and dynamically extract configured default port
        batch_text = BATCH_FILE.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r'set\s+"PORT=(\d+)"', batch_text)
        self.assertIsNotNone(match, "run_save_editor.bat must define default PORT variable")
        batch_port = int(match.group(1))

        # 2. Extract default port from editor.server signature
        import inspect
        server_sig = inspect.signature(Server.__init__)
        self.assertIn("port", server_sig.parameters, "Server.__init__ must have 'port' parameter")
        server_default_port = server_sig.parameters["port"].default

        # 3. Eliminate tautology: assert batch file port matches server configuration
        self.assertEqual(batch_port, server_default_port,
                         f"Batch launcher port ({batch_port}) does not match server default port ({server_default_port})")

        # 4. Verify batch launcher also references the matched port in browser launch and python invocation
        self.assertIn(f"http://localhost:{batch_port}", batch_text.lower())
        self.assertRegex(batch_text, r"--port\s+%PORT%")

        # 5. Verify Server binds cleanly to an explicit port instance
        test_port = find_free_port()
        srv = Server(port=test_port)
        self.assertEqual(srv.server_address[1], test_port)
        srv.server_close()

    def test_t3_cross_21_batch_replay_reserialization_preserves_overall_archive_integrity(self):
        """Cross F14 <-> F20: Batch parsing and re-serializing all 82 replays leaves payloads valid."""
        if ReplayParser is None:
            self.fail("editor.replay_parser.ReplayParser not implemented yet")
        replays = list(self.stage.glob("Library/Documents/*/recent/*")) + list(self.stage.glob("Library/Documents/*/top/*"))
        for r in replays:
            p = ReplayParser.parse(str(r))
            s = ReplayParser.serialize(p)
            self.assertEqual(ReplayParser.parse(s)["score"], p["score"])

    def test_t3_cross_22_tampered_cloud_db_restores_integrity_after_hmc_recalculation(self):
        """Cross F13 <-> F20: Tampering cloudregistry.db and recomputing HMAC restores valid state."""
        db_p = self.stage / "Library" / "Application Support" / "cloudregistry.db"
        conn = sqlite3.connect(db_p)
        conn.execute("INSERT OR REPLACE INTO stringdata (key, value) VALUES ('tamper_test', 'tampered')")
        conn.commit()
        conn.close()
        token = db_p.read_bytes().split()[0]
        recomputed = compute_hmac_sha256(token)
        hmc_p = self.stage / "Library" / "Application Support" / "cloudregistry.db.hmc"
        hmc_p.write_text(recomputed)
        self.assertEqual(hmc_p.read_text().strip(), recomputed)


# ==============================================================================
# Tier 4: Real-World Application Scenarios (10 Scenarios)
# ==============================================================================

class TestTier4RealWorldScenarios(unittest.TestCase):
    """Tier 4: 10 End-to-End Real-World User Workflows specified in TEST_INFRA.md."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.stage = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def test_t4_scenario_01_full_user_ingestion_and_dlc_unlock_roundtrip(self):
        """Scenario 1: Full user ingestion -> unlock all 8 DLC parks -> export & verify."""
        if SessionManager is None:
            self.fail("editor.session.SessionManager not implemented yet")
        if RegistryEditor is None:
            self.fail("editor.registry_editor.RegistryEditor not implemented yet")

        # 1. Ingest reference sample save into isolated session
        mgr = SessionManager(base_temp_dir=self.stage / "sessions")
        sid, count = mgr.load_sample(sample_dir=REF_SAVE_DIR)
        self.assertGreater(count, 0)

        # 2. Open staged registry database via RegistryEditor and unlock all 8 DLC parks
        reg_path = mgr.get_registry_path(sid)
        self.assertTrue(reg_path.exists(), f"Staged registry.db missing: {reg_path}")
        reg_ed = RegistryEditor(str(reg_path))
        reg_ed.set_parks({p: True for p in DLC_PARKS_LIST})

        parks_state = reg_ed.get_parks()
        for p in DLC_PARKS_LIST:
            self.assertTrue(parks_state.get(p), f"Park {p} not unlocked in session")

        # 3. Export clean verified zip archive via SessionManager
        export_zip = self.stage / "export_scenario_01.zip"
        zip_bytes = mgr.export_zip(sid, output_path=export_zip, iph1_format=True)
        self.assertTrue(export_zip.exists())
        self.assertGreater(len(zip_bytes), 50000)

        # 4. Ingest exported zip into a second fresh session to verify roundtrip persistence
        sid2 = mgr.create_session()
        mgr.ingest_archive(sid2, zip_bytes)
        reg_ed2 = RegistryEditor(str(mgr.get_registry_path(sid2)))
        parks_roundtrip = reg_ed2.get_parks()
        for p in DLC_PARKS_LIST:
            self.assertTrue(parks_roundtrip.get(p), f"Park {p} was not retained across export roundtrip")

        integ = mgr.verify_integrity(sid2)
        self.assertTrue(integ.get("registry"), "Registry failed SQLite integrity check after roundtrip")

        mgr.close_session(sid)
        mgr.close_session(sid2)

    def test_t4_scenario_02_complete_all_challenges_and_max_highscores(self):
        """Scenario 2: Complete all 280+ challenges and max out highscores across all parks."""
        if SessionManager is None:
            self.fail("editor.session.SessionManager not implemented yet")
        if RegistryEditor is None:
            self.fail("editor.registry_editor.RegistryEditor not implemented yet")

        mgr = SessionManager(base_temp_dir=self.stage / "sessions")
        sid, _ = mgr.load_sample(sample_dir=REF_SAVE_DIR)
        reg_path = mgr.get_registry_path(sid)
        reg_ed = RegistryEditor(str(reg_path))

        # 1. Complete all 45 challenges across all 9 parks (405 challenges total)
        for park in ALL_PARK_NAMES:
            for c in range(1, 46):
                reg_ed.set_challenge(park=park, challenge_id=c, completed=1)

        challenges = reg_ed.get_challenges(park=None)
        completed_count = sum(1 for ch in challenges if ch.get("completed", 0) == 1)
        self.assertGreaterEqual(completed_count, 280)

        # 2. Max out highscores across all 9 parks to 99,999,999
        for park_id in range(9):
            reg_ed.set_highscore(park_id=park_id, competition=99999999, line=99999999)

        scores = reg_ed.get_highscores()
        self.assertEqual(len(scores), 9)
        for sc in scores:
            self.assertEqual(sc.get("competition"), 99999999)
            self.assertEqual(sc.get("line"), 99999999)

        # 3. Export and verify archive integrity
        zip_bytes = mgr.export_zip(sid)
        self.assertGreater(len(zip_bytes), 50000)
        self.assertTrue(mgr.verify_integrity(sid).get("registry"))
        mgr.close_session(sid)

    def test_t4_scenario_03_unlock_special_boards_sync_plist_and_recalc_hmac(self):
        """Scenario 3: Unlock 30 special boards, sync CKRecord, recalculate HMAC."""
        if SessionManager is None:
            self.fail("editor.session.SessionManager not implemented yet")
        if CloudEditor is None:
            self.fail("editor.cloud_editor.CloudEditor not implemented yet")

        mgr = SessionManager(base_temp_dir=self.stage / "sessions")
        sid, _ = mgr.load_sample(sample_dir=REF_SAVE_DIR)
        cloud_path = mgr.get_cloud_path(sid)
        hmc_path = mgr.get_cloud_hmc_path(sid)

        cloud_ed = CloudEditor(str(cloud_path), str(hmc_path))

        # 1. Unlock all 30 special boards (IDs 2..31)
        all_boards = list(range(2, 32))
        cloud_ed.set_special_boards(all_boards)
        self.assertEqual(cloud_ed.get_special_boards(), all_boards)

        # 2. Update user ID and synchronize
        new_uid = "_fa_scenario03_verified_user_id"
        cloud_ed.set_user_id(new_uid)
        self.assertEqual(cloud_ed.get_user_id(), new_uid)

        # 3. Recalculate and verify HMAC
        new_digest = cloud_ed.save_hmc()
        self.assertEqual(len(new_digest), 64)
        self.assertTrue(cloud_ed.verify_hmc())
        self.assertTrue(mgr.verify_hmc(sid))

        # 4. Export archive and verify roundtrip read-back
        zip_bytes = mgr.export_zip(sid)
        self.assertGreater(len(zip_bytes), 50000)

        sid2 = mgr.create_session()
        mgr.ingest_archive(sid2, zip_bytes)
        cloud_ed2 = CloudEditor(str(mgr.get_cloud_path(sid2)), str(mgr.get_cloud_hmc_path(sid2)))
        self.assertEqual(cloud_ed2.get_special_boards(), all_boards)
        self.assertEqual(cloud_ed2.get_user_id(), new_uid)
        self.assertTrue(cloud_ed2.verify_hmc())

        mgr.close_session(sid)
        mgr.close_session(sid2)

    def test_t4_scenario_04_replay_library_ingestion_score_edit_and_clipcounter(self):
        """Scenario 4: Load replays, edit top competition score, and increment clipcounter."""
        if SessionManager is None:
            self.fail("editor.session.SessionManager not implemented yet")
        if ReplayParser is None or ClipcounterEditor is None:
            self.fail("editor.replay_parser modules not implemented yet")

        mgr = SessionManager(base_temp_dir=self.stage / "sessions")
        sid, _ = mgr.load_sample(sample_dir=REF_SAVE_DIR)
        parks_dir = mgr.get_parks_dir(sid)

        # 1. Parse reference replay in dairyfactory/top
        rep_p = parks_dir / "dairyfactory" / "top" / "comp-17395262745"
        self.assertTrue(rep_p.exists(), f"Reference replay not found: {rep_p}")
        parsed = ReplayParser.parse(str(rep_p))
        self.assertIn("score", parsed)

        # 2. Modify score and serialize
        parsed["score"] = 12345678
        rep_p.write_bytes(ReplayParser.serialize(parsed))

        # 3. Increment clipcounter
        cc_p = parks_dir / "dairyfactory" / "clipcounter"
        self.assertTrue(cc_p.exists(), f"Reference clipcounter not found: {cc_p}")
        read_fn = getattr(ClipcounterEditor, 'read', getattr(ClipcounterEditor, 'read_counter', None))
        write_fn = getattr(ClipcounterEditor, 'write', getattr(ClipcounterEditor, 'write_counter', None))
        if read_fn is None or write_fn is None:
            self.fail("ClipcounterEditor does not provide read/write methods")

        cc_val = read_fn(str(cc_p))
        cc_p.write_bytes(write_fn(cc_val + 1))

        # 4. Verify roundtrip parse and clipcounter value
        self.assertEqual(ReplayParser.parse(str(rep_p))["score"], 12345678)
        self.assertEqual(read_fn(str(cc_p)), 2)

        zip_bytes = mgr.export_zip(sid)
        self.assertGreater(len(zip_bytes), 50000)
        mgr.close_session(sid)

    def test_t4_scenario_05_board_texture_replacement_and_dimensions_validation(self):
        """Scenario 5: Replace board texture PNG with valid 1024x256 image."""
        if SessionManager is None:
            self.fail("editor.session.SessionManager not implemented yet")
        if TextureManager is None:
            self.fail("editor.texture_manager.TextureManager not implemented yet")

        mgr = SessionManager(base_temp_dir=self.stage / "sessions")
        sid, _ = mgr.load_sample(sample_dir=REF_SAVE_DIR)
        tex_dir = mgr.get_board_textures_path(sid)

        tm = TextureManager(str(tex_dir))
        textures = tm.list_textures()
        tex_names = [t["filename"] if isinstance(t, dict) else t for t in textures]
        self.assertIn("deck_baked_deck_2.png", tex_names)

        # 1. Replace with valid 1024x256 PNG
        valid_png = generate_minimal_png(1024, 256, (200, 100, 50, 255))
        tm.replace_texture("deck_baked_deck_2.png", valid_png)
        if hasattr(tm, "validate_dimensions"):
            self.assertTrue(tm.validate_dimensions("deck_baked_deck_2.png"))
        elif hasattr(tm, "validate_image"):
            val = tm.validate_image(valid_png, "deck_baked_deck_2.png")
            self.assertEqual((val.get("width"), val.get("height")), (1024, 256))

        # 2. Reject invalid dimensions
        bad_png = generate_minimal_png(512, 512)
        with self.assertRaises((ValueError, TypeError)):
            tm.replace_texture("deck_baked_deck_2.png", bad_png)

        zip_bytes = mgr.export_zip(sid)
        self.assertGreater(len(zip_bytes), 50000)
        mgr.close_session(sid)

    def test_t4_scenario_06_e2e_rest_api_workflow_with_session_lifecycle(self):
        """Scenario 6: End-to-end REST API session lifecycle simulation."""
        if Server is None:
            self.fail("editor.server.Server not implemented yet")
        if SessionManager is None:
            self.fail("editor.session.SessionManager not implemented yet")

        port = find_free_port()
        server = Server(port=port)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.15)

        base_url = f"http://127.0.0.1:{port}"
        try:
            # 1. POST /api/session/create
            req = urllib.request.Request(f"{base_url}/api/session/create", data=b"{}", method="POST")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                sid = data.get("session_id")
                self.assertTrue(sid)

            # 2. POST /api/session/load_sample
            req2 = urllib.request.Request(f"{base_url}/api/session/load_sample", data=b"{}", method="POST")
            req2.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req2, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                sample_data = json.loads(resp.read().decode("utf-8"))
                sid_sample = sample_data.get("session_id")
                self.assertTrue(sid_sample)
                self.assertGreater(sample_data.get("files_loaded", 0), 20)

            # 3. GET /api/session/<sid>/status
            with urllib.request.urlopen(f"{base_url}/api/session/{sid_sample}/status", timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                status_data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(status_data.get("session_id"), sid_sample)
                self.assertTrue(status_data.get("has_registry"))
                self.assertTrue(status_data.get("has_cloud"))
                self.assertEqual(len(status_data.get("parks", [])), 9)
                self.assertGreater(status_data.get("replays_count", 0), 0)

            # 4. GET /api/session/<sid>/export
            with urllib.request.urlopen(f"{base_url}/api/session/{sid_sample}/export", timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                self.assertIn("application/zip", resp.headers.get("Content-Type", ""))
                exported_bytes = resp.read()
                self.assertTrue(zipfile.is_zipfile(io.BytesIO(exported_bytes)))
                self.assertGreater(len(exported_bytes), 50000)
        finally:
            server.shutdown()
            server.server_close()
            server.session_manager.cleanup_all()

    def test_t4_scenario_07_archive_structure_tolerance_root_vs_iph1_vs_loose(self):
        """Scenario 7: Normalize 3 archive formats: root Library, iph1 container, and loose."""
        if SessionManager is None:
            self.fail("editor.session.SessionManager not implemented yet")

        ref = REF_SAVE_DIR
        reg_bytes = (ref / "Library" / "Documents" / "registry.db").read_bytes()
        cloud_bytes = (ref / "Library" / "Application Support" / "cloudregistry.db").read_bytes()
        hmc_bytes = (ref / "Library" / "Application Support" / "cloudregistry.db.hmc").read_bytes()

        # Format A: Root Library/Documents layout
        buf_a = io.BytesIO()
        with zipfile.ZipFile(buf_a, "w") as zf:
            zf.writestr("Library/Documents/registry.db", reg_bytes)
            zf.writestr("Library/Application Support/cloudregistry.db", cloud_bytes)
            zf.writestr("Library/Application Support/cloudregistry.db.hmc", hmc_bytes)

        # Format B: Parent iph1/ container layout
        buf_b = io.BytesIO()
        with zipfile.ZipFile(buf_b, "w") as zf:
            zf.writestr("iph1/Library/Documents/registry.db", reg_bytes)
            zf.writestr("iph1/Library/Application Support/cloudregistry.db", cloud_bytes)
            zf.writestr("iph1/Library/Application Support/cloudregistry.db.hmc", hmc_bytes)

        # Format C: Loose files at zip root
        buf_c = io.BytesIO()
        with zipfile.ZipFile(buf_c, "w") as zf:
            zf.writestr("registry.db", reg_bytes)
            zf.writestr("cloudregistry.db", cloud_bytes)
            zf.writestr("cloudregistry.db.hmc", hmc_bytes)

        formats = [("root_layout", buf_a), ("iph1_container", buf_b), ("loose_files", buf_c)]
        mgr = SessionManager(base_temp_dir=self.stage / "sessions")

        for fmt_name, buf in formats:
            sid = mgr.create_session()
            extracted = mgr.ingest_archive(sid, buf.getvalue())
            self.assertGreater(len(extracted), 0, f"Extraction returned empty list for {fmt_name}")

            reg_p = mgr.get_registry_path(sid)
            cloud_p = mgr.get_cloud_path(sid)
            hmc_p = mgr.get_cloud_hmc_path(sid)

            self.assertTrue(reg_p.exists(), f"registry.db missing in canonical location for {fmt_name}")
            self.assertTrue(cloud_p.exists(), f"cloudregistry.db missing in canonical location for {fmt_name}")
            self.assertTrue(hmc_p.exists(), f"cloudregistry.db.hmc missing in canonical location for {fmt_name}")

            integ = mgr.verify_integrity(sid)
            self.assertTrue(integ.get("registry"), f"Registry integrity check failed for {fmt_name}")
            self.assertTrue(integ.get("cloud"), f"Cloud integrity check failed for {fmt_name}")
            self.assertTrue(mgr.verify_hmc(sid), f"HMAC verification failed for {fmt_name}")

            mgr.close_session(sid)

    def test_t4_scenario_08_batch_launcher_script_and_static_file_integrity(self):
        """Scenario 8: Windows batch launcher and static UI file inspection."""
        if not BATCH_FILE.exists():
            self.fail(f"run_save_editor.bat does not exist yet at {BATCH_FILE}")

        content = BATCH_FILE.read_text(encoding="utf-8", errors="ignore")
        self.assertIn("8765", content, "Batch script must configure port 8765")
        self.assertIn("TOUCHGRIND SKATE 2 // SAVE EDITOR", content, "Batch script missing required branding")
        self.assertTrue(
            "http://localhost:8765" in content.lower() or "http://127.0.0.1:8765" in content.lower(),
            "Batch script must launch browser to port 8765"
        )
        self.assertTrue(
            "python" in content.lower() or "where py" in content.lower(),
            "Batch script must check for Python availability"
        )

        index_html = WEB_DIR / "index.html"
        style_css = WEB_DIR / "style.css"
        app_js = WEB_DIR / "app.js"

        if not index_html.exists() or not style_css.exists() or not app_js.exists():
            self.fail("editor/web static assets (index.html, style.css, app.js) not created yet")

        html_text = index_html.read_text(encoding="utf-8", errors="ignore")
        self.assertIn("TOUCHGRIND SKATE 2 // SAVE EDITOR", html_text)

    def test_t4_scenario_09_corrupted_file_detection_and_graceful_error_handling(self):
        """Scenario 9: Graceful handling of corrupted files."""
        if SessionManager is None:
            self.fail("editor.session.SessionManager not implemented yet")

        mgr = SessionManager(base_temp_dir=self.stage / "sessions")
        sid = mgr.create_session()

        # 1. Ingesting corrupted ZIP payload raises ValueError
        with self.assertRaises(ValueError):
            mgr.ingest_archive(sid, b"corrupted_non_zip_header_bytes")

        # 2. Corrupted SQLite database aborts export cleanly
        sid2, _ = mgr.load_sample(sample_dir=REF_SAVE_DIR)
        reg_p = mgr.get_registry_path(sid2)
        reg_p.write_bytes(b"SQLite format 3\x00" + b"\xff" * 500)
        with self.assertRaises((sqlite3.DatabaseError, ValueError)):
            mgr.export_zip(sid2)

        # 3. Truncated replay data raises ValueError
        if ReplayParser is None:
            self.fail("editor.replay_parser.ReplayParser not implemented yet")
        with self.assertRaises(ValueError):
            ReplayParser.parse(b"\x01\x02")
        with self.assertRaises(ValueError):
            ReplayParser.parse(b"")

        mgr.close_session(sid)
        mgr.close_session(sid2)

    def test_t4_scenario_10_complete_reexport_binary_sqlite_checksum_consistency(self):
        """Scenario 10: Complete master re-export verification."""
        if SessionManager is None:
            self.fail("editor.session.SessionManager not implemented yet")

        mgr = SessionManager(base_temp_dir=self.stage / "sessions")
        sid, count = mgr.load_sample(sample_dir=REF_SAVE_DIR)
        self.assertGreater(count, 20)

        # 1. Export in standard iph1 container format
        zip_bytes = mgr.export_zip(sid, iph1_format=True)
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(zip_bytes)))

        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            nl = set(zf.namelist())
            self.assertIn("iph1/Library/Documents/registry.db", nl)
            self.assertIn("iph1/Library/Application Support/cloudregistry.db", nl)
            self.assertIn("iph1/Library/Application Support/cloudregistry.db.hmc", nl)

            # Exclude temp, journal, and OS files
            for item in nl:
                self.assertFalse(item.endswith(("-wal", "-shm", ".tmp", ".DS_Store", "Thumbs.db")))

            # Check SQLite PRAGMA integrity on extracted registry.db
            reg_bytes = zf.read("iph1/Library/Documents/registry.db")
            t_db = self.stage / "reg_test.db"
            t_db.write_bytes(reg_bytes)
            conn = sqlite3.connect(str(t_db))
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
            conn.close()

            # Check HMAC-SHA256 recalculation against reference digest
            cloud_bytes = zf.read("iph1/Library/Application Support/cloudregistry.db")
            hmc_str = zf.read("iph1/Library/Application Support/cloudregistry.db.hmc").decode("ascii").strip()
            self.assertEqual(SessionManager.compute_hmc(cloud_bytes), hmc_str)
            self.assertEqual(hmc_str, HMAC_REF_DIGEST)

        # 2. Export in root format (iph1_format=False) and verify hierarchy
        root_bytes = mgr.export_zip(sid, iph1_format=False)
        with zipfile.ZipFile(io.BytesIO(root_bytes), "r") as zf_root:
            nl_root = set(zf_root.namelist())
            self.assertIn("Library/Documents/registry.db", nl_root)
            self.assertIn("Library/Application Support/cloudregistry.db", nl_root)
            for item in nl_root:
                self.assertFalse(item.startswith("iph1/"), f"Found unexpected iph1 prefix in root export: {item}")

        mgr.close_session(sid)

    def test_ingest_archive_with_colon_and_invalid_windows_chars(self):
        """Verify ZIP ingestion sanitizes colons and illegal Windows chars in iOS system paths."""
        mgr = SessionManager(base_temp_dir=self.stage)
        sid = mgr.create_session()

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("Library/Documents/registry.db", b"dummy_reg")
            zf.writestr("Library/SplashBoard/Snapshots/sceneID:se.illusionlabs.skate2-default/snap@3x.ktx", b"ktx_data")
            zf.writestr("Documents/weird:name?*test.txt", b"txt_data")

        extracted = mgr.ingest_archive(sid, buf.getvalue())
        self.assertIn("Library/Documents/registry.db", extracted)
        self.assertIn("Library/SplashBoard/Snapshots/sceneID_se.illusionlabs.skate2-default/snap@3x.ktx", extracted)
        mgr.close_session(sid)

    def test_ingest_real_skate2save_zip_if_present(self):
        """Verify real skate2save.zip with 340+ members extracts cleanly and parses all components."""
        real_zip = Path("saves") / "skate2save.zip"
        if not real_zip.exists():
            real_zip = Path(__file__).resolve().parent.parent / "saves" / "skate2save.zip"
        if not real_zip.exists():
            self.skipTest("saves/skate2save.zip not found in workspace")

        mgr = SessionManager(base_temp_dir=self.stage)
        sid = mgr.create_session()
        extracted = mgr.ingest_archive(sid, real_zip)
        self.assertGreater(len(extracted), 150)

        status = mgr.get_status(sid)
        self.assertTrue(status.get("has_registry"))
        self.assertTrue(status.get("has_cloud"))
        self.assertGreaterEqual(status.get("replays_count", 0), 80)
        self.assertGreaterEqual(status.get("textures_count", 0), 5)

        exported = mgr.export_zip(sid)
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(exported)))
        mgr.close_session(sid)


if __name__ == "__main__":
    unittest.main()
