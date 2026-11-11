"""Touchgrind Skate 2 - Synthetic Demo Save Generator.

Generates a minimal, clean, self-contained iOS save sandbox structure:
- Zero personal identifiers, device hardware logs, or telemetry
- Valid SQLite schemas for registry.db and cloudregistry.db
- Bit-accurate HMAC-SHA256 signature for cloudregistry.db.hmc
- Valid board textures (1024x256 RGBA PNGs, 1024x1024 JPEG)
- Complete set of 82 synthetic binary replay files across all 9 skateparks
- Valid Preferences plist
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from pathlib import Path
import plistlib
import sqlite3
import struct
import zlib

HMAC_SECRET = b"ef79557b546e30c7dda351163deb4bd194b9e8c3"

ALL_PARKS = [
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

DLC_PARK_KEYS = [
    "thecarpark",
    "dairyfactory",
    "thedocks",
    "themotel",
    "playground",
    "megaramp",
    "spacedock",
    "theoffice",
]

# Complete list of 82 replay relative paths matching the game structure
SYNTHETIC_REPLAYS = [
    "backyard/recent/comp-17395267498",
    "backyard/recent/line-17942509071",
    "backyard/recent/line-17942509360",
    "backyard/recent/line-17942509520",
    "backyard/top/comp-17395267498",
    "backyard/top/line-17395240151",
    "backyard/top/line-17399907232",
    "backyard/top/line-17399908696",
    "dairyfactory/recent/comp-17395262745",
    "dairyfactory/recent/comp-17395264527",
    "dairyfactory/recent/comp-17400224847",
    "dairyfactory/recent/line-17400227377",
    "dairyfactory/recent/line-17400227570",
    "dairyfactory/recent/line-17400228345",
    "dairyfactory/top/comp-17395262745",
    "dairyfactory/top/comp-17395264527",
    "dairyfactory/top/comp-17400224847",
    "dairyfactory/top/line-17395252580",
    "dairyfactory/top/line-17395255958",
    "dairyfactory/top/line-17400228345",
    "downhill/recent/comp-17411166891",
    "downhill/recent/line-17411163842",
    "downhill/recent/line-17411164016",
    "downhill/recent/line-17411164396",
    "downhill/top/comp-17411166891",
    "downhill/top/line-17411159812",
    "downhill/top/line-17411160676",
    "downhill/top/line-17411163127",
    "funpark/recent/comp-17411133052",
    "funpark/recent/comp-17411138494",
    "funpark/recent/line-17411098652",
    "funpark/recent/line-17411099115",
    "funpark/recent/line-17411099495",
    "funpark/top/comp-17411133052",
    "funpark/top/comp-17411138494",
    "funpark/top/line-17411096656",
    "funpark/top/line-17411097670",
    "funpark/top/line-17411099115",
    "office/recent/line-17411586750",
    "office/recent/line-17411587273",
    "office/recent/line-17411587491",
    "office/top/line-17411583477",
    "office/top/line-17411584388",
    "office/top/line-17411584853",
    "research/recent/comp-17395280887",
    "research/recent/line-17411052948",
    "research/recent/line-17411053080",
    "research/recent/line-17411053372",
    "research/top/comp-17395280887",
    "research/top/line-17401139599",
    "research/top/line-17401143795",
    "research/top/line-17401144645",
    "spacedock/recent/comp-17411151384",
    "spacedock/recent/comp-17411155192",
    "spacedock/recent/line-17411149486",
    "spacedock/recent/line-17411149814",
    "spacedock/recent/line-17411154071",
    "spacedock/top/comp-17411151384",
    "spacedock/top/comp-17411155192",
    "spacedock/top/line-17411141492",
    "spacedock/top/line-17411143666",
    "spacedock/top/line-17411149245",
    "thecarpark/recent/comp-17395269069",
    "thecarpark/recent/comp-17395279700",
    "thecarpark/recent/line-17400280364",
    "thecarpark/recent/line-17400280499",
    "thecarpark/recent/line-17400287393",
    "thecarpark/top/comp-17395269069",
    "thecarpark/top/comp-17395279700",
    "thecarpark/top/line-17395272556",
    "thecarpark/top/line-17395274229",
    "thecarpark/top/line-17400278870",
    "thedocks/recent/comp-17395266277",
    "thedocks/recent/comp-17400186742",
    "thedocks/recent/line-17400183918",
    "thedocks/recent/line-17400184131",
    "thedocks/recent/line-17400184889",
    "thedocks/top/comp-17395266277",
    "thedocks/top/comp-17400186742",
    "thedocks/top/line-17399911401",
    "thedocks/top/line-17399926510",
    "thedocks/top/line-17399930570",
]


def make_png_bytes(width: int, height: int, r: int = 40, g: int = 40, b: int = 40, a: int = 255) -> bytes:
    """Generate valid patterned PNG file bytes."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    ihdr_chunk = struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data))

    rows = []
    for y in range(height):
        row = bytearray(1 + width * 4)
        row[0] = 0  # Filter type 0
        for x in range(width):
            idx = 1 + x * 4
            row[idx] = (x ^ y ^ r) & 0xFF
            row[idx + 1] = ((x * 3) ^ g) & 0xFF
            row[idx + 2] = ((y * 5) ^ b) & 0xFF
            row[idx + 3] = a
        rows.append(bytes(row))
    raw_data = b"".join(rows)
    compressed = zlib.compress(raw_data)
    idat_chunk = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + struct.pack(">I", zlib.crc32(b"IDAT" + compressed))

    iend_chunk = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))
    return sig + ihdr_chunk + idat_chunk + iend_chunk


