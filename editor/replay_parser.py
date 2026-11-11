"""Touchgrind Skate 2 - Replay Parser & Serializer.

Handles parsing, modifying, and serializing replay files (.replay, comp-*, line-*):
- 4-byte little-endian uncompressed length prefix
- zlib deflation
- Magic: RPLY (4 bytes) + channel_count (2 bytes uint16)
- RINF chunk: 4 bytes tag + 4 bytes length + score (uint32) + name_len (uint8) + name + timestamp (double)
- Duration (float32) and controller channel remainder
- Clipcounter editor: 4-byte unsigned 32-bit integer read/write
"""

from __future__ import annotations

import os
from pathlib import Path
import struct
from typing import Any
import zlib


class ReplayParser:
    """Parser and serializer for Skate 2 replay files."""

    MAX_DECOMPRESSED_SIZE = 10 * 1024 * 1024  # 10 MB safety ceiling

    @classmethod
    def parse(cls, path_or_bytes: str | Path | bytes) -> dict[str, Any]:
        if isinstance(path_or_bytes, (str, Path)):
            p = Path(path_or_bytes)
            if not p.exists():
                raise FileNotFoundError(f"Replay file not found: {p}")
            data = p.read_bytes()
        elif isinstance(path_or_bytes, (bytes, bytearray, memoryview)):
            data = bytes(path_or_bytes)
        else:
            raise TypeError(f"Expected path or bytes, got {type(path_or_bytes)}")

        if len(data) < 4:
            raise ValueError(f"Replay data truncated: {len(data)} bytes < 4")

        decomp_len = struct.unpack("<I", data[:4])[0]
        if decomp_len > cls.MAX_DECOMPRESSED_SIZE:
            raise ValueError(
                f"Decompressed length {decomp_len} exceeds maximum allowed {cls.MAX_DECOMPRESSED_SIZE}"
            )

        try:
            decomp = zlib.decompress(data[4:])
        except Exception as e:
            raise ValueError(f"Corrupted zlib stream in replay: {e}") from e

        if len(decomp) != decomp_len:
            raise ValueError(f"Decompressed length mismatch: expected {decomp_len}, got {len(decomp)}")

        if not decomp.startswith(b"RPLY"):
            raise ValueError("Invalid replay magic: missing 'RPLY'")

        channel_count = struct.unpack("<H", decomp[4:6])[0]

        if decomp[6:10] != b"RINF":
            raise ValueError("Missing or corrupt 'RINF' tag in replay header")

        rinf_len = struct.unpack("<I", decomp[10:14])[0]
        score = struct.unpack("<I", decomp[14:18])[0]
        name_len = decomp[18]
        run_type = decomp[19 : 19 + name_len].decode("utf-8", errors="replace")

        pos = 19 + name_len
        timestamp = struct.unpack("<d", decomp[pos : pos + 8])[0]
        pos += 8

        duration = struct.unpack("<f", decomp[pos : pos + 4])[0]
        pos += 4

        remainder = decomp[pos:]

        return {
            "channel_count": channel_count,
            "reserved": 0,
            "run_type": run_type,
            "score": score,
            "timestamp": timestamp,
            "duration": duration,
            "_remainder": remainder,
        }

    @classmethod
    def serialize(cls, parsed: dict[str, Any]) -> bytes:
        run_type_bytes = str(parsed["run_type"]).encode("utf-8")
        score = int(parsed["score"]) & 0xFFFFFFFF
        timestamp = float(parsed["timestamp"])
        duration = float(parsed.get("duration", 0.0))
        channel_count = int(parsed.get("channel_count", 1)) & 0xFFFF
        remainder = parsed.get("_remainder", b"")

        rinf_payload = (
            struct.pack("<IB", score, len(run_type_bytes))
            + run_type_bytes
            + struct.pack("<d", timestamp)
        )

        decomp = (
            b"RPLY"
            + struct.pack("<H", channel_count)
            + b"RINF"
            + struct.pack("<I", len(rinf_payload))
            + rinf_payload
            + struct.pack("<f", duration)
            + remainder
        )

        return struct.pack("<I", len(decomp)) + zlib.compress(decomp)

    @classmethod
    def build_filename(cls, run_type: str, timestamp: float) -> str:
        rt_lower = run_type.lower()
        if "comp" in rt_lower:
            prefix = "comp"
        elif "line" in rt_lower:
            prefix = "line"
        else:
            prefix = rt_lower[:4]

        tenth_ts = int(timestamp * 10)
        return f"{prefix}-{tenth_ts}"


class ClipcounterEditor:
    """Editor for 4-byte unsigned 32-bit clipcounter files."""

    @classmethod
    def read_counter(cls, path_or_bytes: str | Path | bytes) -> int:
        if isinstance(path_or_bytes, (str, Path)):
            p = Path(path_or_bytes)
            if not p.exists():
                raise FileNotFoundError(f"Clipcounter file not found: {p}")
            data = p.read_bytes()
        elif isinstance(path_or_bytes, (bytes, bytearray, memoryview)):
            data = bytes(path_or_bytes)
        else:
            raise TypeError(f"Expected path or bytes, got {type(path_or_bytes)}")

        if len(data) != 4:
            raise ValueError(f"Clipcounter file size must be exactly 4 bytes, got {len(data)}")

        return struct.unpack("<I", data)[0]

    @classmethod
    def write_counter(cls, count: int) -> bytes:
        if not isinstance(count, int) or isinstance(count, bool):
            raise TypeError(f"Counter must be an integer, got {type(count)}")
        if count < 0 or count > 0xFFFFFFFF:
            raise ValueError(f"Counter out of bounds [0..0xFFFFFFFF]: {count}")

        return struct.pack("<I", count)

    read = read_counter
    write = write_counter
