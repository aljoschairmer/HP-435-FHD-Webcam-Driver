#!/usr/bin/env python3
"""Extract the camera's vendor control traffic from a USBPcap capture.

Reads a Wireshark/USBPcap .pcapng (or .pcap) and prints every USB class control
transfer to the camera's interfaces: UVC extension-unit SET_CUR/GET_CUR (units 3
and 4) and the vendor HID SET_REPORT/GET_REPORT feature reports (the JSON
management channel). Submit and completion packets are paired by IRP id so GET
responses show their returned data.

It shells out to `tshark` (bundled with Wireshark) for packet decoding, so no
extra Python packages are needed.

Usage:
    python3 tools/parse_uvc_capture.py capture.pcapng
    python3 tools/parse_uvc_capture.py capture.pcapng --device 7   # filter device addr
    python3 tools/parse_uvc_capture.py capture.pcapng --tshark "C:\\Program Files\\Wireshark\\tshark.exe"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

# UVC control request codes (bRequest)
UVC_REQ = {0x01: "SET_CUR", 0x81: "GET_CUR", 0x82: "GET_MIN", 0x83: "GET_MAX",
           0x84: "GET_RES", 0x85: "GET_LEN", 0x86: "GET_INFO", 0x87: "GET_DEF"}
# HID control request codes
HID_REQ = {0x01: "GET_REPORT", 0x09: "SET_REPORT", 0x0A: "SET_IDLE",
           0x02: "GET_IDLE", 0x03: "GET_PROTOCOL", 0x0B: "SET_PROTOCOL"}
HID_RTYPE = {1: "Input", 2: "Output", 3: "Feature"}

# VideoControl entity ids for this camera (see descriptors)
ENTITY = {1: "CameraTerminal", 2: "ProcessingUnit", 3: "XU3-HP", 4: "XU4-Sunplus",
          5: "OutputTerminal"}

TSHARK_WIN = [r"C:\Program Files\Wireshark\tshark.exe",
              r"C:\Program Files (x86)\Wireshark\tshark.exe"]

FIELDS = ["usb.irp_id", "frame.number", "frame.time_relative",
          "usb.transfer_type", "usb.bmRequestType", "usb.setup.bRequest",
          "usb.setup.wValue", "usb.setup.wIndex", "usb.setup.wLength",
          "usb.device_address", "usb.endpoint_address.direction",
          "usb.capdata", "usbhid.data", "usb.control.Response"]


def find_tshark(override: str | None) -> str:
    if override:
        return override
    t = shutil.which("tshark")
    if t:
        return t
    for p in TSHARK_WIN:
        if os.path.exists(p):
            return p
    sys.exit("tshark not found. Install Wireshark, or pass --tshark <path>.")


def run_tshark(tshark: str, path: str) -> list[dict]:
    cmd = [tshark, "-r", path, "-T", "fields",
           "-E", "separator=\t", "-E", "occurrence=a"]
    for f in FIELDS:
        cmd += ["-e", f]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"tshark failed:\n{out.stderr.strip()}")
    rows = []
    for line in out.stdout.splitlines():
        cols = line.split("\t")
        cols += [""] * (len(FIELDS) - len(cols))
        rows.append(dict(zip(FIELDS, cols)))
    return rows


def _int(s: str):
    s = (s or "").split(",")[0].strip()
    if not s:
        return None
    try:
        return int(s, 16) if s.lower().startswith("0x") else int(s, 0)
    except ValueError:
        try:
            return int(s)
        except ValueError:
            return None


def _hexbytes(*vals) -> bytes:
    for v in vals:
        v = (v or "").split(",")[0].strip()
        if v:
            h = v.replace(":", "").replace(" ", "")
            try:
                return bytes.fromhex(h)
            except ValueError:
                continue
    return b""


def pair_by_irp(rows: list[dict]) -> list[dict]:
    """Merge submit/complete packets that share an IRP id."""
    merged: dict[str, dict] = {}
    order = []
    for r in rows:
        irp = r.get("usb.irp_id") or f"_{r.get('frame.number')}"
        if irp not in merged:
            merged[irp] = {k: "" for k in FIELDS}
            order.append(irp)
        m = merged[irp]
        for k, v in r.items():
            if v and not m.get(k):
                m[k] = v
        # prefer any non-empty data field
        for df in ("usb.capdata", "usbhid.data", "usb.control.Response"):
            if r.get(df) and not m.get("_data"):
                m["_data"] = r[df]
    return [merged[i] for i in order]


def decode(rows: list[dict], device: int | None):
    print(f"{'frame':>6} {'t(s)':>8}  {'dir':<3} {'kind':<4} "
          f"{'request':<9} target                         data")
    print("-" * 100)
    for r in rows:
        bmr = _int(r.get("usb.bmRequestType"))
        breq = _int(r.get("usb.setup.bRequest"))
        if bmr is None or breq is None:
            continue
        if (bmr >> 5) & 3 != 1:          # class requests only
            continue
        if bmr & 0x1F != 1:              # recipient = interface
            continue
        dev = _int(r.get("usb.device_address"))
        if device is not None and dev != device:
            continue
        wval = _int(r.get("usb.setup.wValue")) or 0
        widx = _int(r.get("usb.setup.wIndex")) or 0
        wlen = _int(r.get("usb.setup.wLength")) or 0
        data = _hexbytes(r.get("_data"), r.get("usb.capdata"),
                         r.get("usbhid.data"), r.get("usb.control.Response"))
        direction = "IN" if (bmr & 0x80) else "OUT"
        frame = r.get("frame.number", "")
        t = r.get("frame.time_relative", "")
        try:
            t = f"{float(t):.3f}"
        except (TypeError, ValueError):
            t = ""

        if breq in UVC_REQ:
            sel = wval >> 8
            ent = widx >> 8
            iface = widx & 0xFF
            tgt = f"{ENTITY.get(ent, f'entity{ent}')} if{iface} sel0x{sel:02x}"
            kind, req = "UVC", UVC_REQ[breq]
        elif breq in HID_REQ:
            rtype = HID_RTYPE.get(wval >> 8, str(wval >> 8))
            rid = wval & 0xFF
            tgt = f"HID if{widx & 0xFF} {rtype} report 0x{rid:02x}"
            kind, req = "HID", HID_REQ[breq]
        else:
            tgt = f"wValue=0x{wval:04x} wIndex=0x{widx:04x}"
            kind, req = "cls", f"0x{breq:02x}"

        datastr = data.hex(" ")
        if len(datastr) > 48:
            datastr = datastr[:48] + " …"
        print(f"{frame:>6} {t:>8}  {direction:<3} {kind:<4} {req:<9} "
              f"{tgt:<30} {datastr}")

        # pretty-print any JSON hiding in the payload
        if data:
            m = re.search(rb"\{.*\}", data, re.S)
            if m:
                try:
                    obj = json.loads(m.group().decode("latin1"))
                    print("           json: " + json.dumps(obj, ensure_ascii=False))
                except Exception:
                    txt = "".join(chr(c) if 32 <= c < 127 else "." for c in data)
                    print(f"           ascii: {txt}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture", help=".pcapng/.pcap from USBPcap")
    ap.add_argument("--device", type=int, help="only this USB device address")
    ap.add_argument("--tshark", help="path to tshark.exe")
    args = ap.parse_args()

    tshark = find_tshark(args.tshark)
    rows = run_tshark(tshark, args.capture)
    merged = pair_by_irp(rows)
    decode(merged, args.device)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