def make_jpeg_bytes(width: int, height: int) -> bytes:
    """Generate minimal valid JPEG file bytes with SOF0 marker."""
    sof_payload = struct.pack(">BHHB", 8, height, width, 3) + b"\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    sof_len = len(sof_payload) + 2
    sof_chunk = b"\xff\xc0" + struct.pack(">H", sof_len) + sof_payload
    return b"\xff\xd8" + sof_chunk + b"\xff\xd9"


def make_replay_bytes(
    run_type: str = "Competition",
    score: int = 3204021,
    timestamp: float = 1739526749.86538,
    duration: float = 54.72,
) -> bytes:
    """Generate valid compressed binary replay stream matching Skate 2 format."""
    run_type_bytes = run_type.encode("utf-8")
    channel_count = 1
    remainder = b"\x00" * 32

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


def create_synthetic_save(target_dir: Path | str) -> int:
    """Populate target_dir with a clean, fully-functioning synthetic Skate 2 save sandbox.

    Returns the total count of files created.
    """
    root = Path(target_dir)
    file_count = 0

    # 1. Directory Structure
    docs_dir = root / "Library" / "Documents"
    app_support_dir = root / "Library" / "Application Support"
    prefs_dir = root / "Library" / "Preferences"
    board_textures_dir = docs_dir / "board_textures"

    docs_dir.mkdir(parents=True, exist_ok=True)
    app_support_dir.mkdir(parents=True, exist_ok=True)
    prefs_dir.mkdir(parents=True, exist_ok=True)
    board_textures_dir.mkdir(parents=True, exist_ok=True)

    # 2. Library/Documents/registry.db
    reg_db_path = docs_dir / "registry.db"
    if reg_db_path.exists():
        reg_db_path.unlink()

    conn_reg = sqlite3.connect(reg_db_path)
    cur_reg = conn_reg.cursor()
    cur_reg.execute("CREATE TABLE integerdata (key TEXT PRIMARY KEY, value INTEGER)")
    cur_reg.execute("CREATE TABLE stringdata (key TEXT PRIMARY KEY, value TEXT)")
    cur_reg.execute("CREATE TABLE floatdata (key TEXT PRIMARY KEY, value REAL)")
    cur_reg.execute("CREATE TABLE binarydata (key TEXT PRIMARY KEY, value BLOB)")

    int_rows = [
        ("bought_something", 1),
        ("did_check_receipt", 1),
        ("selected_location", 0),
        ("ourgames-badge", 0),
        ("ourgames-revision", 1),
        ("did_update_to_office", 1),
        ("currentBoardIndex", 0),
        ("currentDeckIndex", 20),
        ("currentGriptapeIndex", 16),
        ("currentWheelIndex", 22),
    ]
    for dlc in DLC_PARK_KEYS:
        int_rows.append((f"is_purchased_se.illusionlabs.skate2.{dlc}", 1))

    # Highscores: park 0 uses reference values (comp=3204021, line=4206639), park 1 comp=11017218
    int_rows.append(("db_competition_skatepark0", 3204021))
    int_rows.append(("db_linescore_skatepark0", 4206639))
    int_rows.append(("db_competition_skatepark1", 11017218))
    int_rows.append(("db_linescore_skatepark1", 85000))
    for pid in range(2, 9):
        int_rows.append((f"db_competition_skatepark{pid}", 100000 + pid * 10000))
        int_rows.append((f"db_linescore_skatepark{pid}", 80000 + pid * 5000))

    # Challenges: exactly 233 completed challenges, remainder 0
    all_challenge_keys = []
    # Backyard has 25 challenges
    for ch_num in range(1, 26):
        all_challenge_keys.append(f"challenge_{ch_num}_location_backyard")
    # Remaining 8 parks have 45 challenges each (8 * 45 = 360) -> 385 total
    for park in ALL_PARKS[1:]:
        for ch_num in range(1, 46):
            all_challenge_keys.append(f"challenge_{ch_num}_location_{park}")

    for idx, ch_key in enumerate(all_challenge_keys):
        completed = 1 if idx < 233 else 0
        int_rows.append((ch_key, completed))

    cur_reg.executemany("INSERT INTO integerdata (key, value) VALUES (?, ?)", int_rows)

    float_rows = [
        ("deck_wear_time", 0.0),
        ("db_metrics_played_seconds_deck_0", 120.0),
        ("db_metrics_rail_seconds_deck_0", 25.0),
        ("db_metrics_air_seconds_deck_0", 15.0),
        ("db_metrics_dist_m_deck_0", 500.0),
        ("db_metrics_highest_jump_deck_0", 5.0),
        ("db_metrics_played_seconds_deck_2", 300.0),
    ]
    cur_reg.executemany("INSERT INTO floatdata (key, value) VALUES (?, ?)", float_rows)

    string_rows = [
        ("MultiplayerMatchId", ""),
    ]
    cur_reg.executemany("INSERT INTO stringdata (key, value) VALUES (?, ?)", string_rows)

    conn_reg.commit()
    conn_reg.close()
    file_count += 1

    # 3. Library/Application Support/cloudregistry.db
    cloud_db_path = app_support_dir / "cloudregistry.db"
    if cloud_db_path.exists():
        cloud_db_path.unlink()

    conn_cloud = sqlite3.connect(cloud_db_path)
    cur_cloud = conn_cloud.cursor()
    cur_cloud.execute("CREATE TABLE integerdata (key TEXT PRIMARY KEY, value INTEGER)")
    cur_cloud.execute("CREATE TABLE stringdata (key TEXT PRIMARY KEY, value TEXT)")
    cur_cloud.execute("CREATE TABLE floatdata (key TEXT PRIMARY KEY, value REAL)")
    cur_cloud.execute("CREATE TABLE binarydata (key TEXT PRIMARY KEY, value BLOB)")

    board_ids = list(range(2, 32))
    raw_board_bytes = struct.pack(f"<{len(board_ids)}q", *board_ids)
    b64_special_boards = base64.b64encode(raw_board_bytes).decode("ascii")

    dummy_uuid = "00000000-0000-0000-0000-000000000000"
    dummy_user_id = "_00000000000000000000000000000000"

    uuid_pl = {
        "$version": 100000,
        "$archiver": "NSKeyedArchiver",
        "$top": {"root": plistlib.UID(1)},
        "$objects": [
            "$null",
            {"$class": plistlib.UID(3), "value": plistlib.UID(2)},
            dummy_uuid,
            {"$classes": ["CKRecord", "NSObject"], "$classname": "CKRecord"},
        ],
    }
    b64_uuid_ck = base64.b64encode(plistlib.dumps(uuid_pl, fmt=plistlib.FMT_BINARY)).decode("ascii")

    special_pl = {
        "$version": 100000,
        "$archiver": "NSKeyedArchiver",
        "$top": {"root": plistlib.UID(1)},
        "$objects": ["$null"] + [f"header_{i}" for i in range(25)],
    }
    b64_special_ck = base64.b64encode(plistlib.dumps(special_pl, fmt=plistlib.FMT_BINARY)).decode("ascii")

    cloud_strings = [
        ("CloudStorage_UserID", dummy_user_id),
        ("iap_uuid_value", dummy_uuid),
        ("CloudStorage_zones", '{"iap":"iap"}'),
        ("iap_special_boards_items", b64_special_boards),
        ("iap_uuid_CKRecord", b64_uuid_ck),
        ("iap_special_boards_CKRecord", b64_special_ck),
    ]
    cur_cloud.executemany("INSERT INTO stringdata (key, value) VALUES (?, ?)", cloud_strings)

    cloud_ints = [
        ("iap_saved_to_cloud", 1),
        ("iap_synched", 1),
        ("iap_special_boards_override", 0),
        ("iap_uuid_override", 0),
    ]
    cur_cloud.executemany("INSERT INTO integerdata (key, value) VALUES (?, ?)", cloud_ints)

    conn_cloud.commit()
    conn_cloud.close()
    file_count += 1

    # 4. Library/Application Support/cloudregistry.db.hmc
    db_bytes = cloud_db_path.read_bytes()
    tokens = db_bytes.split()
    token = tokens[0] if tokens else b"SQLite"
    b64_token = base64.b64encode(token)
    hmac_digest = hmac.new(HMAC_SECRET, b64_token, hashlib.sha256).hexdigest().lower()

    hmc_path = app_support_dir / "cloudregistry.db.hmc"
    hmc_path.write_text(hmac_digest, encoding="ascii")
    file_count += 1

    # 5. Library/Preferences/se.illusionlabs.skate2.plist
    pref_data = {
        "privacyPolicyVersion": 1,
        "analytics_enabled": False,
        "adconsent_enabled": False,
    }
    pref_path = prefs_dir / "se.illusionlabs.skate2.plist"
    pref_path.write_bytes(plistlib.dumps(pref_data, fmt=plistlib.FMT_BINARY))
    file_count += 1

    # 6. Library/Documents/board_textures
    png_1024x256 = make_png_bytes(1024, 256, 50, 50, 50, 255)
    jpg_1024x1024 = make_jpeg_bytes(1024, 1024)

    tex_files = [
        ("deck_baked_deck_2.png", png_1024x256),
        ("deck_baked_deck_9.png", png_1024x256),
        ("photo_board_untouched_deck_2.png", png_1024x256),
        ("photo_board_untouched_deck_9.png", png_1024x256),
        ("stickers_baked_deck_2.png", png_1024x256),
        ("stickers_baked_deck_9.png", png_1024x256),
        ("my_current_board_texture.jpg", jpg_1024x1024),
    ]
    for tex_name, tex_bytes in tex_files:
        (board_textures_dir / tex_name).write_bytes(tex_bytes)
        file_count += 1

    # 7. Library/Documents/<park>/clipcounter (initial value = 1)
    clipcounter_bytes = struct.pack("<I", 1)
    for park in ALL_PARKS:
        park_dir = docs_dir / park
        park_dir.mkdir(parents=True, exist_ok=True)
        (park_dir / "clipcounter").write_bytes(clipcounter_bytes)
        file_count += 1

    # 8. Library/Documents/<park> Replays (all 82 replays)
    for rel_replay in SYNTHETIC_REPLAYS:
        parts = rel_replay.split("/")
        park_name, sub_folder, filename = parts[0], parts[1], parts[2]
        target_folder = docs_dir / park_name / sub_folder
        target_folder.mkdir(parents=True, exist_ok=True)

        if "comp" in filename:
            rep_bytes = make_replay_bytes("Competition", 3204021, 1739526749.86538, 54.72)
        else:
            rep_bytes = make_replay_bytes("Line", 4206639, 1739524015.10000, 48.00)

        (target_folder / filename).write_bytes(rep_bytes)
        file_count += 1

    return file_count
