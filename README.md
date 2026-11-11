# TOUCHGRIND SKATE 2 // SAVE EDITOR

A standalone, local WebGUI save file editor for **Touchgrind Skate 2** (`se.illusionlabs.skate2`) on iOS. Built with an early iOS skeuomorphic aesthetic, requiring **zero third-party dependencies** (Python 3 standard library only).

---

## Features

- **Zero External Dependencies**: Powered entirely by Python 3.10+ standard library (`http.server`, `sqlite3`, `plistlib`, `zipfile`, `zlib`, `hashlib`, `hmac`). No `pip install` required.
- **Skeuomorphic Interface**: Early iOS tactile design language featuring dark grip tape texture, brushed aluminum bezels, inset wells, `#4cd964` toggle switches, and LED status indicators.
- **Isolated Staging Architecture**: All operations run in temporary sandboxed workspaces (`%TEMP%/tgskate2_editor/session_<uuid>/`). Your original device saves are never mutated on disk.
- **HMAC-SHA256 Signature Recalculation**: Reverse-engineered cryptographic engine computes bit-accurate signatures for `cloudregistry.db.hmc` using the extracted iOS binary key.
- **Complete Challenge Explorer (385 Challenges)**: Reverse-engineered challenge catalog covering all 9 skateparks. Every challenge displays its authentic in-game title, objective description, trick requirements, and duration, paired with a real-time trick search filter.
- **DLC Park Unlocker**: Toggle unlocks for all 8 DLC environments (*The Car Park*, *Dairy Factory*, *The Docks*, *The Motel*, *Playground*, *Mega Ramp*, *Space Dock*, *The Office*).
- **High Scores Editor**: Modify Competition (100s mode) and Jam Session Line high scores across all parks.
- **Custom Equipment & Deck Metrics**: Set board, deck, grip, wheel, and truck indices, deck wear, grip levels, width/length dimensions, and kicktail angle.
- **Cloud Registry & Special Boards**: Manage User ID and UUID synchronization, plus granular toggles for special boards (IDs 2..31) with automatic binary plist synchronization (`iap_special_boards_CKRecord`).
- **Binary Replay Parser & Clipcounter**: Inspect and manage competition and line replay runs (`comp-*`, `line-*`), uncompressing zlib streams, telemetry headers, run durations, scores, and clip counters.
- **Texture Manager**: Validate custom deck graphics (strictly 1024x256 RGBA PNGs) and custom board photos (strictly 1024x1024 JPEGs) with live base64 previews.
- **Raw SQLite Explorer**: Direct paginated SQL browser over typed tables (`stringdata`, `integerdata`, `floatdata`, `binarydata`) with parameterized injection defenses.

---

## Quick Start

### Windows

Double-click `run_save_editor.bat` in the repository root, or run via command prompt:

```cmd
run_save_editor.bat
```

To specify a custom port:
```cmd
run_save_editor.bat 9000
```

### macOS & Linux

Make the script executable and run:

```bash
chmod +x run_save_editor.sh
./run_save_editor.sh
```

Or invoke the Python module directly:

```bash
python3 -m editor.server --port 8765
```

The web server will start and automatically open your default browser to `http://localhost:8765`.

---

## Save File Structure Reference

In iOS app sandboxes (`/var/mobile/Containers/Data/Application/<UUID>/`), *Touchgrind Skate 2* maintains the following hierarchy:

```
iph1/
├── Library/
│   ├── Application Support/
│   │   ├── cloudregistry.db        # Cloud SQLite DB (special boards, UUID, iCloud state)
│   │   └── cloudregistry.db.hmc    # 64-char lowercase HMAC-SHA256 signature
│   ├── Documents/
│   │   ├── registry.db             # Primary SQLite DB (DLC unlocks, challenges, scores, deck)
│   │   ├── board_textures/         # Custom PNG (1024x256) and JPEG (1024x1024) board graphics
│   │   └── <park_name>/            # e.g., thecarpark, backyard, dairyfactory, thedocks
│   │       ├── clipcounter         # 4-byte uint32 clip sequence counter
│   │       ├── recent/             # Replay telemetry files (comp-*, line-*)
│   │       └── top/                # Personal record replay runs
│   └── Preferences/
│       └── se.illusionlabs.skate2.plist
```

---

## How to Transfer Saves to/from iOS

### Extracting Saves from iOS
1. **Jailbreak / TrollStore / Filza**:
   - Navigate to `/var/mobile/Containers/Data/Application/` and locate the `Skate2` directory.
   - Copy or compress the `Library/` and `Documents/` directories into a `.zip` archive.
2. **3uTools / iMazing**:
   - Open App Management -> *Touchgrind Skate 2* -> Document Sharing / Backup.
   - Export the app documents to your computer.

