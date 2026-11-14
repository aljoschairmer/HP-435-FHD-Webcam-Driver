#!/usr/bin/env python3
"""EXPERIMENTAL: read the SPCA2281D ASIC register/memory space (Windows).

The Sunplus extension unit (unit 4) exposes a register window:
  * selector 0x02 (Reg16Cmd) sets a 16-bit address  (SET_CUR, 2 bytes LE)
  * selector 0x03 (Reg8Data) reads the byte there    (GET_CUR, 1 byte)

This is the same read path fwupd uses for ASIC registers. The goal here is to
look for the *running* / descrambled firmware in the chip's internal memory,
which the static flash dump does not contain. Whether code RAM is reachable
through this window at all is unknown — this is a probe, not a guarantee.

SAFETY
  * Reads only. Selector 0x02 only latches an address (harmless); selector 0x03
    is read with GET_CUR. The write/update selectors (0x03 SET, 0x09, 0x0A,
    0x0C) are never touched, so the flash is not modified.
  * BUT some hardware registers have read side-effects (clear-on-read status,
    FIFO pops). Reading a region blindly can therefore disturb the camera's
    running state until it is re-plugged. Nothing is written to flash, so this
    is recoverable by unplugging, but do not run it while the camera is in use.
  * You must give an explicit --range. There is no "read everything" default.

Requires:  pip install comtypes
Usage:
    py -3 windows\\asic_read_win.py --range 0x2000 0x2100          # peek, to stdout
    py -3 windows\\asic_read_win.py --range 0x0000 0x2000 --out m.bin
    py -3 windows\\asic_read_win.py --survey                       # sparse map (opt-in)
"""

from __future__ import annotations

import argparse
import math
import os
import struct
import sys
import collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uvcxu_win import WinXU, XUWinError, PROBE_ERRORS  # noqa: E402

VID, PID = 0x03F0, 0x794A
XU = "{63610682-5070-49AB-B8CC-B3855E8D221D}"
SEL_ADDR = 0x02   # Reg16Cmd: set 16-bit address (SET_CUR, 2 bytes LE)
SEL_DATA = 0x03   # Reg8Data: read 8-bit value (GET_CUR, 1 byte)


def read_byte(cam: WinXU, addr: int) -> int:
    cam.set(XU, SEL_ADDR, struct.pack("<H", addr & 0xFFFF))
    return cam.get(XU, SEL_DATA, 1)[0]


def read_range(cam: WinXU, start: int, end: int) -> bytes:
    out = bytearray()
    total = end - start
    for off, addr in enumerate(range(start, end)):
        out.append(read_byte(cam, addr))
        if off % 256 == 0 or off == total - 1:
            print(f"\r  0x{addr:04x}  {100*(off+1)//total:3d}%", end="", flush=True)
    print()
    return bytes(out)


def entropy(b: bytes) -> float:
    if not b:
        return 0.0
    c = collections.Counter(b)
    n = len(b)
    return -sum(v / n * math.log2(v / n) for v in c.values())


def looks_like_code(b: bytes) -> str:
    """Rough 8051 code-likeness note for a block."""
    if not b:
        return ""
    ljmp = b.count(0x02) + b.count(0x12)        # LJMP / LCALL
    movdp = b.count(0x90)                        # MOV DPTR,#imm16
    movx = b.count(0xE0) + b.count(0xF0)         # MOVX
    z = 100 * b.count(0) // len(b)
    f = 100 * b.count(0xFF) // len(b)
    tag = []
    if b[:1] == b"\x02":
        tag.append(f"starts LJMP 0x{(b[1] << 8 | b[2]):04x}" if len(b) >= 3 else "starts 02")
    if ljmp + movdp + movx > len(b) // 12:
        tag.append("code-like")
    return (f"H={entropy(b):.2f} 00={z}% ff={f}% ljmp/lcall={ljmp} movdptr={movdp} "
            f"movx={movx}" + ("  " + ", ".join(tag) if tag else ""))


def survey(cam: WinXU) -> None:
    print("Sparse survey: reading 16 bytes at each 0x800 boundary across "
          "0x0000..0xFFFF.\nThis touches many registers; read the safety note. "
          "Ctrl+C to stop.\n")
    for base in range(0x0000, 0x10000, 0x800):
        try:
            b = bytes(read_byte(cam, base + i) for i in range(16))
        except PROBE_ERRORS as e:
            print(f"  0x{base:04x}: <error {e}>")
            continue
        print(f"  0x{base:04x}: {b.hex(' ')}   {looks_like_code(b)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--range", nargs=2, metavar=("START", "END"),
                    help="address window to read, e.g. --range 0x2000 0x2100")
    ap.add_argument("--out", metavar="FILE", help="write the window to a .bin")
    ap.add_argument("--survey", action="store_true",
                    help="opt-in sparse map of the whole 64 KiB space")
    args = ap.parse_args()

    if not args.range and not args.survey:
        ap.error("give --range START END (or --survey). There is no read-all default.")

    try:
        with WinXU(VID, PID) as cam:
            print(f"Device path: {cam.device_path}")
            if not cam.supporting_nodes(XU):
                print("Sunplus extension unit not found.", file=sys.stderr)
                return 1
            # verify the register window is shaped as expected
            if cam.probe_size(XU, SEL_ADDR, (2,)) != 2 or \
               cam.probe_size(XU, SEL_DATA, (1,)) != 1:
                print("ASIC register selectors 0x02/0x03 not shaped as expected; "
                      "aborting.", file=sys.stderr)
                return 1
            orig_addr = cam.get(XU, SEL_ADDR, 2)

            try:
                if args.survey:
                    survey(cam)
                else:
                    start = int(args.range[0], 0)
                    end = int(args.range[1], 0)
                    if not (0 <= start < end <= 0x10000):
                        print("range must be within 0x0000..0x10000.", file=sys.stderr)
                        return 2
                    data = read_range(cam, start, end)
                    print(f"  {looks_like_code(data)}")
                    if args.out:
                        open(args.out, "wb").write(data)
                        print(f"  wrote {len(data)} bytes to {args.out}")
                    else:
                        for o in range(0, len(data), 16):
                            print(f"  {start+o:04x}: {data[o:o+16].hex(' ')}")
            finally:
                # restore the address pointer we disturbed
                try:
                    cam.set(XU, SEL_ADDR, bytes(orig_addr))
                except PROBE_ERRORS:
                    pass
    except XUWinError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except PROBE_ERRORS as e:
        print(f"COM error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
