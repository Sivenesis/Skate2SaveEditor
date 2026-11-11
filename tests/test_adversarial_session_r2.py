"""Adversarial stress test suite for Milestone 1 Iteration 2 (Challenger R2-1).

Tests:
1. Multiple open registered SQLite connections with active transactions closed during close_session().
2. Concurrency stress across 10 threads for session creation, editing, export, and cleanup.
3. Corrupted zip member payload reading and ValueError wrapping verification.
"""

from __future__ import annotations

import concurrent.futures
import io
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from editor.session import SessionManager


class TestMultipleRegisteredConnectionsWithActiveTransactions(unittest.TestCase):
    """Stress test registered SQLite connections with active transactions and open cursors."""

    def setUp(self):
        self.sm = SessionManager()

    def tearDown(self):
        self.sm.cleanup_all()

    def test_multiple_clean_registered_connections_closed(self):
        """Multiple registered connections across registry.db and cloudregistry.db."""
        sid = self.sm.create_session()
        reg_p = self.sm.get_registry_path(sid)
        cloud_p = self.sm.get_cloud_path(sid)

        # Initialize tables
        c = sqlite3.connect(str(reg_p))
        c.execute("CREATE TABLE reg (id INT PRIMARY KEY, name TEXT)")
        c.commit()
        c.close()

        c = sqlite3.connect(str(cloud_p))
        c.execute("CREATE TABLE cloud (id INT PRIMARY KEY, key TEXT)")
        c.commit()
        c.close()

        # Open 4 connections with active uncommitted transactions
        conn1 = sqlite3.connect(str(reg_p))
        conn1.execute("INSERT INTO reg VALUES (1, 'val1')")

        conn2 = sqlite3.connect(str(reg_p))
        conn2.execute("SELECT * FROM reg")

        conn3 = sqlite3.connect(str(cloud_p))
        conn3.execute("INSERT INTO cloud VALUES (10, 'key10')")

        conn4 = sqlite3.connect(str(cloud_p))
        conn4.execute("SELECT * FROM cloud")

        for conn in [conn1, conn2, conn3, conn4]:
            self.sm.register_connection(sid, conn)

        sdir = self.sm.get_session_dir(sid)
        self.sm.close_session(sid)

        # Clean up local variables in case session manager failed
        for conn in [conn1, conn2, conn3, conn4]:
            try:
                conn.close()
            except Exception:
                pass

        self.assertFalse(self.sm.has_session(sid))
        self.assertFalse(sdir.exists(), f"Session directory {sdir} was left orphaned on disk!")

    def test_registered_connection_with_active_open_cursor(self):
        """CRITICAL: Exposes defect where open cursor prevents PRAGMA wal_checkpoint, skipping conn.close().
        
        When conn1 has an active open cursor (in-progress SELECT statement) and conn2 is registered,
        wal_checkpoint raises an operational error. Because conn.close() is placed after checkpoint
        inside the try block without finally, conn1/conn2 are never closed, locking the file on Windows.
        """
        sid = self.sm.create_session()
        reg_p = self.sm.get_registry_path(sid)

        c = sqlite3.connect(str(reg_p))
        c.execute("CREATE TABLE t (id INT)")
        for i in range(10):
            c.execute("INSERT INTO t VALUES (?)", (i,))
        c.commit()
        c.close()

        conn1 = sqlite3.connect(str(reg_p))
        cursor1 = conn1.cursor()
        cursor1.execute("SELECT * FROM t")
        # Keep cursor active without exhausting rows

        conn2 = sqlite3.connect(str(reg_p))
        conn2.execute("INSERT INTO t VALUES (99)")

        self.sm.register_connection(sid, conn1)
        self.sm.register_connection(sid, conn2)

        sdir = self.sm.get_session_dir(sid)
        self.sm.close_session(sid)

        # Inspect if directory still exists (WinError 32 leak)
        dir_leaked = sdir.exists()

        # Clean up handles manually to avoid polluting subsequent tests
        try:
            cursor1.close()
        except Exception:
            pass
        for conn in [conn1, conn2]:
            try:
                conn.close()
            except Exception:
                pass

        # If leaked, try to clean up directory now that handles are explicitly closed
        if dir_leaked and sdir.exists():
            try:
                shutil.rmtree(sdir)
            except Exception:
                pass

        self.assertFalse(
            dir_leaked,
            "DEFECT CONFIRMED: close_session() failed to close registered connections "
            "when an active statement or uncommitted transaction caused wal_checkpoint to fail. "
            "conn.close() was skipped because it is inside try without finally, "
            "leaving registry.db locked by WinError 32 and orphaning the session directory!",
        )

    def test_registered_connection_on_corrupted_db(self):
        """CRITICAL: If a registered database file is corrupted, close_session must still close the connection."""
        sid = self.sm.create_session()
        reg_p = self.sm.get_registry_path(sid)

        c = sqlite3.connect(str(reg_p))
        c.execute("CREATE TABLE t (id INT)")
        c.commit()
        c.close()

        conn = sqlite3.connect(str(reg_p))
        self.sm.register_connection(sid, conn)

        # Simulate database file corruption on disk
        with open(reg_p, "r+b") as f:
            f.seek(0)
            f.write(b"CORRUPTED_NOT_SQLITE_HEADER_1234567890")

        sdir = self.sm.get_session_dir(sid)
        self.sm.close_session(sid)

        dir_leaked = sdir.exists()

        try:
            conn.close()
        except Exception:
            pass

        if dir_leaked and sdir.exists():
            try:
                shutil.rmtree(sdir)
            except Exception:
                pass

        self.assertFalse(
            dir_leaked,
            "DEFECT CONFIRMED: close_session() failed to close registered connection on corrupted DB. "
            "PRAGMA wal_checkpoint failed with DatabaseError, skipping conn.close() and orphaning directory!",
        )