### Editing in the WebGUI
1. Open `http://localhost:8765`.
2. Drag and drop your `.zip` archive (or loose save files) directly onto the upload dropzone. Alternatively, click **Load Reference Sample Save** to explore the bundled sample save.
3. Make your desired modifications across the tabs (Parks, Challenges, Highscores, Equipment, Cloud Data, Replays, Textures).
4. When modifying Cloud Data, click **Recalculate HMAC** to ensure your save passes in-game validation.
5. Click **Export ZIP Archive** to download the clean save archive.

### Restoring to iOS
1. Extract the downloaded ZIP archive.
2. Copy `registry.db`, `cloudregistry.db`, and `cloudregistry.db.hmc` back into their respective folders in the app sandbox.
3. Ensure file ownership permissions are set to `mobile:mobile` (if using Filza).
4. Launch *Touchgrind Skate 2*.

---

## Technical Specifications & Reverse Engineering

### 1. Cryptographic HMAC-SHA256 Checksum (`cloudregistry.db.hmc`)
- **Key**: `ef79557b546e30c7dda351163deb4bd194b9e8c3` (extracted from Mach-O ARM64 executable).
- **Payload**: Base64 encoding of the first whitespace-delimited token in `cloudregistry.db` (`b"SQLite"` -> `b"U1FMaXRl"`).
- **Digest**: 64-character lowercase hex string.

### 2. Challenge Cipher Decompilation
Challenge definition `.dat` files (`gpl_*_challenges.dat`) inside the app bundle are encrypted with a stream permutation cipher located at `0x10037d738` in the ARM64 binary:
```python
def decrypt_challenges_dat(data: bytes) -> bytes:
    buf = bytearray(data)
    w9, w8, w10 = 0xad, 0x17, 0x4c
    for i in range(len(buf)):
        w12 = (w8 + w9) & 0xffffffff
        b = buf[i]
        w13 = (b ^ w10) & 0xff
        buf[i] = (w13 - w9) & 0xff
        w9 = (w12 - 6) & 0xffffffff
        w10 = (w10 + w8) & 0xffffffff
        w8 = (w8 + 1) & 0xffffffff
    return bytes(buf)
```
All 385 extracted definitions are stored in [`editor/challenge_catalog.json`](editor/challenge_catalog.json).

### 3. Binary Replay Layout (`comp-*`, `line-*`)
- **Header**: 4-byte little-endian uint32 storing the uncompressed payload length.
- **Compression**: Standard zlib deflate.
- **Stream**: Magic `b"RPLY\x01\x00"` + `b"RINF"` chunk containing score (`<I`), name string, timestamp (`<d`), duration (`<f`), followed by channel frame blocks.
- **Timestamp Tenths Truncation**: Filename tenths suffix calculated as `int(timestamp * 10)`.

### 4. Special Boards Layout (`iap_special_boards_items`)
- Stored in `cloudregistry.db` table `binarydata` as consecutive 8-byte little-endian signed integers representing unlocked board IDs (2..31).
- Automatically synchronized into `iap_special_boards_CKRecord` binary plist structure.

---

## Automated Test Suite

The repository includes a comprehensive 349-test automated test suite covering all modules, file parsers, cryptographic recalculations, cross-platform path handling, and REST routes.

To run the full test suite:

```bash
python -m unittest discover tests
```

---

## Legal Notice

*Touchgrind Skate 2* and related trademarks, logos, and game assets are the intellectual property of **Illusion Labs AB**.

Apple, iOS, iPhone, iPad, iCloud, and CloudKit are trademarks of **Apple Inc.**, registered in the U.S. and other countries.

This project is an independent, non-commercial open-source research tool created strictly for educational purposes, software interoperability, and personal data backups. This repository and its contributors are **not** affiliated with, sponsored by, authorized by, or in any way officially connected with Illusion Labs AB, Apple Inc., or any of their respective subsidiaries or affiliates.

---

## Disclaimer ("AS IS")

THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT.

IN NO EVENT SHALL THE AUTHORS, CONTRIBUTORS, OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES, LOSS OF DATA, SAVE CORRUPTION, DEVICE MALFUNCTION, ACCOUNT PENALTIES, OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT, OR OTHERWISE, ARISING FROM, OUT OF, OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

Modifying save files carries inherent risk of data corruption or synchronization rejection by game servers. Always maintain an independent, uncompressed backup copy of your original game files before attempting any modification or transfer.

---

## AI Disclaimer

Portions of this codebase, reverse-engineering analysis tools, test suites, and documentation were created, structured, or refactored with the assistance of artificial intelligence and agentic coding models. While the implementation has been subjected to extensive automated testing and verification, users are advised to review the source code independently prior to execution in sensitive environments.

---

## License

This project is licensed under the [MIT License](LICENSE).
