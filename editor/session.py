"""Touchgrind Skate 2 Save Editor - Session Management.

Provides isolated temporary staging, ZIP ingestion/normalization,
sample save loading, status reporting, and verified clean ZIP export.
"""

from __future__ import annotations

import base64
import gc
import hashlib
import hmac
import io
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
import zipfile
import zlib


class SessionManager:
    """Manages isolated temporary session staging directories for save editing.

    Under %TEMP%/tgskate2_editor/session_<uuid>/staged/.
    """

    HMAC_KEY = b"ef79557b546e30c7dda351163deb4bd194b9e8c3"
    KNOWN_PARKS = [
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

    def __init__(
        self,
        base_temp_dir: Path | str | None = None,
        sample_dir: Path | str | None = None,
    ):
        if base_temp_dir is None:
            self.base_temp_dir = Path(tempfile.gettempdir()) / "tgskate2_editor"
        else:
            self.base_temp_dir = Path(base_temp_dir)
        self.base_temp_dir.mkdir(parents=True, exist_ok=True)

        if sample_dir is not None:
            self._default_sample_dir = Path(sample_dir)
        else:
            self._default_sample_dir = None

        self._lock = threading.RLock()
        self._sessions: dict[str, dict] = {}
        self._connections: dict[str, list[sqlite3.Connection]] = {}

    def create_session(self) -> str:
        """Create a new isolated session directory with canonical iOS skeleton."""
        session_id = str(uuid.uuid4())
        session_dir = self.base_temp_dir / f"session_{session_id}"
        staged_dir = session_dir / "staged"
        staged_dir.mkdir(parents=True, exist_ok=True)

        # Pre-create canonical directories
        (staged_dir / "Library" / "Documents").mkdir(parents=True, exist_ok=True)
        (staged_dir / "Library" / "Application Support").mkdir(parents=True, exist_ok=True)
        (staged_dir / "Library" / "Preferences").mkdir(parents=True, exist_ok=True)
        (staged_dir / "Documents").mkdir(parents=True, exist_ok=True)

        with self._lock:
            self._sessions[session_id] = {
                "dir": session_dir,
                "staged": staged_dir,
                "created_at": time.time(),
            }
            self._connections[session_id] = []

        return session_id

    def has_session(self, session_id: str) -> bool:
        """Check if session is active."""
        with self._lock:
            return session_id in self._sessions

    def list_sessions(self) -> list[str]:
        """Return list of active session IDs."""
        with self._lock:
            return list(self._sessions.keys())

    def get_session_dir(self, session_id: str) -> Path:
        """Get root directory for a session."""
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Session not found: {session_id}")
            return self._sessions[session_id]["dir"]

    def get_staged_dir(self, session_id: str) -> Path:
        """Get staged iOS sandbox directory for a session."""
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Session not found: {session_id}")
            return self._sessions[session_id]["staged"]

    def get_registry_path(self, session_id: str) -> Path:
        """Return canonical path to registry.db in staged session."""
        return self.get_staged_dir(session_id) / "Library" / "Documents" / "registry.db"

    def get_cloud_path(self, session_id: str) -> Path:
        """Return canonical path to cloudregistry.db in staged session."""
        return self.get_staged_dir(session_id) / "Library" / "Application Support" / "cloudregistry.db"

    def get_cloud_hmc_path(self, session_id: str) -> Path:
        """Return canonical path to cloudregistry.db.hmc in staged session."""
        return self.get_staged_dir(session_id) / "Library" / "Application Support" / "cloudregistry.db.hmc"

    def get_board_textures_path(self, session_id: str) -> Path:
        """Return canonical path to board_textures directory in staged session."""
        return self.get_staged_dir(session_id) / "Library" / "Documents" / "board_textures"

    def get_parks_dir(self, session_id: str) -> Path:
        """Return canonical path to Library/Documents where parks reside."""
        return self.get_staged_dir(session_id) / "Library" / "Documents"

    def register_connection(self, session_id: str, conn: sqlite3.Connection) -> None:
        """Register open SQLite connection for safe flush and closing on cleanup."""
        with self._lock:
            if session_id in self._connections:
                self._connections[session_id].append(conn)

    def unregister_connection(self, session_id: str, conn: sqlite3.Connection) -> None:
        """Unregister closed connection."""
        with self._lock:
            if session_id in self._connections and conn in self._connections[session_id]:
                self._connections[session_id].remove(conn)

    def _resolve_sample_dir(self, sample_dir: Path | str | None = None) -> Path | None:
        """Resolve sample reference save directory, or None if not found on disk."""
        if sample_dir is not None:
            p = Path(sample_dir)
            if p.exists() and p.is_dir():
                return p
            return None

        if self._default_sample_dir is not None and self._default_sample_dir.exists():
            return self._default_sample_dir

        potential = [
            Path("saves") / "iph1",
            Path(__file__).resolve().parent.parent / "saves" / "iph1",
        ]
        for p in potential:
            if p.exists() and p.is_dir():
                return p

        return None

    def load_sample(self, sample_dir: Path | str | None = None) -> tuple[str, int]:
        """Load reference save files or generate clean synthetic demo save into a new session.

        Returns (session_id, files_loaded_count).
        """
        if sample_dir is not None:
            p = Path(sample_dir)
            if not p.exists():
                raise FileNotFoundError(f"Reference sample save directory not found: {p}")
            sample_path: Path | None = p
        else:
            sample_path = self._resolve_sample_dir()

        session_id = self.create_session()
        staged = self.get_staged_dir(session_id)

        if sample_path is not None and sample_path.exists():
            count = 0
            for root, _, files in os.walk(sample_path):
                rel_dir = Path(root).relative_to(sample_path)
                target_dir = staged / rel_dir
                target_dir.mkdir(parents=True, exist_ok=True)
                for f in files:
                    shutil.copy2(Path(root) / f, target_dir / f)
                    count += 1
            return session_id, count

        # Fallback to generating a self-contained synthetic demo save
        from editor.demo_save import create_synthetic_save
        count = create_synthetic_save(staged)
        return session_id, count

    @classmethod
    def _sanitize_path(cls, rel_path: str) -> str:
        """Sanitize path segments for cross-platform filesystem compatibility (especially Windows)."""
        clean_parts = []
        for part in rel_path.replace("\\", "/").split("/"):
            if not part:
                continue
            # Replace characters forbidden on Windows filesystems: <>:"/\|?*
            clean = "".join("_" if c in '<>:"|?*' else c for c in part).rstrip(". ")
            if clean:
                clean_parts.append(clean)
        return "/".join(clean_parts)

    @classmethod
    def _normalize_relative_path(cls, rel_path: str, common_wrapper: str = "") -> str:
        """Normalize an archive entry path to the canonical iOS sandbox structure."""
        p_raw = rel_path.replace("\\", "/").strip("/")
        raw_parts = [part for part in p_raw.split("/") if part]
        if not raw_parts:
            return ""

        if any(part == ".." for part in raw_parts):
            raise ValueError(f"Path traversal sequence '..' detected: {rel_path}")

        if common_wrapper and p_raw.startswith(common_wrapper + "/"):
            p = p_raw[len(common_wrapper) + 1 :]
        else:
            p = p_raw

        parts = [part for part in p.split("/") if part]
        if not parts:
            return ""

        # Check Layout 2 (Library/ or Documents/ at root)
        if parts[0] in ("Library", "Documents"):
            # Redirect misplaced registry or textures under Documents to Library/Documents
            if p == "Documents/registry.db":
                return "Library/Documents/registry.db"
            if p.startswith("Documents/board_textures/"):
                return cls._sanitize_path("Library/Documents/" + p[len("Documents/") :])
            if len(parts) > 1 and parts[1] in cls.KNOWN_PARKS and parts[0] == "Documents":
                return cls._sanitize_path("Library/Documents/" + p[len("Documents/") :])
            return cls._sanitize_path(p)

        # Layout 3: Loose files or subfolders at zip root
        filename = parts[-1]
        if filename == "registry.db":
            return "Library/Documents/registry.db"
        if filename == "cloudregistry.db":
            return "Library/Application Support/cloudregistry.db"
        if filename == "cloudregistry.db.hmc":
            return "Library/Application Support/cloudregistry.db.hmc"
        if filename.endswith(".plist"):
            return cls._sanitize_path(f"Library/Preferences/{filename}")
        if (
            p.startswith("board_textures/")
            or filename.startswith(("deck_baked_", "stickers_baked_", "photo_board_"))
            or filename == "my_current_board_texture.jpg"
            or (filename.endswith((".png", ".jpg", ".jpeg")) and not parts[0] in cls.KNOWN_PARKS)
        ):
            return cls._sanitize_path(f"Library/Documents/board_textures/{filename}")

        if parts[0] in cls.KNOWN_PARKS:
            return cls._sanitize_path(f"Library/Documents/{p}")

        if filename.startswith(("comp-", "line-")):
            return cls._sanitize_path(f"Library/Documents/thecarpark/recent/{filename}")
        if filename == "clipcounter":
            return "Library/Documents/thecarpark/clipcounter"

        return cls._sanitize_path(f"Library/Documents/{filename}")

    def ingest_archive(self, session_id: str, zip_path_or_bytes: Path | str | bytes) -> list[str]:
        """Ingest a ZIP archive into session staging, normalizing paths.

        Returns list of extracted relative canonical paths.
        """
        staged = self.get_staged_dir(session_id)

        try:
            if isinstance(zip_path_or_bytes, (str, Path)):
                zf = zipfile.ZipFile(zip_path_or_bytes, "r")
            elif isinstance(zip_path_or_bytes, bytes):
                zf = zipfile.ZipFile(io.BytesIO(zip_path_or_bytes), "r")
            else:
                raise TypeError("Expected Path, str, or bytes")
        except zipfile.BadZipFile as e:
            raise ValueError(f"Invalid or corrupted zip archive: {e}") from e

        with zf:
            members = [
                m
                for m in zf.namelist()
                if not m.endswith("/")
                and not m.startswith("__MACOSX")
                and not os.path.basename(m).startswith(".")
            ]
            if not members:
                return []

            # Zip Slip defense check before anything else
            for m in members:
                clean_m = m.replace("\\", "/").strip("/")
                if any(part == ".." for part in clean_m.split("/")):
                    raise ValueError(f"Zip slip security violation: {m}")

            # Detect common container prefix (Layout 1: e.g. iph1/ or Skate2/)
            prefix_candidates = set()
            for m in members:
                m_clean = m.replace("\\", "/").strip("/")
                parts = m_clean.split("/")
                if len(parts) > 1:
                    prefix_candidates.add(parts[0])
                else:
                    prefix_candidates.add("")

            common_wrapper = ""
            if len(prefix_candidates) == 1:
                cand = list(prefix_candidates)[0]
                if cand not in ("Library", "Documents", "..", ".") and cand != "":
                    common_wrapper = cand

            extracted = []
            for member in members:
                norm_rel = self._normalize_relative_path(member, common_wrapper)
                if not norm_rel:
                    continue
                target_path = staged / norm_rel

                # Zip Slip defense: verify target stays within staged directory
                resolved = target_path.resolve()
                if not resolved.is_relative_to(staged.resolve()):
                    raise ValueError(f"Zip slip security violation: {member}")

                try:
                    member_bytes = zf.read(member)
                except (zipfile.BadZipFile, zlib.error, RuntimeError, EOFError) as e:
                    raise ValueError(f"Corrupted zip member {member}: {e}") from e

                try:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_bytes(member_bytes)
                    extracted.append(norm_rel)
                except OSError as os_err:
                    logging.warning("Skipping extraction of non-critical member %s to %s: %s", member, target_path, os_err)

            return extracted

    def ingest_file(self, session_id: str, filename: str, data: bytes) -> str:
        """Ingest a single file into the staged session, normalizing its location.

        Returns normalized relative path string.
        """
        staged = self.get_staged_dir(session_id)
        norm_rel = self._normalize_relative_path(filename)
        if not norm_rel:
            raise ValueError(f"Invalid filename: {filename}")
        target_path = staged / norm_rel

        # Path traversal defense
        resolved = target_path.resolve()
        if not resolved.is_relative_to(staged.resolve()):
            raise ValueError(f"Path traversal security violation: {filename}")

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(data)
        return norm_rel

    def get_status(self, session_id: str) -> dict:
        """Report session manifest status and component counts."""
        staged = self.get_staged_dir(session_id)
        reg_p = staged / "Library" / "Documents" / "registry.db"
        cloud_p = staged / "Library" / "Application Support" / "cloudregistry.db"
        docs_dir = staged / "Library" / "Documents"

        parks_found = []
        replays_count = 0
        if docs_dir.exists():
            for p in self.KNOWN_PARKS:
                p_dir = docs_dir / p
                if p_dir.is_dir():
                    parks_found.append(p)
                    for sub in ["recent", "top", "myclip", "myproj"]:
                        s_dir = p_dir / sub
                        if s_dir.exists():
                            replays_count += len([f for f in s_dir.iterdir() if f.is_file()])

        tex_dir = staged / "Library" / "Documents" / "board_textures"
        textures_count = len([f for f in tex_dir.iterdir() if f.is_file()]) if tex_dir.exists() else 0

        return {
            "session_id": session_id,
            "has_registry": reg_p.exists(),
            "has_cloud": cloud_p.exists(),
            "parks": parks_found,
            "replays_count": replays_count,
            "textures_count": textures_count,
        }

    @classmethod
    def compute_hmc(cls, db_bytes: bytes) -> str:
        """Calculate HMAC-SHA256 for cloudregistry.db.

        std::ifstream >> std::string extracts b'SQLite' prior to first whitespace,
        base64 encodes to b'U1FMaXRl', and calculates HMAC-SHA256.
        """
        token = db_bytes.split()[0] if db_bytes.split() else b"SQLite"
        b64 = base64.b64encode(token)
        return hmac.new(cls.HMAC_KEY, b64, hashlib.sha256).hexdigest()

    def verify_hmc(self, session_id: str) -> bool:
        """Verify cloudregistry.db HMAC matches cloudregistry.db.hmc."""
        cloud_p = self.get_cloud_path(session_id)
        hmc_p = self.get_cloud_hmc_path(session_id)
        if not cloud_p.exists() or not hmc_p.exists():
            return False

        expected = self.compute_hmc(cloud_p.read_bytes())
        stored = hmc_p.read_text(encoding="ascii", errors="replace").strip()
        return stored.lower() == expected.lower()

    def recalculate_hmc(self, session_id: str) -> str:
        """Recalculate HMAC-SHA256 for cloudregistry.db and update cloudregistry.db.hmc."""
        cloud_p = self.get_cloud_path(session_id)
        if not cloud_p.exists():
            raise FileNotFoundError(f"cloudregistry.db not found for session {session_id}")

        digest = self.compute_hmc(cloud_p.read_bytes())
        hmc_p = self.get_cloud_hmc_path(session_id)
        hmc_p.parent.mkdir(parents=True, exist_ok=True)
        hmc_p.write_bytes(digest.encode("ascii"))
        return digest

    def verify_integrity(self, session_id: str) -> dict[str, bool]:
        """Verify SQLite integrity for registry.db and cloudregistry.db."""
        results = {}
        reg_p = self.get_registry_path(session_id)
        if reg_p.exists():
            try:
                conn = sqlite3.connect(str(reg_p))
                try:
                    rows = conn.execute("PRAGMA integrity_check").fetchall()
                    results["registry"] = (rows == [("ok",)])
                finally:
                    conn.close()
            except Exception:
                results["registry"] = False

        cloud_p = self.get_cloud_path(session_id)
        if cloud_p.exists():
            try:
                conn = sqlite3.connect(str(cloud_p))
                try:
                    rows = conn.execute("PRAGMA integrity_check").fetchall()
                    results["cloud"] = (rows == [("ok",)])
                finally:
                    conn.close()
            except Exception:
                results["cloud"] = False

        return results

    def export_zip(
        self,
        session_id: str,
        output_path: Path | str | None = None,
        iph1_format: bool = True,
    ) -> bytes:
        """Export clean, verified ZIP archive with integrity checks and HMAC recalculation."""
        staged = self.get_staged_dir(session_id)

        # 1. Close and flush any registered SQLite connections
        self._flush_and_close_connections(session_id)

        # 2. SQLite PRAGMA integrity_check, WAL checkpoint, and journal_mode=DELETE
        for root, _, files in os.walk(staged):
            for f in files:
                if f.endswith((".db", ".sqlite", ".sqlite3")):
                    db_p = Path(root) / f
                    try:
                        conn = sqlite3.connect(str(db_p))
                        try:
                            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                            conn.execute("PRAGMA journal_mode=DELETE")
                            rows = conn.execute("PRAGMA integrity_check").fetchall()
                            if rows != [("ok",)]:
                                raise ValueError(f"SQLite integrity check failed for {f}: {rows}")
                        finally:
                            conn.close()
                    except sqlite3.DatabaseError as e:
                        raise ValueError(f"SQLite integrity check failed for {f}: {e}") from e

        # 3. Recalculate HMAC for cloudregistry.db if present
        cloud_p = self.get_cloud_path(session_id)
        if cloud_p.exists():
            self.recalculate_hmc(session_id)

        # 4. Create ZIP
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(staged):
                for f in files:
                    if f.endswith(("-wal", "-shm", ".tmp", ".DS_Store", "Thumbs.db")):
                        continue
                    full_p = Path(root) / f
                    rel_p = full_p.relative_to(staged).as_posix()
                    arcname = f"iph1/{rel_p}" if iph1_format else rel_p
                    zf.write(full_p, arcname=arcname)

        zip_bytes = buffer.getvalue()
        if output_path is not None:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(zip_bytes)
        return zip_bytes

    def _flush_and_close_connections(self, session_id: str) -> None:
        """Flush WAL and safely close all SQLite connections for a session."""
        with self._lock:
            if session_id in self._connections:
                for conn in self._connections[session_id]:
                    try:
                        for obj in gc.get_objects():
                            if isinstance(obj, sqlite3.Cursor):
                                try:
                                    if getattr(obj, "connection", None) is conn:
                                        obj.close()
                                except Exception:
                                    pass
                    except Exception:
                        pass

                    try:
                        try:
                            conn.commit()
                        except Exception:
                            pass
                        try:
                            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                        except Exception:
                            pass
                    finally:
                        try:
                            conn.close()
                        except Exception:
                            pass
                self._connections[session_id].clear()
        gc.collect()

    def close_session(self, session_id: str) -> None:
        """Safely clean up and remove session directory on disk."""
        with self._lock:
            if session_id not in self._sessions:
                return
            session_dir = self._sessions[session_id]["dir"]
            del self._sessions[session_id]

        # Flush WAL and close open connections before deleting connection registry
        self._flush_and_close_connections(session_id)

        with self._lock:
            if session_id in self._connections:
                del self._connections[session_id]

        gc.collect()

        # Robust Windows directory deletion with exponential retry backoff
        for attempt in range(5):
            try:
                shutil.rmtree(session_dir)
                break
            except FileNotFoundError:
                break
            except (PermissionError, OSError):
                time.sleep(0.05 * (attempt + 1))
                gc.collect()

    def cleanup_all(self) -> None:
        """Close and remove all active sessions."""
        with self._lock:
            active_ids = list(self._sessions.keys())
        for sid in active_ids:
            self.close_session(sid)
