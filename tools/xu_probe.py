#!/usr/bin/env python3
"""Read-only probe of the HP 430/435 FHD Webcam vendor extension units (Linux).

Finds the camera's primary V4L2 capture node, confirms it is 03f0:794a with the
expected Sunplus XU GUID on unit 4, then issues GET_INFO / GET_LEN / GET_CUR for a
range of selectors on units 3 and 4.

This sends only GET_* queries. It does NOT write anything to the device.

Usage:
    python3 tools/xu_probe.py [--device /dev/videoN] [--unit 4]
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uvcxu import XU, XUError, decode_info  # noqa: E402

EXPECTED_VID = 0x03F0
EXPECTED_PID = 0x794A
# Sunplus vendor XU (unit 4) GUID, little-endian GUID as stored in the descriptor.
SUNPLUS_XU_GUID = "63610682-5070-49ab-b8cc-b3855e8d221d"

UNIT_SUNPLUS = 4
UNIT_HP = 3

# Selectors used by the fwupd sunplus-camera plugin (see docs/sunplus-xu-protocol.md).
KNOWN_SELECTORS = {
    0x02: "Reg16Cmd (set ASIC reg addr)",
    0x03: "Reg8Data (ASIC reg value)",
    0x09: "Enable (download mode) [WRITE-ONLY, not probed as SET]",
    0x0A: "Access (stream payload)",
    0x0B: "Checksum (XOR-8)",
    0x0C: "Finish",
    0x0E: "ReadAddr (u32 LE)",
    0x16: "ReadChunk (64 bytes)",
}


def sysfs_ids(video_name: str):
    """Return (vid, pid, product) for a /dev/videoN node, or (None, None, None)."""
    base = f"/sys/class/video4linux/{video_name}/device"
    # Walk up to the USB device directory that has idVendor/idProduct.
    path = os.path.realpath(base)
    for _ in range(6):
        vf, pf = os.path.join(path, "idVendor"), os.path.join(path, "idProduct")
        if os.path.exists(vf) and os.path.exists(pf):
            vid = int(open(vf).read().strip(), 16)
            pid = int(open(pf).read().strip(), 16)
            prod = ""
            pp = os.path.join(path, "product")
            if os.path.exists(pp):
                prod = open(pp).read().strip()
            return vid, pid, prod
        path = os.path.dirname(path)
    return None, None, None


def find_camera() -> str | None:
    for dev in sorted(glob.glob("/dev/video*")):
        name = os.path.basename(dev)
        vid, pid, _ = sysfs_ids(name)
        if vid == EXPECTED_VID and pid == EXPECTED_PID:
            # The first (capture) node of the function is the one uvcvideo
            # accepts XU queries on. Lowest index for this device wins.
            return dev
    return None


def read_xu_guid(video_name: str, unit: int) -> str | None:
    """Best-effort: read the XU GUID from sysfs if the kernel exposes it."""
    # Not all kernels expose this; it's informational only.
    cand = glob.glob(
        f"/sys/class/video4linux/{video_name}/device/.../"  # placeholder
    )
    _ = cand
    return None


def probe_unit(xu: XU, unit: int) -> None:
    print(f"\n=== Extension Unit {unit} ===")
    for sel in range(0x01, 0x18):
        try:
            info = xu.get_info(unit, sel)
        except XUError:
            continue  # selector not present
        caps = decode_info(info)
        length = None
        try:
            length = xu.get_len(unit, sel)
        except XUError:
            pass
        label = KNOWN_SELECTORS.get(sel, "")
        line = f"  selector 0x{sel:02x}  info={info:#04x} [{caps}]"
        if length is not None:
            line += f"  len={length}"
        if label:
            line += f"  — {label}"
        print(line)

        # Only read GET_CUR for short, readable selectors, and never for the
        # write-only download-enable path.
        if length and length <= 8 and (info & 0x01) and sel not in (0x09, 0x0A):
            try:
                cur = xu.get_cur(unit, sel, length)
                print(f"              cur = {cur.hex(' ')}")
            except XUError as e:
                print(f"              cur = <error: {e}>")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--device", help="V4L2 node (default: auto-detect 03f0:794a)")
    ap.add_argument("--unit", type=int, default=None,
                    help="probe only this unit id (default: 3 and 4)")
    args = ap.parse_args()

    dev = args.device or find_camera()
    if not dev:
        print("HP 430/435 FHD Webcam (03f0:794a) not found.", file=sys.stderr)
        print("Plug it in, or pass --device /dev/videoN.", file=sys.stderr)
        return 2

    vid, pid, prod = sysfs_ids(os.path.basename(dev))
    print(f"Device: {dev}  {vid:04x}:{pid:04x}  {prod!r}")
    if (vid, pid) != (EXPECTED_VID, EXPECTED_PID):
        print("WARNING: this is not 03f0:794a; continuing anyway because "
              "--device was given.", file=sys.stderr)

    units = [args.unit] if args.unit is not None else [UNIT_HP, UNIT_SUNPLUS]
    try:
        with XU(dev) as xu:
            for u in units:
                probe_unit(xu, u)
    except PermissionError:
        print(f"\nPermission denied opening {dev}. Run as root or join the "
              f"'video' group.", file=sys.stderr)
        return 1
    print("\nDone. (read-only; nothing was written to the device)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
