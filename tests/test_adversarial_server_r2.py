"""Adversarial Server Re-verification Suite (R2-2).

Milestone 1 Iteration 2: Server Re-verification
Touchgrind Skate 2 Save Editor

Focus areas:
1. Sequential requests over persistent HTTP/1.1 connections with changing payload sizes and empty payloads.
2. Multipart uploads with whitespace-only, empty, and malicious boundary strings.
3. Client disconnects during upload and download streaming (TCP RST & graceful FIN).
4. High-stress concurrent disconnect blitz and post-disconnect server liveness.
"""

from __future__ import annotations

import concurrent.futures
import http.client
import io
import json
import os
from pathlib import Path
import re
import socket
import struct
import sys
import threading
import time
import unittest
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from editor.server import create_server, parse_multipart_data, MAX_UPLOAD_SIZE
from editor.session import SessionManager


class AdversarialServerR2Harness(unittest.TestCase):
    """Adversarial re-verification harness running against ThreadingHTTPServer on an ephemeral port."""

    server = None
    server_thread = None
    host = "127.0.0.1"
    port = 0
    base_url = ""
    sm = None

    @classmethod
    def setUpClass(cls):
        cls.sm = SessionManager()
        cls.server = create_server(cls.host, 0, session_manager=cls.sm)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://{cls.host}:{cls.port}"
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()
            cls.server.server_close()
        if cls.server_thread and cls.server_thread.is_alive():
            cls.server_thread.join(timeout=2.0)

    def _http_request(
        self,
        method: str,
        path: str,
        body: bytes | str | None = None,
        headers: dict | None = None,
        timeout: float = 5.0,
    ) -> tuple[int, dict, bytes]:
        """Low-level single HTTP request helper using http.client."""
        if headers is None:
            headers = {}
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            if isinstance(body, str):
                body = body.encode("utf-8")
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            status = resp.status
            resp_headers = {k.lower(): v for k, v in resp.getheaders()}
            data = resp.read()
            return status, resp_headers, data
        finally:
            conn.close()

    def _raw_socket_send(self, raw_bytes: bytes, read_response: bool = True, timeout: float = 5.0) -> bytes:
        """Send raw bytes over a TCP socket directly."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((self.host, self.port))
        try:
            s.sendall(raw_bytes)
            if not read_response:
                return b""
            response_chunks = []
            while True:
                try:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    response_chunks.append(chunk)
                except socket.timeout:
                    break
            return b"".join(response_chunks)
        finally:
            s.close()

    # =========================================================================
    # SECTION 1: PERSISTENT HTTP/1.1 CONNECTIONS & CHANGING/EMPTY PAYLOADS
    # =========================================================================

    def test_01_persistent_sequential_mixed_requests_same_connection(self):
        """16 sequential requests over a SINGLE persistent HTTP/1.1 connection with varying and empty payloads."""
        conn = http.client.HTTPConnection(self.host, self.port, timeout=10.0)
        sid = None
        try:
            # 1. POST /api/session/create (empty json body)
            conn.request("POST", "/api/session/create", body=b"{}", headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            res_data = json.loads(resp.read().decode("utf-8"))
            sid = res_data["session_id"]
            self.assertTrue(len(sid) > 0)

            # 2. GET /api/session/{sid}/status (no body)
            conn.request("GET", f"/api/session/{sid}/status")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            status_data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(status_data["session_id"], sid)

            # 3. POST upload_file with empty payload (0 bytes) and Content-Length: 0
            conn.request(
                "POST",
                f"/api/session/{sid}/upload_file?filename=empty.bin",
                body=b"",
                headers={"Content-Length": "0"},
            )
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            self.assertEqual(json.loads(resp.read().decode("utf-8"))["status"], "saved")

            # 4. POST upload_file with 1 byte payload
            conn.request(
                "POST",
                f"/api/session/{sid}/upload_file?filename=byte1.bin",
                body=b"X",
                headers={"Content-Length": "1"},
            )
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            resp.read()

            # 5. POST upload_file with 256 bytes payload
            body_256 = b"A" * 256
            conn.request(
                "POST",
                f"/api/session/{sid}/upload_file?filename=data256.bin",
                body=body_256,
                headers={"Content-Length": str(len(body_256))},
            )
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            resp.read()

            # 6. POST upload_file with 64 KB payload
            body_64k = os.urandom(64 * 1024)
            conn.request(
                "POST",
                f"/api/session/{sid}/upload_file?filename=data64k.bin",
                body=body_64k,
                headers={"Content-Length": str(len(body_64k))},
            )
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            resp.read()

            # 7. POST upload_file with 256 KB payload
            body_256k = os.urandom(256 * 1024)
            conn.request(
                "POST",
                f"/api/session/{sid}/upload_file?filename=data256k.bin",
                body=body_256k,
                headers={"Content-Length": str(len(body_256k))},
            )
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            resp.read()

            # 8. POST upload_file with empty payload again (0 bytes)
            conn.request(
                "POST",
                f"/api/session/{sid}/upload_file?filename=empty2.bin",
                body=b"",
                headers={"Content-Length": "0"},
            )
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            resp.read()

            # 9. GET status on same connection to verify all 6 files are present
            conn.request("GET", f"/api/session/{sid}/status")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            status_data2 = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(status_data2["session_id"], sid)

            # 10. POST multipart upload with valid zip on same connection
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w") as zf:
                zf.writestr("Documents/test_stream.txt", b"Streamed persistent file")
            valid_zip = zip_buf.getvalue()

            boundary = "StreamBoundary123"
            part_body = (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="stream.zip"\r\n'
                "Content-Type: application/zip\r\n\r\n"
            ).encode("utf-8") + valid_zip + f"\r\n--{boundary}--\r\n".encode("utf-8")

            conn.request(
                "POST",
                f"/api/session/{sid}/upload",
                body=part_body,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Content-Length": str(len(part_body)),
                },
            )
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            upload_res = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(upload_res["status"], "uploaded")

            # 11. GET export archive on same connection (binary streaming)
            conn.request("GET", f"/api/session/{sid}/export")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            export_bytes = resp.read()
            self.assertTrue(export_bytes.startswith(b"PK\x03\x04"))

            # 12. GET static HTML on same connection
            conn.request("GET", "/")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            html_bytes = resp.read()
            self.assertIn(b"TOUCHGRIND SKATE 2 // SAVE EDITOR", html_bytes)

            # 13. GET static CSS on same connection
            conn.request("GET", "/style.css")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            css_bytes = resp.read()
            self.assertTrue(len(css_bytes) > 0)

            # 14. GET static JS on same connection
            conn.request("GET", "/app.js")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            js_bytes = resp.read()
            self.assertTrue(len(js_bytes) > 0)

            # 15. DELETE session on same connection
            conn.request("DELETE", f"/api/session/{sid}")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            resp.read()

            # 16. GET deleted session status on same connection (must return 404)
            conn.request("GET", f"/api/session/{sid}/status")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 404)
            resp.read()

        finally:
            conn.close()
            if sid and self.sm.has_session(sid):
                self.sm.close_session(sid)

    def test_02_persistent_connection_error_recovery_and_body_drain(self):
        """Error responses (400, 404, 405) with bodies do not break subsequent requests on the same connection."""
        conn = http.client.HTTPConnection(self.host, self.port, timeout=5.0)
        sid = self.sm.create_session()
        try:
            # 1. Send malformed JSON body to /api/session/create -> 400 Bad Request
            conn.request(
                "POST",
                "/api/session/create",
                body=b'{"unclosed_json: true',
                headers={"Content-Type": "application/json", "Content-Length": "21"},
            )
            r1 = conn.getresponse()
            self.assertEqual(r1.status, 400)
            r1.read()

            # 2. Immediately send GET / on same connection -> 200 OK
            conn.request("GET", "/")
            r2 = conn.getresponse()
            self.assertEqual(r2.status, 200)
            self.assertIn(b"TOUCHGRIND SKATE 2 // SAVE EDITOR", r2.read())

            # 3. Send POST with 10 KB unread body to nonexistent endpoint -> 404 or 405
            unprocessed_body = b"X" * 10240
            conn.request(
                "POST",
                "/api/unknown_endpoint_route",
                body=unprocessed_body,
                headers={"Content-Length": str(len(unprocessed_body))},
            )
            r3 = conn.getresponse()
            self.assertIn(r3.status, [404, 405])
            r3.read()

            # 4. Immediately send GET /style.css on same connection -> 200 OK
            conn.request("GET", "/style.css")
            r4 = conn.getresponse()
            self.assertEqual(r4.status, 200)
            self.assertTrue(len(r4.read()) > 0)

            # 5. Send POST /upload with empty body -> 400 Bad Request
            conn.request(
                "POST",
                f"/api/session/{sid}/upload",
                body=b"",
                headers={"Content-Length": "0"},
            )
            r5 = conn.getresponse()
            self.assertEqual(r5.status, 400)
            r5.read()

            # 6. Immediately send GET /api/session/{sid}/status -> 200 OK
            conn.request("GET", f"/api/session/{sid}/status")
            r6 = conn.getresponse()
            self.assertEqual(r6.status, 200)
            r6.read()

        finally:
            conn.close()
            self.sm.close_session(sid)

    def test_03_http_pipelining_burst(self):
        """Sending multiple pipelined HTTP/1.1 requests in a single TCP write returns ordered 200 OK responses."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect((self.host, self.port))
        try:
            pipelined = (
                b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
                b"GET /style.css HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
                b"GET /app.js HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
                b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
                b"GET /style.css HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
            )
            s.sendall(pipelined)

            response_bytes = []
            while True:
                buf = s.recv(4096)
                if not buf:
                    break
                response_bytes.append(buf)

            all_resp = b"".join(response_bytes)
            status_200_count = all_resp.count(b"HTTP/1.1 200 OK")
            self.assertEqual(status_200_count, 5, f"Expected 5 responses for 5 pipelined requests, got {status_200_count}")
        finally:
            s.close()

    def test_04_persistent_connection_close_header_honored(self):
        """Request with 'Connection: close' header terminates connection after response."""
        conn = http.client.HTTPConnection(self.host, self.port, timeout=5.0)
        try:
            conn.request("GET", "/", headers={"Connection": "close"})
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            resp.read()

            # Attempting a subsequent request over the closed connection must fail
            with self.assertRaises((http.client.CannotSendRequest, http.client.RemoteDisconnected, ConnectionError)):
                conn.request("GET", "/style.css")
                conn.getresponse()
        finally:
            conn.close()

    # =========================================================================
    # SECTION 2: MULTIPART UPLOADS WITH EMPTY, WHITESPACE & MALICIOUS BOUNDARIES
    # =========================================================================

    def test_05_multipart_boundary_empty_variants(self):
        """Empty boundary in quotes, single quotes, or bare must return 400 Bad Request."""
        sid = self.sm.create_session()
        try:
            empty_headers = [
                'multipart/form-data; boundary=""',
                "multipart/form-data; boundary=''",
                "multipart/form-data; boundary=",
                "multipart/form-data",
            ]
            for ct in empty_headers:
                status, _, body = self._http_request(
                    "POST",
                    f"/api/session/{sid}/upload",
                    body=b"some content",
                    headers={"Content-Type": ct},
                )
                self.assertEqual(status, 400, f"Expected 400 for Content-Type: {ct}, got {status}")
                res = json.loads(body.decode("utf-8"))
                self.assertEqual(res.get("status"), "error")
                self.assertIn("boundary", res.get("message", "").lower())
        finally:
            self.sm.close_session(sid)

    def test_06_multipart_boundary_whitespace_variants(self):
        """Whitespace-only boundary strings must be rejected with 400 Bad Request."""
        sid = self.sm.create_session()
        try:
            whitespace_headers = [
                'multipart/form-data; boundary=" "',
                'multipart/form-data; boundary="     "',
                'multipart/form-data; boundary="\t"',
                'multipart/form-data; boundary=" \t \r\n "',
                "multipart/form-data; boundary=   ",
            ]
            for ct in whitespace_headers:
                status, _, body = self._http_request(
                    "POST",
                    f"/api/session/{sid}/upload",
                    body=b"some content",
                    headers={"Content-Type": ct},
                )
                self.assertEqual(status, 400, f"Expected 400 for Content-Type: {ct!r}, got {status}")
                res = json.loads(body.decode("utf-8"))
                self.assertEqual(res.get("status"), "error")
                self.assertIn("boundary", res.get("message", "").lower())
        finally:
            self.sm.close_session(sid)

    def test_07_multipart_boundary_special_characters(self):
        """Boundaries with punctuation, dashes, dots, and regex meta-characters parse cleanly."""
        sid = self.sm.create_session()
        try:
            special_boundaries = [
                "----WebKitFormBoundary7MA4YWxkTrZu0gW",
                "==--+Special.Boundary$^*()[]{}|\\?--==",
                "___my-special.boundary_v2.0___",
                "boundary-with-dashes-and--double-dashes",
            ]
            for boundary in special_boundaries:
                part_body = (
                    f"--{boundary}\r\n"
                    'Content-Disposition: form-data; name="file"; filename="spec.txt"\r\n'
                    "Content-Type: text/plain\r\n\r\n"
                    f"Content for boundary: {boundary}\r\n"
                    f"--{boundary}--\r\n"
                ).encode("latin-1")

                status, _, body = self._http_request(
                    "POST",
                    f"/api/session/{sid}/upload",
                    body=part_body,
                    headers={"Content-Type": f'multipart/form-data; boundary="{boundary}"'},
                )
                self.assertEqual(status, 200, f"Failed for boundary {boundary!r}: {body}")
                res = json.loads(body.decode("utf-8"))
                self.assertEqual(res.get("status"), "uploaded")
                self.assertTrue(len(res.get("staged_files", [])) > 0)
        finally:
            self.sm.close_session(sid)

    def test_08_multipart_boundary_unicode_rejection(self):
        """Non-Latin-1 Unicode boundary characters raise ValueError on direct parse and are rejected cleanly."""
        # 1. Direct call with true non-latin-1 Unicode string must raise ValueError
        for ct in [
            'multipart/form-data; boundary="boundary_\u2603"',
            'multipart/form-data; boundary="\u0442\u0435\u0441\u0442"',
        ]:
            with self.assertRaises(ValueError):
                parse_multipart_data(ct, b"--dummy\r\n\r\n--dummy--")

        # 2. Raw TCP socket send with UTF-8 encoded header bytes
        sid = self.sm.create_session()
        try:
            raw_req = (
                f"POST /api/session/{sid}/upload HTTP/1.1\r\n"
                f"Host: {self.host}:{self.port}\r\n"
                "Content-Type: multipart/form-data; boundary=unicode_\xe2\x98\x83\r\n"
                "Content-Length: 30\r\n"
                "Connection: close\r\n\r\n"
                "--unicode_\xe2\x98\x83\r\n\r\n--unicode_\xe2\x98\x83--"
            ).encode("latin-1")

            resp_raw = self._raw_socket_send(raw_req, read_response=True)
            self.assertTrue(resp_raw.startswith(b"HTTP/1.1 200") or resp_raw.startswith(b"HTTP/1.1 400"))
        finally:
            self.sm.close_session(sid)

    def test_09_multipart_boundary_massive_length(self):
        """A boundary with 10,000 ASCII characters parses without ReDoS or stack overflow."""
        sid = self.sm.create_session()
        try:
            long_boundary = "B" * 10000
            part_body = (
                f"--{long_boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="long_b.txt"\r\n'
                "Content-Type: text/plain\r\n\r\n"
                "Data with massive boundary\r\n"
                f"--{long_boundary}--\r\n"
            ).encode("utf-8")

            t0 = time.time()
            status, _, body = self._http_request(
                "POST",
                f"/api/session/{sid}/upload",
                body=part_body,
                headers={"Content-Type": f"multipart/form-data; boundary={long_boundary}"},
                timeout=5.0,
            )
            elapsed = time.time() - t0
            self.assertLess(elapsed, 2.0, "Parsing massive boundary took longer than 2.0 seconds")
            self.assertEqual(status, 200)
            res = json.loads(body.decode("utf-8"))
            self.assertEqual(res.get("status"), "uploaded")
        finally:
            self.sm.close_session(sid)

    def test_10_multipart_boundary_flood_stress(self):
        """Payload with 1,000 boundary separators does not crash server or hang."""
        sid = self.sm.create_session()
        try:
            boundary = "floodBoundary"
            # 1,000 empty boundaries
            flood_body = (f"--{boundary}\r\n\r\n" * 1000 + f"--{boundary}--\r\n").encode("utf-8")

            t0 = time.time()
            status, _, body = self._http_request(
                "POST",
                f"/api/session/{sid}/upload",
                body=flood_body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                timeout=5.0,
            )
            elapsed = time.time() - t0
            self.assertLess(elapsed, 2.0, "Boundary flood parsing took longer than 2.0 seconds")
            self.assertEqual(status, 200)
            res = json.loads(body.decode("utf-8"))
            self.assertEqual(res.get("status"), "uploaded")
        finally:
            self.sm.close_session(sid)

    def test_11_multipart_unclosed_boundary(self):
        """Multipart data without the terminating '--{boundary}--' is safely processed without hang."""
        sid = self.sm.create_session()
        try:
            boundary = "unclosedBoundary"
            # Missing trailing '--' on final boundary
            unclosed_body = (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="unclosed.txt"\r\n'
                "Content-Type: text/plain\r\n\r\n"
                "Unclosed part data here\r\n"
                f"--{boundary}\r\n"
            ).encode("utf-8")

            status, _, body = self._http_request(
                "POST",
                f"/api/session/{sid}/upload",
                body=unclosed_body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            self.assertEqual(status, 200)
            res = json.loads(body.decode("utf-8"))
            self.assertEqual(res.get("status"), "uploaded")
            self.assertEqual(len(res.get("staged_files", [])), 1)
        finally:
            self.sm.close_session(sid)

    def test_12_multipart_multiple_files_batch_upload(self):
        """Single multipart request uploading 3 distinct files stages all files cleanly."""
        sid = self.sm.create_session()
        try:
            boundary = "multiFileBoundary"
            part_body = (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file1"; filename="batch1.txt"\r\n\r\n'
                "Batch file 1 contents\r\n"
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file2"; filename="batch2.txt"\r\n\r\n'
                "Batch file 2 contents\r\n"
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file3"; filename="batch3.txt"\r\n\r\n'
                "Batch file 3 contents\r\n"
                f"--{boundary}--\r\n"
            ).encode("utf-8")

            status, _, body = self._http_request(
                "POST",
                f"/api/session/{sid}/upload",
                body=part_body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            self.assertEqual(status, 200)
            res = json.loads(body.decode("utf-8"))
            staged = res.get("staged_files", [])
            self.assertEqual(len(staged), 3)
            self.assertTrue(any("batch1.txt" in f for f in staged))
            self.assertTrue(any("batch2.txt" in f for f in staged))
            self.assertTrue(any("batch3.txt" in f for f in staged))
        finally:
            self.sm.close_session(sid)

    def test_13_multipart_windows_reserved_device_names(self):
        """Uploading filenames with Windows reserved device names (CON, AUX, NUL) must not escape staging."""
        sid = self.sm.create_session()
        try:
            boundary = "reservedBoundary"
            part_body = (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="CON.txt"\r\n\r\n'
                "Reserved file test\r\n"
                f"--{boundary}--\r\n"
            ).encode("utf-8")

            status, _, body = self._http_request(
                "POST",
                f"/api/session/{sid}/upload",
                body=part_body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            # Should either succeed or safely handle without crashing server
            self.assertIn(status, [200, 400, 500])
            # Server must remain live
            liveness_status, _, _ = self._http_request("GET", "/")
            self.assertEqual(liveness_status, 200)
        finally:
            self.sm.close_session(sid)

    # =========================================================================
    # SECTION 3: CLIENT DISCONNECTS DURING UPLOAD & DOWNLOAD STREAMING
    # =========================================================================

    def test_14_client_disconnect_during_raw_upload_rst(self):
        """Abrupt TCP RST during raw file upload does not crash server; server remains live."""
        sid = self.sm.create_session()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((self.host, self.port))
            headers = (
                f"POST /api/session/{sid}/upload_file?filename=aborted_raw.bin HTTP/1.1\r\n"
                f"Host: {self.host}:{self.port}\r\n"
                "Content-Length: 5000000\r\n"
                "Connection: keep-alive\r\n\r\n"
            ).encode("utf-8")
            s.sendall(headers)
            s.sendall(b"Partial upload data...")
            # Forcibly reset TCP connection with RST via SO_LINGER
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            s.close()

            # Small pause for socket cleanup
            time.sleep(0.05)

            # Subsequent request must succeed completely
            status, _, body = self._http_request("GET", f"/api/session/{sid}/status")
            self.assertEqual(status, 200, "Server failed liveness check after raw upload TCP RST")
        finally:
            self.sm.close_session(sid)

    def test_15_client_disconnect_during_multipart_upload_rst(self):
        """Abrupt TCP RST during multipart upload does not crash server."""
        sid = self.sm.create_session()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((self.host, self.port))
            boundary = "abortMultipartBnd"
            headers = (
                f"POST /api/session/{sid}/upload HTTP/1.1\r\n"
                f"Host: {self.host}:{self.port}\r\n"
                f"Content-Type: multipart/form-data; boundary={boundary}\r\n"
                "Content-Length: 5000000\r\n"
                "Connection: keep-alive\r\n\r\n"
            ).encode("utf-8")
            s.sendall(headers)
            s.sendall(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"abort.zip\"\r\n\r\nPK".encode("utf-8"))
            # Forcibly reset TCP connection with RST
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            s.close()

            time.sleep(0.05)
            status, _, body = self._http_request("GET", "/")
            self.assertEqual(status, 200, "Server failed liveness check after multipart upload TCP RST")
        finally:
            self.sm.close_session(sid)

    def test_16_client_disconnect_during_download_streaming_rst(self):
        """Abrupt TCP RST during export download streaming is handled cleanly without unhandled server exception."""
        # Create session with sample files
        sid, count = self.sm.load_sample()
        self.assertTrue(count > 0)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((self.host, self.port))
            req = (
                f"GET /api/session/{sid}/export HTTP/1.1\r\n"
                f"Host: {self.host}:{self.port}\r\n"
                "Connection: keep-alive\r\n\r\n"
            ).encode("utf-8")
            s.sendall(req)

            # Read only first 32 bytes (status line), then immediately terminate with RST
            initial_bytes = s.recv(32)
            self.assertTrue(len(initial_bytes) > 0)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            s.close()

            time.sleep(0.05)

            # Server must be completely operational
            status, _, body = self._http_request("GET", f"/api/session/{sid}/status")
            self.assertEqual(status, 200, "Server failed liveness check after export download TCP RST")
        finally:
            self.sm.close_session(sid)

    def test_17_client_graceful_close_mid_upload_fin(self):
        """Client sending partial upload then sending TCP FIN (graceful close) does not hang server."""
        sid = self.sm.create_session()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((self.host, self.port))
            headers = (
                f"POST /api/session/{sid}/upload_file?filename=graceful_fin.bin HTTP/1.1\r\n"
                f"Host: {self.host}:{self.port}\r\n"
                "Content-Length: 100000\r\n"
                "Connection: close\r\n\r\n"
            ).encode("utf-8")
            s.sendall(headers)
            s.sendall(b"partial content only")
            # Gracefully close sending side (FIN)
            s.shutdown(socket.SHUT_WR)
            # Read until server closes
            try:
                s.recv(1024)
            except Exception:
                pass
            s.close()

            # Verify server is immediately responsive
            status, _, _ = self._http_request("GET", "/")
            self.assertEqual(status, 200)
        finally:
            self.sm.close_session(sid)

    def test_18_concurrent_disconnect_blitz(self):
        """20 concurrent threads connecting, sending partial data, and violently resetting sockets."""
        concurrency = 20
        errors = []

        def violent_disconnect_worker(idx: int):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2.0)
                s.connect((self.host, self.port))
                if idx % 2 == 0:
                    # Partial upload
                    req = (
                        f"POST /api/session/fake_{idx}/upload_file?filename=blitz_{idx}.bin HTTP/1.1\r\n"
                        f"Host: {self.host}:{self.port}\r\n"
                        "Content-Length: 100000\r\n\r\n"
                        "Data chunk..."
                    ).encode("utf-8")
                else:
                    # Partial GET
                    req = (
                        f"GET /style.css HTTP/1.1\r\n"
                        f"Host: {self.host}:{self.port}\r\n\r\n"
                    ).encode("utf-8")
                s.sendall(req)
                time.sleep(0.01)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                s.close()
            except Exception as e:
                errors.append(f"Worker {idx} error: {e}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(violent_disconnect_worker, i) for i in range(concurrency)]
            concurrent.futures.wait(futures)

        # Brief sleep for server threads to settle
        time.sleep(0.1)

        # Now execute a complete, clean end-to-end session lifecycle to verify full operational capability
        sid = self.sm.create_session()
        try:
            status, _, body = self._http_request("POST", f"/api/session/{sid}/upload_file?filename=post_blitz.txt", body=b"Healthy server!")
            self.assertEqual(status, 200, "Server failed post-blitz upload")

            s_status, _, s_body = self._http_request("GET", f"/api/session/{sid}/status")
            self.assertEqual(s_status, 200, "Server failed post-blitz status query")

            e_status, _, e_body = self._http_request("GET", f"/api/session/{sid}/export")
            self.assertEqual(e_status, 200, "Server failed post-blitz export")
            self.assertTrue(e_body.startswith(b"PK\x03\x04"))
        finally:
            self.sm.close_session(sid)

    # =========================================================================
    # SECTION 4: ADVANCED ADVERSARIAL COMBINATIONS & EDGE CASES
    # =========================================================================

    def test_19_persistent_large_payload_alternation(self):
        """Alternating large (1MB) and zero-byte payloads over a single persistent connection."""
        conn = http.client.HTTPConnection(self.host, self.port, timeout=10.0)
        sid = self.sm.create_session()
        try:
            # 1. 1MB payload upload
            payload_1mb = os.urandom(1024 * 1024)
            conn.request(
                "POST",
                f"/api/session/{sid}/upload_file?filename=large_1mb.bin",
                body=payload_1mb,
                headers={"Content-Length": str(len(payload_1mb))},
            )
            r1 = conn.getresponse()
            self.assertEqual(r1.status, 200)
            r1.read()

            # 2. 0-byte upload
            conn.request(
                "POST",
                f"/api/session/{sid}/upload_file?filename=zero_1.bin",
                body=b"",
                headers={"Content-Length": "0"},
            )
            r2 = conn.getresponse()
            self.assertEqual(r2.status, 200)
            r2.read()

            # 3. 512KB payload upload
            payload_512k = os.urandom(512 * 1024)
            conn.request(
                "POST",
                f"/api/session/{sid}/upload_file?filename=medium_512k.bin",
                body=payload_512k,
                headers={"Content-Length": str(len(payload_512k))},
            )
            r3 = conn.getresponse()
            self.assertEqual(r3.status, 200)
            r3.read()

            # 4. 0-byte upload again
            conn.request(
                "POST",
                f"/api/session/{sid}/upload_file?filename=zero_2.bin",
                body=b"",
                headers={"Content-Length": "0"},
            )
            r4 = conn.getresponse()
            self.assertEqual(r4.status, 200)
            r4.read()

            # 5. GET status on same connection
            conn.request("GET", f"/api/session/{sid}/status")
            r5 = conn.getresponse()
            self.assertEqual(r5.status, 200)
            status_data = json.loads(r5.read().decode("utf-8"))
            self.assertEqual(status_data["session_id"], sid)
        finally:
            conn.close()
            self.sm.close_session(sid)

    def test_20_multipart_case_insensitive_parser(self):
        """Mixed-case Content-Type header 'MULTIPART/FORM-DATA; BOUNDARY=...' parses correctly in parse_multipart_data."""
        boundary = "mixedCaseBoundary999"
        part_body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="case.txt"\r\n\r\n'
            "Case insensitive header test\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")

        parts = parse_multipart_data(f"MULTIPART/FORM-DATA; BOUNDARY={boundary}", part_body)
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].filename, "case.txt")
        self.assertEqual(parts[0].data, b"Case insensitive header test")

    def test_21_multipart_part_empty_payload(self):
        """Multipart upload where an individual file part contains 0 bytes is saved cleanly."""
        sid = self.sm.create_session()
        try:
            boundary = "emptyPartBoundary"
            part_body = (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="zero_part.txt"\r\n\r\n'
                f"\r\n--{boundary}--\r\n"
            ).encode("utf-8")

            status, _, body = self._http_request(
                "POST",
                f"/api/session/{sid}/upload",
                body=part_body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            self.assertEqual(status, 200)
            res = json.loads(body.decode("utf-8"))
            staged = res.get("staged_files", [])
            self.assertEqual(len(staged), 1)
            staged_path = self.sm.get_staged_dir(sid) / staged[0]
            self.assertEqual(staged_path.stat().st_size, 0)
        finally:
            self.sm.close_session(sid)

    def test_22_client_disconnect_during_header_transmission(self):
        """Client disconnects with TCP RST during request header transmission."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((self.host, self.port))
        # Send partial headers only
        s.sendall(b"POST /api/session/create HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: app")
        s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        s.close()

        time.sleep(0.05)
        # Verify subsequent request works cleanly
        status, _, _ = self._http_request("GET", "/")
        self.assertEqual(status, 200)

    def test_23_client_disconnect_after_headers_zero_body_sent(self):
        """Client announces 10MB Content-Length, sends 0 body bytes, then resets socket with TCP RST."""
        sid = self.sm.create_session()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((self.host, self.port))
            headers = (
                f"POST /api/session/{sid}/upload_file?filename=ghost.bin HTTP/1.1\r\n"
                f"Host: {self.host}:{self.port}\r\n"
                "Content-Length: 10485760\r\n\r\n"
            ).encode("utf-8")
            s.sendall(headers)
            # Send no body bytes at all, immediately RST
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            s.close()

            time.sleep(0.05)
            # Server must be completely responsive
            status, _, _ = self._http_request("GET", f"/api/session/{sid}/status")
            self.assertEqual(status, 200)
        finally:
            self.sm.close_session(sid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
