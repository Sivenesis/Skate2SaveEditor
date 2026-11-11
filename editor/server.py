"""Touchgrind Skate 2 Save Editor - HTTP Server and REST API Dispatcher.

Strictly Python 3 standard library (zero third-party dependencies).
Compatible with Python 3.12+ (no use of deprecated/removed cgi module).
"""

from __future__ import annotations

import argparse
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
import threading
from typing import Any, TYPE_CHECKING
import urllib.parse

if TYPE_CHECKING:
    from editor.session import SessionManager

MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB upload limit
WEB_DIR = Path(__file__).resolve().parent / "web"


class MultipartPart:
    """Represents a single parsed multipart section."""

    def __init__(
        self,
        name: str,
        filename: str | None,
        content_type: str,
        data: bytes,
    ):
        self.name = name
        self.filename = filename
        self.content_type = content_type
        self.data = data


def parse_multipart_data(content_type_header: str, body_bytes: bytes) -> list[MultipartPart]:
    """Pure Python standard-library multipart/form-data parser.

    Compatible with Python 3.12+ (zero use of deprecated/removed cgi module).
    """
    if not content_type_header or "multipart/form-data" not in content_type_header.lower():
        raise ValueError("Content-Type is not multipart/form-data")

    m = re.search(r"boundary=([^;]+)", content_type_header, re.IGNORECASE)
    if not m:
        raise ValueError("No boundary delimiter specified in Content-Type header")

    boundary = m.group(1).strip()
    if (boundary.startswith('"') and boundary.endswith('"')) or (
        boundary.startswith("'") and boundary.endswith("'")
    ):
        boundary = boundary[1:-1]
    boundary = boundary.strip()

    if not boundary:
        raise ValueError("Invalid or empty multipart boundary")

    try:
        delimiter = b"--" + boundary.encode("latin-1")
    except UnicodeEncodeError as e:
        raise ValueError(f"Invalid non-ASCII/latin-1 multipart boundary: {e}") from e
    parts: list[MultipartPart] = []

    for raw in body_bytes.split(delimiter):
        if not raw or raw.startswith(b"--"):
            continue
        if raw.startswith(b"\r\n"):
            raw = raw[2:]
        elif raw.startswith(b"\n"):
            raw = raw[1:]
        if raw.endswith(b"\r\n"):
            raw = raw[:-2]
        elif raw.endswith(b"\n"):
            raw = raw[:-1]
        if not raw:
            continue

        sep_idx = raw.find(b"\r\n\r\n")
        header_len = 4
        if sep_idx == -1:
            sep_idx = raw.find(b"\n\n")
            header_len = 2
            if sep_idx == -1:
                continue

        header_bytes = raw[:sep_idx]
        data_bytes = raw[sep_idx + header_len:]
        headers_text = header_bytes.decode("latin-1", errors="replace")

        name = ""
        filename = None
        part_content_type = "application/octet-stream"

        for line in headers_text.splitlines():
            if ":" not in line:
                continue
            hk, hv = line.split(":", 1)
            hk = hk.strip().lower()
            hv = hv.strip()
            if hk == "content-disposition":
                m_name = re.search(r'name=["\']?([^"\';]+)["\']?', hv)
                if m_name:
                    name = m_name.group(1)
                m_file = re.search(r'filename=["\']?([^"\';]+)["\']?', hv)
                if m_file:
                    filename = m_file.group(1)
            elif hk == "content-type":
                part_content_type = hv

        parts.append(
            MultipartPart(
                name=name,
                filename=filename,
                content_type=part_content_type,
                data=data_bytes,
            )
        )

    return parts


