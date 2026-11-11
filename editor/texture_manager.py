"""Touchgrind Skate 2 - Board Texture Manager.

Manages board textures under Library/Documents/board_textures:
- Lists texture files with dimensions, format, and file size
- Validates PNG dimensions (1024x256 RGBA) and JPEG dimensions (1024x1024)
- Enforces 10MB file size limit and strict format matching
- Safely replaces texture files and serves previews
"""

from __future__ import annotations

import os
from pathlib import Path
import struct
from typing import Any

MAX_TEXTURE_SIZE = 10 * 1024 * 1024  # 10 MB limit


class TextureManager:
    """Manager for skate board deck, sticker, and custom photo textures."""

    def __init__(self, target_path: str | Path):
        p = Path(target_path)
        if p.name == "board_textures":
            self.tex_dir = p
        elif (p / "Library" / "Documents" / "board_textures").exists():
            self.tex_dir = p / "Library" / "Documents" / "board_textures"
        elif (p / "board_textures").exists():
            self.tex_dir = p / "board_textures"
        else:
            self.tex_dir = p / "Library" / "Documents" / "board_textures"

    def ensure_directory(self) -> None:
        self.tex_dir.mkdir(parents=True, exist_ok=True)

    def list_textures(self) -> list[dict[str, Any]]:
        if not self.tex_dir.exists():
            return []

        textures: list[dict[str, Any]] = []
        for f in sorted(self.tex_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg"):
                try:
                    info = self.get_texture_info(f.name)
                    textures.append(info)
                except Exception:
                    pass
        return textures

    def get_texture_info(self, filename: str) -> dict[str, Any]:
        p = self.tex_dir / filename
        if not p.exists():
            raise FileNotFoundError(f"Texture file not found: {p}")
        data = p.read_bytes()
        val = self._parse_image_meta(data)
        val["filename"] = filename
        val["size"] = len(data)
        return val

    def validate_image(self, data: bytes, target_filename: str) -> dict[str, Any]:
        if len(data) == 0:
            raise ValueError("Texture data is empty (0 bytes)")
        if len(data) > MAX_TEXTURE_SIZE:
            raise ValueError(f"Texture file exceeds 10MB limit: {len(data)} bytes")

        target_ext = Path(target_filename).suffix.lower()
        meta = self._parse_image_meta(data)

        # Enforce format matching
        if target_ext == ".png" and meta["format"] != "png":
            raise ValueError(f"Target {target_filename} requires PNG image, got {meta['format']}")
        if target_ext in (".jpg", ".jpeg") and meta["format"] != "jpeg":
            raise ValueError(f"Target {target_filename} requires JPEG image, got {meta['format']}")

        # Enforce required dimensions
        if target_ext in (".jpg", ".jpeg") or target_filename == "my_current_board_texture.jpg":
            if meta["width"] != 1024 or meta["height"] != 1024:
                raise ValueError(
                    f"Board JPEG must be 1024x1024, got {meta['width']}x{meta['height']}"
                )
        elif target_ext == ".png":
            if meta["width"] != 1024 or meta["height"] != 256:
                raise ValueError(
                    f"Deck PNG must be 1024x256, got {meta['width']}x{meta['height']}"
                )

        return meta

    def validate_dimensions(self, filename: str) -> bool:
        p = self.tex_dir / filename
        if not p.exists():
            return False
        try:
            self.validate_image(p.read_bytes(), filename)
            return True
        except ValueError:
            return False

    def replace_texture(self, filename: str, data: bytes) -> dict[str, Any]:
        self.ensure_directory()
        val = self.validate_image(data, filename)
        target = self.tex_dir / filename
        target.write_bytes(data)
        return {"success": True, "filename": filename, **val}

    def get_preview(self, filename: str) -> tuple[bytes, str]:
        p = self.tex_dir / filename
        if not p.exists():
            raise FileNotFoundError(f"Texture file not found: {p}")
        data = p.read_bytes()
        mime = "image/png" if filename.lower().endswith(".png") else "image/jpeg"
        return data, mime

    @classmethod
    def _parse_image_meta(cls, data: bytes) -> dict[str, Any]:
        if len(data) < 8:
            raise ValueError("Image data too small to contain valid header")

        # PNG Check
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            if len(data) < 29:
                raise ValueError("Truncated PNG header")
            ihdr_pos = data.find(b"IHDR")
            if ihdr_pos == -1 or ihdr_pos + 17 > len(data):
                raise ValueError("Corrupted PNG: missing or truncated IHDR chunk")
            w = struct.unpack(">I", data[ihdr_pos + 4 : ihdr_pos + 8])[0]
            h = struct.unpack(">I", data[ihdr_pos + 8 : ihdr_pos + 12])[0]
            bit_depth = data[ihdr_pos + 12]
            color_type = data[ihdr_pos + 13]
            return {
                "format": "png",
                "width": w,
                "height": h,
                "bit_depth": bit_depth,
                "color_type": color_type,
            }

        # JPEG Check
        if data.startswith(b"\xff\xd8"):
            idx = 2
            data_len = len(data)
            while idx < data_len - 1:
                if data[idx] != 0xFF:
                    idx += 1
                    continue
                marker = data[idx + 1]
                idx += 2
                # SOF markers: 0xC0..0xC3, 0xC5..0xC7, 0xC9..0xCB, 0xCD..0xCF
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    if idx + 7 > data_len:
                        raise ValueError("Truncated SOF marker in JPEG")
                    h = struct.unpack(">H", data[idx + 3 : idx + 5])[0]
                    w = struct.unpack(">H", data[idx + 5 : idx + 7])[0]
                    return {
                        "format": "jpeg",
                        "width": w,
                        "height": h,
                    }
                # Other markers with length
                if marker not in (0xD8, 0xD9, 0x00) and idx + 2 <= data_len:
                    seg_len = struct.unpack(">H", data[idx : idx + 2])[0]
                    idx += seg_len
                else:
                    idx += 1

            raise ValueError("Could not find SOF marker in JPEG data")

        raise ValueError("Unsupported or corrupted image header: not PNG or JPEG")
