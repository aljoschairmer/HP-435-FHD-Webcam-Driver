#!/usr/bin/env python3
"""Read-only firmware backup for the HP 430/435 FHD Webcam (Linux).

Backs up the camera's flash by reading it 64 bytes at a time through the Sunplus
vendor extension unit (unit 4): SET_CUR on the read-address selector (0x0E) then
GET_CUR on the read-chunk selector (0x16). See docs/sunplus-xu-protocol.md.

What this tool will and will NOT do:
  * It issues GET_* queries plus SET_CUR on selector 0x0E (read address) only.
  * It does NOT enter download mode (0x09), stream a payload (0x0A), finish a
    transfer (0x0C), or write any ASIC register. It cannot modify the flash.
  * It aborts on the first read error instead of pushing the device into an
    unknown state.

This uses undocumented vendor functionality. Reading should be harmless, but
there is no warranty. Make two dumps and compare their hashes before trusting one.

Usage:
    python3 tools/flash_dump.py --out hp435-fw.bin [--size 0x8000] [--device /dev/videoN]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uvcxu import XU, XUError  # noqa: E402
from xu_probe import EXPECTED_PID, EXPECTED_VID, find_camera, sysfs_ids  # noqa: E402

UNIT = 4
SEL_READ_ADDR = 0x0E
SEL_READ_CHUNK = 0x16
CHUNK = 64
DEFAULT_SIZE = 0x8000  # 32 KiB, matches the known Sunplus reference image size


def read_chunk(xu: XU, addr: int) -> bytes:
    xu.set_cur(UNIT, SEL_READ_ADDR, struct.pack("<I", addr))
    return xu.get_cur(UNIT, SEL_READ_CHUNK, CHUNK)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="output .bin path")
    ap.add_argument("--size", type=lambda s: int(s, 0), default=DEFAULT_SIZE,
                    help=f"bytes to read (default {DEFAULT_SIZE:#x})")
    ap.add_argument("--start", type=lambda s: int(s, 0), default=0,
                    help="start address (default 0)")
    ap.add_argument("--device", help="V4L2 node (default: auto-detect 03f0:794a)")
    ap.add_argument("--force", action="store_true",
                    help="continue even if VID/PID does not match 03f0:794a")
    args = ap.parse_args()

    if args.size % CHUNK:
        print(f"--size must be a multiple of {CHUNK}.", file=sys.stderr)
        return 2
    if os.path.exists(args.out):
        print(f"Refusing to overwrite existing {args.out}.", file=sys.stderr)
        return 2

    dev = args.device or find_camera()
    if not dev:
        print("HP 430/435 FHD Webcam (03f0:794a) not found.", file=sys.stderr)
        return 2

    vid, pid, prod = sysfs_ids(os.path.basename(dev))
    print(f"Device: {dev}  {vid:04x}:{pid:04x}  {prod!r}")
    if (vid, pid) != (EXPECTED_VID, EXPECTED_PID) and not args.force:
        print("VID/PID does not match 03f0:794a. Use --force to override.",
              file=sys.stderr)
        return 2

    data = bytearray()
    try:
        with XU(dev) as xu:
            # Sanity check: the read-address selector must accept 4 bytes.
            try:
                rlen = xu.get_len(UNIT, SEL_READ_ADDR)
                clen = xu.get_len(UNIT, SEL_READ_CHUNK)
            except XUError as e:
                print(f"Unit {UNIT} does not expose the read selectors "
                      f"({e}). This firmware may use a different path; run "
                      f"xu_probe.py first.", file=sys.stderr)
                return 1
            if rlen != 4 or clen != CHUNK:
                print(f"Unexpected selector lengths (addr={rlen}, chunk={clen}). "
                      f"Aborting to stay safe.", file=sys.stderr)
                return 1

            total = args.size
            for off in range(0, total, CHUNK):
                addr = args.start + off
                try:
                    chunk = read_chunk(xu, addr)
                except XUError as e:
                    print(f"\nRead failed at 0x{addr:06x}: {e}", file=sys.stderr)
                    print("Aborting. Nothing was written to the device.",
                          file=sys.stderr)
                    if not data:
                        return 1
                    print("Keeping the partial dump collected so far.",
                          file=sys.stderr)
                    break
                data += chunk
                done = off + CHUNK
                if done % (CHUNK * 64) == 0 or done >= total:
                    pct = 100 * done // total
                    print(f"\r  read {done:#08x}/{total:#08x} ({pct:3d}%)",
                          end="", flush=True)
            print()
    except PermissionError:
        print(f"Permission denied opening {dev}. Run as root or join the "
              f"'video' group.", file=sys.stderr)
        return 1

    with open(args.out, "wb") as f:
        f.write(data)
    sha = hashlib.sha256(data).hexdigest()
    print(f"Wrote {len(data)} bytes to {args.out}")
    print(f"sha256: {sha}")
    print("Run again to a second file and compare hashes before trusting the dump.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
