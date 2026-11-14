#!/usr/bin/env python3
"""Read-only probe of the HP 430/435 FHD Webcam extension units (Windows).

Enumerates the camera's KS topology nodes, then issues GET requests against the
two known extension-unit GUIDs and reports which selectors respond and how long
their data is. Sends only GET requests.

Requires:  pip install comtypes   (Windows, Python 3.8+)
Usage:     py -3 windows\\xu_probe_win.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uvcxu_win import WinXU, XUWinError  # noqa: E402

VID, PID = 0x03F0, 0x794A

XU_HP = "{D5C2F42C-1808-4D9F-BE56-753E271C9244}"      # unit 3, 3 controls
XU_SUNPLUS = "{63610682-5070-49AB-B8CC-B3855E8D221D}"  # unit 4, Sunplus vendor XU

KNOWN = {
    0x02: "Reg16Cmd", 0x03: "Reg8Data", 0x09: "Enable(download)",
    0x0A: "Access", 0x0B: "Checksum", 0x0C: "Finish",
    0x0E: "ReadAddr", 0x16: "ReadChunk",
}


def probe_xu(cam: WinXU, label: str, guid: str) -> None:
    print(f"\n=== {label}  {guid} ===")
    nodes = cam.supporting_nodes(guid)
    if not nodes:
        print(f"  no topology node accepts this extension unit "
              f"(checked 0..{cam.num_nodes - 1})")
        return
    print(f"  responding node id(s): {nodes}")
    node = nodes[0]
    try:
        info = cam.get_info(guid)
        print(f"  EXTENSION_UNIT_INFO: {info.hex(' ')}")
    except OSError as e:
        print(f"  EXTENSION_UNIT_INFO: <error {e}>")

    for sel in range(0x01, 0x18):
        # Never GET the write-only download/stream selectors.
        if sel in (0x09, 0x0A):
            print(f"  selector 0x{sel:02x}  (skipped: write path) "
                  f"— {KNOWN.get(sel, '')}")
            continue
        size = cam.probe_size(guid, sel)
        if size is None:
            continue
        label2 = KNOWN.get(sel, "")
        line = f"  selector 0x{sel:02x}  len={size}"
        if label2:
            line += f"  — {label2}"
        try:
            val = cam.get(guid, sel, size)
            line += f"   cur={val.hex(' ')}"
        except OSError as e:
            line += f"   cur=<error {e}>"
        print(line)


def main() -> int:
    try:
        with WinXU(VID, PID) as cam:
            print(f"Device path: {cam.device_path}")
            print(f"Topology: {cam.num_nodes} nodes")
            for i in range(cam.num_nodes):
                print(f"  node {i}: type {cam.node_type(i)}")
            probe_xu(cam, "Unit 3 (HP)", XU_HP)
            probe_xu(cam, "Unit 4 (Sunplus)", XU_SUNPLUS)
    except XUWinError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print("\nDone. (read-only; nothing was written to the device)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