class Skate2RequestHandler(BaseHTTPRequestHandler):
    """Custom HTTP Request Handler supporting REST API, multipart uploads, and static assets."""

    server_version = "Skate2Editor/1.0"
    protocol_version = "HTTP/1.1"

    _body_bytes: bytes | None = None

    def handle_one_request(self) -> None:
        """Reset per-request state and dispatch single HTTP request."""
        self._body_bytes = None
        super().handle_one_request()

    # Route Table: (HTTP_METHOD, REGEX_PATTERN, HANDLER_METHOD_NAME)
    ROUTES = [
        ("POST", r"^/api/session/create$", "handle_session_create"),
        ("POST", r"^/api/session/load_sample$", "handle_session_load_sample"),
        ("GET", r"^/api/session/(?P<session_id>[^/]+)/status$", "handle_session_status"),
        ("POST", r"^/api/session/(?P<session_id>[^/]+)/upload$", "handle_session_upload"),
        ("POST", r"^/api/session/(?P<session_id>[^/]+)/upload_file$", "handle_session_upload_file"),
        ("GET", r"^/api/session/(?P<session_id>[^/]+)/export$", "handle_session_export"),
        ("DELETE", r"^/api/session/(?P<session_id>[^/]+)$", "handle_session_delete"),
        ("GET", r"^/api/session/(?P<session_id>[^/]+)/registry/parks$", "handle_session_registry_parks_get"),
        ("POST", r"^/api/session/(?P<session_id>[^/]+)/registry/parks$", "handle_session_registry_parks"),
        ("GET", r"^/api/session/(?P<session_id>[^/]+)/registry/challenges?$", "handle_session_challenges_get"),
        ("POST", r"^/api/session/(?P<session_id>[^/]+)/registry/challenges?$", "handle_session_challenge_update"),
        ("GET", r"^/api/session/(?P<session_id>[^/]+)/registry/highscores?$", "handle_session_highscores_get"),
        ("POST", r"^/api/session/(?P<session_id>[^/]+)/registry/highscores?$", "handle_session_highscore_update"),
        ("GET", r"^/api/session/(?P<session_id>[^/]+)/registry/equipment$", "handle_session_equipment_get"),
        ("POST", r"^/api/session/(?P<session_id>[^/]+)/registry/equipment$", "handle_session_equipment_update"),
        ("GET", r"^/api/session/(?P<session_id>[^/]+)/registry/raw$", "handle_session_raw_query"),
        ("POST", r"^/api/session/(?P<session_id>[^/]+)/registry/raw$", "handle_session_raw_execute"),
        ("GET", r"^/api/session/(?P<session_id>[^/]+)/raw_db$", "handle_session_raw_query"),
        ("POST", r"^/api/session/(?P<session_id>[^/]+)/raw_db$", "handle_session_raw_execute"),
        ("GET", r"^/api/session/(?P<session_id>[^/]+)/cloud/data$", "handle_session_cloud_data_get"),
        ("POST", r"^/api/session/(?P<session_id>[^/]+)/cloud/update$", "handle_session_cloud_update"),
        ("POST", r"^/api/session/(?P<session_id>[^/]+)/cloud/boards$", "handle_session_cloud_boards_update"),
        ("POST", r"^/api/session/(?P<session_id>[^/]+)/cloud/user$", "handle_session_cloud_user_update"),
        ("POST", r"^/api/session/(?P<session_id>[^/]+)/cloud/recalculate_hmac$", "handle_session_cloud_recalculate_hmac"),
        ("GET", r"^/api/session/(?P<session_id>[^/]+)/replays$", "handle_session_replays_list"),
        ("GET", r"^/api/session/(?P<session_id>[^/]+)/replays/clipcounter$", "handle_session_clipcounter_get"),
        ("POST", r"^/api/session/(?P<session_id>[^/]+)/replays/clipcounter$", "handle_session_clipcounter_set"),
        ("GET", r"^/api/challenges/catalog$", "handle_challenges_catalog"),
        ("GET", r"^/api/session/(?P<session_id>[^/]+)/textures/preview$", "handle_session_texture_preview"),
        ("GET", r"^/api/session/(?P<session_id>[^/]+)/data$", "handle_session_full_data"),
        ("POST", r"^/api/session/(?P<session_id>[^/]+)/textures/replace$", "handle_session_texture_replace"),
        ("DELETE", r"^/api/session/(?P<session_id>[^/]+)/replays/(?P<park>[^/]+)/(?P<folder>[^/]+)/(?P<filename>[^/]+)$", "handle_session_replay_delete"),
    ]

    session_manager: SessionManager | None = None

    @property
    def sm(self) -> SessionManager:
        """Resolve session manager from server, class, or create default singleton."""
        if hasattr(self.server, "session_manager") and getattr(self.server, "session_manager") is not None:
            return getattr(self.server, "session_manager")
        if self.session_manager is not None:
            return self.session_manager
        if not hasattr(Skate2RequestHandler, "_default_sm"):
            from editor.session import SessionManager
            Skate2RequestHandler._default_sm = SessionManager()
        return Skate2RequestHandler._default_sm

    def _set_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With, X-Filename")

    def do_OPTIONS(self) -> None:
        self._body_bytes = None
        try:
            self.send_response(204)
            self._set_cors_headers()
            self.send_header("Content-Length", "0")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True

    def send_json(self, data: Any, status: int = 200) -> None:
        try:
            self._drain_body()
            body = json.dumps(data, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._set_cors_headers()
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True

    send_json_response = send_json

    def send_binary(
        self,
        data: bytes,
        content_type: str = "application/octet-stream",
        status: int = 200,
        filename: str | None = None,
    ) -> None:
        try:
            self._drain_body()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self._set_cors_headers()
            self.end_headers()
            self.wfile.write(data)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True

    def send_error_json(self, status: int, message: str, details: Any = None) -> None:
        payload: dict[str, Any] = {"status": "error", "code": status, "message": message}
        if details:
            payload["details"] = details
        try:
            self.send_json(payload, status=status)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True

    def read_body(self) -> bytes:
        if getattr(self, "_body_bytes", None) is not None:
            return self._body_bytes

        length_str = self.headers.get("Content-Length", "0")
        try:
            length = int(length_str)
        except ValueError:
            length = 0
        if length > MAX_UPLOAD_SIZE:
            raise ValueError(f"Payload exceeds maximum allowed size ({MAX_UPLOAD_SIZE} bytes)")
        if length > 0:
            self._body_bytes = self.rfile.read(length)
        else:
            self._body_bytes = b""
        return self._body_bytes

    def _drain_body(self) -> None:
        if getattr(self, "_body_bytes", None) is None:
            try:
                self.read_body()
            except Exception:
                self.close_connection = True

    def read_json_body(self) -> dict:
        raw = self.read_body()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"Malformed JSON body: {e}") from e

    def do_GET(self) -> None:
        self._body_bytes = None
        self.dispatch("GET")

    def do_POST(self) -> None:
        self._body_bytes = None
        self.dispatch("POST")

    def do_PUT(self) -> None:
        self._body_bytes = None
        self.dispatch("PUT")

    def do_DELETE(self) -> None:
        self._body_bytes = None
        self.dispatch("DELETE")

    def dispatch(self, method: str) -> None:
        self._body_bytes = None
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        try:
            if path.startswith("/api/"):
                self.dispatch_api(method, path, query)
            else:
                if method not in ("GET", "HEAD"):
                    self.send_error_json(405, f"Method {method} not allowed for static assets")
                    return
                self.handle_static(path)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True
        except KeyError as e:
            self._drain_body()
            try:
                self.send_error_json(404, str(e))
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                self.close_connection = True
        except ValueError as e:
            self._drain_body()
            try:
                self.send_error_json(400, str(e))
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                self.close_connection = True
        except Exception as e:
            self._drain_body()
            try:
                self.send_error_json(500, f"Internal server error: {e}")
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                self.close_connection = True

    def dispatch_api(self, method: str, path: str, query: dict[str, list[str]]) -> None:
        method_matched = False
        for route_method, pattern, handler_name in self.ROUTES:
            match = re.match(pattern, path)
            if match:
                if method != route_method:
                    method_matched = True
                    continue
                handler = getattr(self, handler_name, None)
                if not handler:
                    self.send_error_json(500, f"Handler {handler_name} not implemented")
                    return
                handler(query=query, **match.groupdict())
                return

        if method_matched:
            self.send_error_json(405, f"Method {method} not allowed for {path}")
        else:
            self.send_error_json(404, f"API route not found: {method} {path}")

    # --- M1 Route Handlers ---

    def handle_session_create(self, query: dict, **kwargs) -> None:
        ct = self.headers.get("Content-Type", "")
        if "application/json" in ct:
            self.read_json_body()
        sid = self.sm.create_session()
        self.send_json({"session_id": sid, "status": "created"}, status=200)

    def handle_session_load_sample(self, query: dict, **kwargs) -> None:
        sid, count = self.sm.load_sample()
        self.send_json({"session_id": sid, "files_loaded": count, "status": "sample_loaded"})

    def handle_session_status(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        status_data = self.sm.get_status(session_id)
        self.send_json(status_data)

    def handle_session_upload(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        ct = self.headers.get("Content-Type", "")
        body = self.read_body()
        if not body:
            raise ValueError("Empty upload body")

        staged_files: list[str] = []
        if "multipart/form-data" in ct:
            parts = parse_multipart_data(ct, body)
            for part in parts:
                if part.filename:
                    clean_name = os.path.basename(part.filename)
                    if clean_name.lower().endswith(".zip") or part.data.startswith(b"PK\x03\x04"):
                        staged_files.extend(self.sm.ingest_archive(session_id, part.data))
                    else:
                        staged_files.append(self.sm.ingest_file(session_id, clean_name, part.data))
        elif body.startswith(b"PK\x03\x04") or "application/zip" in ct:
            staged_files.extend(self.sm.ingest_archive(session_id, body))
        else:
            raise ValueError("Expected multipart/form-data or application/zip archive")

        self.send_json({"status": "uploaded", "staged_files": staged_files})

    def handle_session_upload_file(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        fname = query.get("filename", [""])[0] or self.headers.get("X-Filename", "")
        if not fname:
            raise ValueError("Missing 'filename' query parameter or X-Filename header")
        clean_name = os.path.basename(fname)
        body = self.read_body()
        staged_path = self.sm.ingest_file(session_id, clean_name, body)
        self.send_json({"status": "saved", "path": str(staged_path), "filename": clean_name})

    def handle_session_export(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        fmt = query.get("format", ["iph1"])[0]
        iph1_format = fmt.lower() != "root"
        zip_bytes = self.sm.export_zip(session_id, iph1_format=iph1_format)
        self.send_binary(zip_bytes, content_type="application/zip", filename=f"skate2_save_{session_id}.zip")

    def handle_session_delete(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        self.sm.close_session(session_id)
        self.send_json({"status": "deleted", "session_id": session_id})

    # --- Extended REST API Handlers ---

    def handle_session_registry_parks_get(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.registry_editor import RegistryEditor

        reg_path = self.sm.get_registry_path(session_id)
        editor = RegistryEditor(reg_path)
        self.send_json({"status": "ok", "parks": editor.get_parks()})

    def handle_session_registry_parks(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.registry_editor import RegistryEditor, DLC_PARKS_LIST

        reg_path = self.sm.get_registry_path(session_id)
        editor = RegistryEditor(reg_path)
        body = self.read_json_body()
        if body.get("unlock_all"):
            editor.set_parks({p: True for p in DLC_PARKS_LIST})
        elif "parks" in body and isinstance(body["parks"], dict):
            editor.set_parks(body["parks"])
        elif any(k in DLC_PARKS_LIST for k in body.keys()):
            editor.set_parks(body)
        self.send_json({"status": "ok", "parks": editor.get_parks()})

    def handle_session_cloud_recalculate_hmac(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.cloud_editor import CloudEditor

        cloud_path = self.sm.get_cloud_path(session_id)
        hmc_path = self.sm.get_cloud_hmc_path(session_id)
        editor = CloudEditor(cloud_path, hmc_path)
        digest = editor.save_hmc()
        self.send_json({"status": "ok", "hmac": digest})

    def handle_session_replays_list(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.replay_parser import ReplayParser
        from editor.registry_editor import ALL_PARK_NAMES

        parks_dir = self.sm.get_parks_dir(session_id)
        replays: list[dict[str, Any]] = []
        for park in ALL_PARK_NAMES:
            pdir = parks_dir / park
            if not pdir.is_dir():
                continue
            for folder in ("recent", "top"):
                fdir = pdir / folder
                if fdir.is_dir():
                    for item in fdir.iterdir():
                        if item.is_file() and not item.name.startswith("."):
                            try:
                                parsed = ReplayParser.parse(item)
                                replays.append(
                                    {
                                        "park": park,
                                        "folder": folder,
                                        "filename": item.name,
                                        "score": parsed["score"],
                                        "run_type": parsed["run_type"],
                                        "timestamp": parsed["timestamp"],
                                        "duration": parsed["duration"],
                                        "size": item.stat().st_size,
                                    }
                                )
                            except Exception:
                                pass
        self.send_json({"status": "ok", "replays": replays})

    def handle_challenges_catalog(self, query: dict, **kwargs) -> None:
        """Return complete catalog of skatepark challenges with titles, descriptions and requirements."""
        catalog_path = Path(__file__).resolve().parent / "challenge_catalog.json"
        if catalog_path.exists():
            data = json.loads(catalog_path.read_text(encoding="utf-8"))
            self.send_json(data)
        else:
            self.send_json({})

    def handle_session_clipcounter_get(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.replay_parser import ClipcounterEditor

        park = query.get("park", ["backyard"])[0]
        cc_path = self.sm.get_parks_dir(session_id) / park / "clipcounter"
        if not cc_path.exists():
            val = 1
        else:
            val = ClipcounterEditor.read_counter(cc_path)
        self.send_json({"status": "ok", "park": park, "clipcounter": val})

    def handle_session_clipcounter_set(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.replay_parser import ClipcounterEditor

        body = self.read_json_body()
        park = body.get("park", "backyard")
        val = int(body.get("clipcounter", 1))
        cc_path = self.sm.get_parks_dir(session_id) / park / "clipcounter"
        cc_path.parent.mkdir(parents=True, exist_ok=True)
        cc_path.write_bytes(ClipcounterEditor.write_counter(val))
        self.send_json({"status": "ok", "park": park, "clipcounter": val})

    def handle_session_texture_preview(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.texture_manager import TextureManager

        filename = query.get("file", [""])[0]
        if not filename:
            raise ValueError("Missing 'file' query parameter")
        tm = TextureManager(self.sm.get_board_textures_path(session_id))
        data, mime = tm.get_preview(filename)
        self.send_binary(data, content_type=mime)

    def handle_session_full_data(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.registry_editor import RegistryEditor
        from editor.cloud_editor import CloudEditor
        from editor.texture_manager import TextureManager

        reg_path = self.sm.get_registry_path(session_id)
        cloud_path = self.sm.get_cloud_path(session_id)
        hmc_path = self.sm.get_cloud_hmc_path(session_id)

        data: dict[str, Any] = {"status": "ok", "session_id": session_id}
        if reg_path.exists():
            reg = RegistryEditor(reg_path)
            data["parks"] = reg.get_parks()
            data["challenges"] = reg.get_challenges()
            data["highscores"] = reg.get_highscores()
            data["equipment"] = reg.get_equipment()

        if cloud_path.exists():
            cld = CloudEditor(cloud_path, hmc_path)
            data["cloud"] = {
                "user_id": cld.get_user_id(),
                "uuid": cld.get_uuid(),
                "special_boards": cld.get_special_boards(),
                "hmac": cld.compute_hmc(),
                "hmac_valid": cld.verify_hmc(),
            }

        tm = TextureManager(self.sm.get_board_textures_path(session_id))
        data["textures"] = tm.list_textures()

        self.send_json(data)

    def handle_session_challenges_get(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.registry_editor import RegistryEditor

        park = query.get("park", [None])[0]
        reg = RegistryEditor(self.sm.get_registry_path(session_id))
        self.send_json({"status": "ok", "challenges": reg.get_challenges(park=park)})

    def handle_session_challenge_update(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.registry_editor import RegistryEditor, ALL_PARK_NAMES

        reg = RegistryEditor(self.sm.get_registry_path(session_id))
        body = self.read_json_body()
        if body.get("unlock_all"):
            target_park = body.get("park")
            parks_to_unlock = [target_park] if target_park else ALL_PARK_NAMES
            for p in parks_to_unlock:
                if p in ALL_PARK_NAMES:
                    for cid in range(1, 46):
                        reg.set_challenge(p, cid, 1)
        elif "challenges" in body and isinstance(body["challenges"], list):
            for c in body["challenges"]:
                reg.set_challenge(c["park"], int(c["challenge_id"]), int(c["completed"]))
        else:
            reg.set_challenge(body["park"], int(body["challenge_id"]), int(body["completed"]))
        self.send_json({"status": "ok"})

    def handle_session_highscores_get(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.registry_editor import RegistryEditor

        reg = RegistryEditor(self.sm.get_registry_path(session_id))
        self.send_json({"status": "ok", "highscores": reg.get_highscores()})

    def handle_session_highscore_update(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.registry_editor import RegistryEditor

        reg = RegistryEditor(self.sm.get_registry_path(session_id))
        body = self.read_json_body()
        if body.get("max_all"):
            max_score = int(body.get("score", 99999999))
            for pid in range(9):
                reg.set_highscore(pid, competition=max_score, line=max_score)
        elif "highscores" in body and isinstance(body["highscores"], list):
            for sc in body["highscores"]:
                reg.set_highscore(
                    int(sc["park_id"]),
                    competition=sc.get("competition"),
                    line=sc.get("line"),
                )
        elif "park_id" in body:
            reg.set_highscore(
                int(body["park_id"]),
                competition=body.get("competition"),
                line=body.get("line"),
            )
        self.send_json({"status": "ok", "highscores": reg.get_highscores()})

    def handle_session_equipment_get(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.registry_editor import RegistryEditor

        reg = RegistryEditor(self.sm.get_registry_path(session_id))
        self.send_json({"status": "ok", "equipment": reg.get_equipment()})

    def handle_session_equipment_update(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.registry_editor import RegistryEditor

        reg = RegistryEditor(self.sm.get_registry_path(session_id))
        body = self.read_json_body()
        eq_data = body.get("equipment", body)
        reg.set_equipment(eq_data)
        self.send_json({"status": "ok", "equipment": reg.get_equipment()})

    def handle_session_cloud_data_get(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.cloud_editor import CloudEditor

        cld = CloudEditor(self.sm.get_cloud_path(session_id), self.sm.get_cloud_hmc_path(session_id))
        self.send_json(
            {
                "status": "ok",
                "user_id": cld.get_user_id(),
                "uuid": cld.get_uuid(),
                "special_boards": cld.get_special_boards(),
                "hmac": cld.compute_hmc(),
                "hmac_valid": cld.verify_hmc(),
            }
        )

    def handle_session_cloud_update(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.cloud_editor import CloudEditor

        cld = CloudEditor(self.sm.get_cloud_path(session_id), self.sm.get_cloud_hmc_path(session_id))
        body = self.read_json_body()
        if "user_id" in body:
            cld.set_user_id(body["user_id"])
        if "uuid" in body:
            cld.set_uuid(body["uuid"])
        if "special_boards" in body and isinstance(body["special_boards"], list):
            cld.set_special_boards(body["special_boards"])
        elif body.get("unlock_all_boards"):
            cld.set_special_boards(list(range(2, 32)))
        if body.get("recalculate_hmac", True):
            cld.save_hmc()
        self.send_json(
            {
                "status": "ok",
                "user_id": cld.get_user_id(),
                "uuid": cld.get_uuid(),
                "special_boards": cld.get_special_boards(),
                "hmac": cld.compute_hmc(),
                "hmac_valid": cld.verify_hmc(),
            }
        )

    def handle_session_cloud_boards_update(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.cloud_editor import CloudEditor

        cld = CloudEditor(self.sm.get_cloud_path(session_id), self.sm.get_cloud_hmc_path(session_id))
        body = self.read_json_body()
        cld.set_special_boards(body.get("boards", []))
        cld.save_hmc()
        self.send_json({"status": "ok", "special_boards": cld.get_special_boards()})

    def handle_session_cloud_user_update(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.cloud_editor import CloudEditor

        cld = CloudEditor(self.sm.get_cloud_path(session_id), self.sm.get_cloud_hmc_path(session_id))
        body = self.read_json_body()
        if "user_id" in body:
            cld.set_user_id(body["user_id"])
        if "uuid" in body:
            cld.set_uuid(body["uuid"])
        cld.save_hmc()
        self.send_json({"status": "ok", "user_id": cld.get_user_id(), "uuid": cld.get_uuid()})

    def handle_session_raw_query(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.registry_editor import RegistryEditor

        table = query.get("table", ["integerdata"])[0]
        limit = int(query.get("limit", [50])[0])
        offset = int(query.get("offset", [0])[0])
        search = query.get("search", [None])[0]
        reg = RegistryEditor(self.sm.get_registry_path(session_id))
        result = reg.raw_query(table, limit=limit, offset=offset, search=search)
        self.send_json({"status": "ok", **result})

    def handle_session_raw_execute(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.registry_editor import RegistryEditor

        body = self.read_json_body()
        reg = RegistryEditor(self.sm.get_registry_path(session_id))
        reg.raw_execute(body["table"], body["action"], body["key"], body.get("value"))
        self.send_json({"status": "ok"})

    def handle_session_texture_replace(self, session_id: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        from editor.texture_manager import TextureManager

        ct = self.headers.get("Content-Type", "")
        body = self.read_body()
        tm = TextureManager(self.sm.get_board_textures_path(session_id))
        if "multipart/form-data" in ct:
            parts = parse_multipart_data(ct, body)
            if not parts:
                raise ValueError("No multipart section found")
            part = parts[0]
            filename = part.filename or query.get("filename", [""])[0]
            if not filename:
                raise ValueError("Filename not specified")
            clean_name = os.path.basename(filename)
            res = tm.replace_texture(clean_name, part.data)
            self.send_json({"status": "ok", **res})
        else:
            filename = query.get("filename", [""])[0] or self.headers.get("X-Filename", "")
            if not filename:
                raise ValueError("Filename not specified")
            clean_name = os.path.basename(filename)
            res = tm.replace_texture(clean_name, body)
            self.send_json({"status": "ok", **res})

    def handle_session_replay_delete(self, session_id: str, park: str, folder: str, filename: str, query: dict, **kwargs) -> None:
        if not self.sm.has_session(session_id):
            raise KeyError(f"Session not found: {session_id}")
        clean_file = os.path.basename(filename)
        clean_park = os.path.basename(park)
        clean_folder = os.path.basename(folder)
        target = self.sm.get_parks_dir(session_id) / clean_park / clean_folder / clean_file
        if not target.exists():
            raise FileNotFoundError(f"Replay not found: {clean_file}")
        target.unlink()
        self.send_json({"status": "deleted", "filename": clean_file})

    # --- Static File Serving & M4 Fallback ---

    def handle_static(self, path: str) -> None:
        unquoted = urllib.parse.unquote(path)
        clean_rel = unquoted.lstrip("/\\")
        parts = clean_rel.replace("\\", "/").split("/")
        if any(part == ".." for part in parts):
            self.send_error_json(403, "Access forbidden: directory traversal disallowed")
            return

        if clean_rel in ("", "index.html"):
            index_path = WEB_DIR / "index.html"
            if index_path.is_file():
                self.send_binary(index_path.read_bytes(), content_type="text/html; charset=utf-8")
            else:
                self.send_binary(self._render_fallback_html(), content_type="text/html; charset=utf-8")
            return

        if clean_rel == "style.css":
            css_path = WEB_DIR / "style.css"
            if css_path.is_file():
                self.send_binary(css_path.read_bytes(), content_type="text/css; charset=utf-8")
            else:
                self.send_binary(self._render_fallback_css(), content_type="text/css; charset=utf-8")
            return

        if clean_rel == "app.js":
            js_path = WEB_DIR / "app.js"
            if js_path.is_file():
                self.send_binary(js_path.read_bytes(), content_type="application/javascript; charset=utf-8")
            else:
                self.send_binary(self._render_fallback_js(), content_type="application/javascript; charset=utf-8")
            return

        # Serve static asset from WEB_DIR
        target = (WEB_DIR / clean_rel).resolve()
        try:
            target.relative_to(WEB_DIR.resolve())
        except ValueError:
            self.send_error_json(403, "Access forbidden: directory traversal disallowed")
            return

        if not target.is_file():
            self.send_error_json(404, f"Static asset not found: {path}")
            return

        mime_type, _ = mimetypes.guess_type(str(target))
        self.send_binary(target.read_bytes(), content_type=mime_type or "application/octet-stream")

    def _render_fallback_html(self) -> bytes:
        return (
            "<!DOCTYPE html>\n"
            '<html lang="en">\n'
            "<head>\n"
            '  <meta charset="UTF-8">\n'
            '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            "  <title>TOUCHGRIND SKATE 2 // SAVE EDITOR</title>\n"
            '  <link rel="stylesheet" href="/style.css">\n'
            "</head>\n"
            "<body>\n"
            '  <div class="container">\n'
            "    <header><h1>TOUCHGRIND SKATE 2 // SAVE EDITOR</h1></header>\n"
            "    <main>\n"
            '      <p class="status-badge">Backend Server Online (Port 8765)</p>\n'
            "      <p>Milestone 1 REST API active. Web UI frontend loading.</p>\n"
            "    </main>\n"
            "  </div>\n"
            '  <script src="/app.js"></script>\n'
            "</body>\n"
            "</html>\n"
        ).encode("utf-8")

    def _render_fallback_css(self) -> bytes:
        return (
            "body { background: #161618; color: #ececee; font-family: -apple-system, sans-serif; margin: 0; padding: 2rem; }\n"
            "header h1 { font-size: 1.25rem; letter-spacing: 0.1em; color: #fff; border-bottom: 2px solid #333; padding-bottom: 0.5rem; }\n"
            ".status-badge { display: inline-block; background: #234b28; color: #5ee670; padding: 4px 10px; border-radius: 4px; font-weight: bold; }\n"
        ).encode("utf-8")

    def _render_fallback_js(self) -> bytes:
        return "console.log('TOUCHGRIND SKATE 2 // SAVE EDITOR backend connected.');\n".encode("utf-8")

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(f"[{self.log_date_time_string()}] {format % args}\n")
        sys.stderr.flush()


# Alias for backward compatibility if needed
EditorRequestHandler = Skate2RequestHandler


class Skate2ThreadingServer(ThreadingHTTPServer):
    """Multi-threaded HTTP server with reuse address and daemon worker threads."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address,
        RequestHandlerClass,
        session_manager: SessionManager | None = None,
    ):
        super().__init__(server_address, RequestHandlerClass)
        self.session_manager = session_manager


class Server(Skate2ThreadingServer):
    """Server wrapper class supporting Server(host=..., port=...)."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        session_manager: SessionManager | None = None,
    ):
        if session_manager is None:
            from editor.session import SessionManager
            session_manager = SessionManager()
        super().__init__((host, port), Skate2RequestHandler, session_manager=session_manager)


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    session_manager: SessionManager | None = None,
) -> Skate2ThreadingServer:
    """Factory creating configured server instance."""
    if session_manager is None:
        from editor.session import SessionManager
        session_manager = SessionManager()
    return Skate2ThreadingServer((host, port), Skate2RequestHandler, session_manager=session_manager)


def run_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    sample_dir: str | None = None,
) -> None:
    """Main server runner function."""
    from editor.session import SessionManager

    sm = SessionManager(sample_dir=sample_dir)
    server = create_server(host=host, port=port, session_manager=sm)

    print("====================================================")
    print("TOUCHGRIND SKATE 2 // SAVE EDITOR")
    print(f"Backend Server running at http://{host}:{port}/")
    print("====================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Touchgrind Skate 2 Save Editor Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    parser.add_argument("--sample-dir", default=None, help="Reference sample save directory")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, sample_dir=args.sample_dir)


if __name__ == "__main__":
    main()