class TestRapidMultiThreadedSessionLifecycle(unittest.TestCase):
    """Stress rapid creation, ingestion, query, export, and destruction across 10 threads."""

    def setUp(self):
        self.sm = SessionManager()

    def tearDown(self):
        self.sm.cleanup_all()

    def test_10_thread_rapid_session_lifecycle_stress(self):
        """100 sessions created, populated, queried, exported, and closed across 10 threads."""
        session_dirs = []
        errors = []

        def worker(worker_id):
            worker_errs = []
            for i in range(10):
                try:
                    sid = self.sm.create_session()
                    sdir = self.sm.get_session_dir(sid)
                    session_dirs.append(sdir)

                    # Ingest metadata file
                    self.sm.ingest_file(sid, f"meta_{worker_id}.txt", f"worker_{worker_id}_run_{i}".encode())

                    # Setup isolated SQLite DB
                    reg_p = self.sm.get_registry_path(sid)
                    c = sqlite3.connect(str(reg_p))
                    c.execute("CREATE TABLE kv (k TEXT, v INT)")
                    c.execute("INSERT INTO kv VALUES (?, ?)", (f"k_{worker_id}", i))
                    c.commit()
                    self.sm.register_connection(sid, c)

                    # Export zip
                    z = self.sm.export_zip(sid)
                    if len(z) < 100:
                        worker_errs.append(f"Export zip too small: {len(z)}")

                    # Close session
                    self.sm.close_session(sid)

                    if self.sm.has_session(sid):
                        worker_errs.append(f"Session {sid} still registered")
                    if sdir.exists():
                        worker_errs.append(f"Session dir {sdir} still exists on disk")
                except Exception as ex:
                    worker_errs.append(f"Worker {worker_id} iter {i} ex: {type(ex).__name__}: {ex}")
            return worker_errs

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, w) for w in range(10)]
            for f in concurrent.futures.as_completed(futures):
                res = f.result()
                if res:
                    errors.extend(res)

        self.assertEqual(errors, [], f"Encountered concurrency errors: {errors[:5]}")
        orphaned = [d for d in session_dirs if d.exists()]
        self.assertEqual(orphaned, [], f"Found orphaned directories: {orphaned[:5]}")
        self.assertEqual(len(self.sm.list_sessions()), 0)

    def test_10_thread_concurrent_sample_loader(self):
        """Concurrent load_sample, export, and close across 10 threads."""
        try:
            from tests.synthetic_fixtures import get_synthetic_ref_dir
            sample_path = get_synthetic_ref_dir()
        except Exception:
            sample_path = PROJECT_ROOT / "saves" / "iph1"
        if not sample_path.exists():
            self.skipTest("Sample directory not found")

        session_dirs = []
        errors = []

        def worker(worker_id):
            worker_errs = []
            for i in range(3):
                try:
                    sid, count = self.sm.load_sample(sample_dir=sample_path)
                    sdir = self.sm.get_session_dir(sid)
                    session_dirs.append(sdir)

                    self.assertGreater(count, 0)
                    status = self.sm.get_status(sid)
                    self.assertTrue(status["has_registry"])
                    self.assertTrue(status["has_cloud"])

                    z = self.sm.export_zip(sid)
                    self.assertGreater(len(z), 1000)

                    self.sm.close_session(sid)
                    if self.sm.has_session(sid):
                        worker_errs.append(f"Session {sid} not removed")
                    if sdir.exists():
                        worker_errs.append(f"Session dir {sdir} still exists")
                except Exception as ex:
                    worker_errs.append(f"Worker {worker_id} iter {i} ex: {type(ex).__name__}: {ex}")
            return worker_errs

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, w) for w in range(10)]
            for f in concurrent.futures.as_completed(futures):
                res = f.result()
                if res:
                    errors.extend(res)

        self.assertEqual(errors, [], f"Encountered sample loader errors: {errors[:5]}")
        orphaned = [d for d in session_dirs if d.exists()]
        self.assertEqual(orphaned, [], f"Found orphaned directories: {orphaned[:5]}")


