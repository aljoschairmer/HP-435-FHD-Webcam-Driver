#!/usr/bin/env python3
"""Read-only firmware backup for the HP 430/435 FHD Webcam (Windows).

Reads the camera's flash 64 bytes at a time through the Sunplus extension unit
(unit 4): SET on the read-address selector (0x0E), then GET on the read-chunk
selector (0x16). Mirrors tools/flash_dump.py but uses the Windows IKsControl path.

It performs GET requests plus SET on selector 0x0E only. It does NOT enter
download mode (0x09), stream a payload (0x0A), finish a transfer (0x0C), or write
any ASIC register. It cannot modify the flash. Aborts on the first read error.

Requires:  pip install comtypes
Usage:     py -3 windows\\flash_dump_win.py --out hp435-fw.bin [--size 0x8000]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uvcxu_win import WinXU, XUWinError  # noqa: E402

VID, PID = 0x03F0, 0x794A
XU_SUNPLUS = "{63610682-5070-49AB-B8CC-B3855E8D221D}"
SEL_READ_ADDR = 0x0E
SEL_READ_CHUNK = 0x16
CHUNK = 64
DEFAULT_SIZE = 0x8000


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=lambda s: int(s, 0), default=DEFAULT_SIZE)
    ap.add_argument("--start", type=lambda s: int(s, 0), default=0)
    args = ap.parse_args()

    if args.size % CHUNK:
        print(f"--size must be a multiple of {CHUNK}.", file=sys.stderr)
        return 2
    if os.path.exists(args.out):
        print(f"Refusing to overwrite existing {args.out}.", file=sys.stderr)
        return 2

    data = bytearray()
    try:
        with WinXU(VID, PID) as cam:
            print(f"Device path: {cam.device_path}")
            cam.node_for_guid(XU_SUNPLUS)  # raises if the Sunplus XU is absent

            # Sanity: the read selectors should accept 4 and 64 bytes.
            if cam.probe_size(XU_SUNPLUS, SEL_READ_ADDR, (4,)) != 4:
                print("ReadAddr (0x0E) did not accept a 4-byte access; aborting.",
                      file=sys.stderr)
                return 1
            if cam.probe_size(XU_SUNPLUS, SEL_READ_CHUNK, (CHUNK,)) != CHUNK:
                print(f"ReadChunk (0x16) did not accept a {CHUNK}-byte access; "
                      f"aborting. Run xu_probe_win.py first.", file=sys.stderr)
                return 1

            total = args.size
            for off in range(0, total, CHUNK):
                addr = args.start + off
                try:
                    cam.set(XU_SUNPLUS, SEL_READ_ADDR, struct.pack("<I", addr))
                    chunk = cam.get(XU_SUNPLUS, SEL_READ_CHUNK, CHUNK)
                except OSError as e:
                    print(f"\nRead failed at 0x{addr:06x}: {e}", file=sys.stderr)
                    print("Aborting. Nothing was written to the device.",
                          file=sys.stderr)
                    if not data:
                        return 1
                    break
                data += chunk
                done = off + CHUNK
                if done % (CHUNK * 64) == 0 or done >= total:
                    print(f"\r  read {done:#08x}/{total:#08x} "
                          f"({100 * done // total:3d}%)", end="", flush=True)
            print()
    except XUWinError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    with open(args.out, "wb") as f:
        f.write(data)
    print(f"Wrote {len(data)} bytes to {args.out}")
    print(f"sha256: {hashlib.sha256(data).hexdigest()}")
    print("Dump twice and compare hashes before trusting the result.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