class TestCorruptedZipMemberPayloadReading(unittest.TestCase):
    """Verify that corruptions within ZIP member payloads consistently raise ValueError."""

    def setUp(self):
        self.sm = SessionManager()
        self.sid = self.sm.create_session()

    def tearDown(self):
        self.sm.close_session(self.sid)

    def test_corrupted_deflate_stream_payload(self):
        """Corrupted compressed stream in member payload must raise ValueError."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("Library/Documents/registry.db", b"payload_content_stream_12345" * 20)
        data = bytearray(buf.getvalue())
        fname = b"registry.db"
        offset = data.find(fname) + len(fname)
        data[offset + 4] ^= 0xAA
        data[offset + 5] ^= 0x55

        with self.assertRaises(ValueError) as ctx:
            self.sm.ingest_archive(self.sid, bytes(data))
        self.assertIn("Corrupted zip member", str(ctx.exception))

    def test_tampered_payload_crc32_mismatch(self):
        """Stored member with altered payload byte must trigger CRC-32 check and raise ValueError."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
            zf.writestr("Library/Documents/registry.db", b"stored_exact_database_payload")
        data = bytearray(buf.getvalue())
        idx = data.find(b"stored_exact_database_payload")
        data[idx] = ord("X")

        with self.assertRaises(ValueError) as ctx:
            self.sm.ingest_archive(self.sid, bytes(data))
        self.assertIn("Corrupted zip member", str(ctx.exception))

    def test_central_directory_crc32_mismatch(self):
        """Central directory CRC alteration must trigger CRC-32 mismatch and raise ValueError."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
            zf.writestr("Library/Documents/registry.db", b"stored_exact_database_payload")
        data = bytearray(buf.getvalue())
        cd = data.find(b"PK\x01\x02")
        data[cd + 16] ^= 0xFF

        with self.assertRaises(ValueError) as ctx:
            self.sm.ingest_archive(self.sid, bytes(data))
        self.assertIn("Corrupted zip member", str(ctx.exception))

    def test_encrypted_member_payload(self):
        """Encrypted zip member payload without password must raise ValueError."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("Library/Documents/registry.db", b"secret_unreadable_data")
        data = bytearray(buf.getvalue())
        data[6] |= 0x01
        cd = data.find(b"PK\x01\x02")
        if cd != -1:
            data[cd + 8] |= 0x01

        with self.assertRaises(ValueError) as ctx:
            self.sm.ingest_archive(self.sid, bytes(data))
        self.assertIn("Corrupted zip member", str(ctx.exception))

    def test_unsupported_compression_method(self):
        """Unsupported member compression method (e.g. method 99) must raise ValueError."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("Library/Documents/registry.db", b"custom_compression_data")
        data = bytearray(buf.getvalue())
        data[8] = 99
        data[9] = 0
        cd = data.find(b"PK\x01\x02")
        if cd != -1:
            data[cd + 10] = 99
            data[cd + 11] = 0

        with self.assertRaises(ValueError) as ctx:
            self.sm.ingest_archive(self.sid, bytes(data))
        self.assertIn("Corrupted zip member", str(ctx.exception))

    def test_multi_member_archive_with_one_corrupted_payload(self):
        """Archive with multiple valid members and one corrupted member payload must raise ValueError."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("iph1/Library/Documents/registry.db", b"valid_member_one")
            zf.writestr("iph1/Library/Preferences/com.illusionlabs.skate2.plist", b"valid_member_two_longer" * 10)
            zf.writestr("iph1/Library/Documents/board_textures/deck.png", b"valid_member_three")
        data = bytearray(buf.getvalue())
        fname = b"com.illusionlabs.skate2.plist"
        offset = data.find(fname) + len(fname)
        data[offset + 4] ^= 0x77
        data[offset + 5] ^= 0x33

        with self.assertRaises(ValueError) as ctx:
            self.sm.ingest_archive(self.sid, bytes(data))
        self.assertIn("Corrupted zip member", str(ctx.exception))

    def test_file_path_based_corrupted_member_payload(self):
        """Ingesting corrupted member from file path on disk must raise ValueError."""
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
            with zipfile.ZipFile(tf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("registry.db", b"data_on_disk_payload_stream" * 20)
            tf_path = tf.name

        try:
            with open(tf_path, "r+b") as f:
                d = bytearray(f.read())
                fname = b"registry.db"
                idx = d.find(fname) + len(fname)
                d[idx + 2] ^= 0xEE
                f.seek(0)
                f.write(d)

            with self.assertRaises(ValueError) as ctx:
                self.sm.ingest_archive(self.sid, tf_path)
            self.assertIn("Corrupted zip member", str(ctx.exception))
        finally:
            if os.path.exists(tf_path):
                os.unlink(tf_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
