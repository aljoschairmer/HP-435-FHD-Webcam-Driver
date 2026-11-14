#!/usr/bin/env python3
"""Decode the HP 430/435 vendor extension-unit controls by watching them change.

The vendor selectors on units 3 and 4 are undocumented. The practical way to
learn what each one does is to read them all, change one setting elsewhere
(Poly Lens, the Windows Camera app, or windows\\settings_win.py), and see which
selector moved. This tool automates that:

    py -3 windows\\xu_watch_win.py                 # one-shot snapshot table
    py -3 windows\\xu_watch_win.py --monitor       # live: print every change
    py -3 windows\\xu_watch_win.py --save base.json
    py -3 windows\\xu_watch_win.py --diff base.json # compare now vs. a snapshot

Read-only: issues GET_CUR on short selectors only. The write-path selectors
(0x09 Enable, 0x0A Access) and the bulk read selectors (0x0E ReadAddr, 0x16
ReadChunk, 64 bytes of flash window) are skipped so monitoring stays quiet and
safe. Override with --include / --exclude if you want to watch them anyway.

Requires:  pip install comtypes
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uvcxu_win import WinXU, XUWinError, PROBE_ERRORS  # noqa: E402

VID, PID = 0x03F0, 0x794A
UNITS = {
    "unit3": "{D5C2F42C-1808-4D9F-BE56-753E271C9244}",
    "unit4": "{63610682-5070-49AB-B8CC-B3855E8D221D}",
}
DEFAULT_EXCLUDE = {0x09, 0x0A, 0x0E, 0x16}
SEL_RANGE = range(0x01, 0x18)


def discover(cam: WinXU, exclude: set, include: set) -> dict:
    """Return {unit_name: {selector: length}} for readable selectors."""
    layout = {}
    for uname, guid in UNITS.items():
        if not cam.supporting_nodes(guid):
            continue
        sels = {}
        for sel in SEL_RANGE:
            if sel in exclude and sel not in include:
                continue
            size = cam.probe_size(guid, sel)
            if size is not None:
                sels[sel] = size
        layout[uname] = sels
    return layout


def snapshot(cam: WinXU, layout: dict) -> dict:
    """Return {unit_name: {selector: hex-string}} of current values."""
    snap = {}
    for uname, sels in layout.items():
        guid = UNITS[uname]
        vals = {}
        for sel, size in sels.items():
            try:
                vals[sel] = cam.get(guid, sel, size).hex(" ")
            except PROBE_ERRORS as e:
                vals[sel] = f"<error {e}>"
        snap[uname] = vals
    return snap


def print_snapshot(snap: dict) -> None:
    for uname, vals in snap.items():
        print(f"\n=== {uname}  {UNITS[uname]} ===")
        for sel in sorted(vals):
            print(f"  selector 0x{sel:02x} = {vals[sel]}")


def diff(old: dict, new: dict) -> list:
    """Return [(unit, selector, old_val, new_val)] for changed selectors."""
    changes = []
    for uname, vals in new.items():
        oldvals = old.get(uname, {})
        for sel, v in vals.items():
            ov = oldvals.get(sel)
            if ov is not None and ov != v:
                changes.append((uname, sel, ov, v))
    return changes


def _normalize(snap: dict) -> dict:
    # JSON turns int keys into strings; normalize back to int selectors.
    out = {}
    for uname, vals in snap.items():
        out[uname] = {int(k): v for k, v in vals.items()}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--monitor", action="store_true",
                    help="poll continuously and print changes until Ctrl+C")
    ap.add_argument("--interval", type=float, default=0.4,
                    help="monitor poll interval in seconds (default 0.4)")
    ap.add_argument("--save", metavar="FILE", help="write snapshot to JSON")
    ap.add_argument("--diff", metavar="FILE", help="compare now against a saved snapshot")
    ap.add_argument("--include", default="",
                    help="comma-separated extra selectors to watch, e.g. 0x0e,0x16")
    ap.add_argument("--exclude", default="",
                    help="comma-separated selectors to skip (hex or decimal)")
    args = ap.parse_args()

    include = {int(x, 0) for x in args.include.split(",") if x.strip()}
    exclude = set(DEFAULT_EXCLUDE)
    exclude |= {int(x, 0) for x in args.exclude.split(",") if x.strip()}

    try:
        with WinXU(VID, PID) as cam:
            print(f"Device path: {cam.device_path}")
            layout = discover(cam, exclude, include)
            total = sum(len(s) for s in layout.values())
            print("Watching "
                  + ", ".join(f"{u}:{len(s)} sel" for u, s in layout.items())
                  + f"  ({total} selectors)")

            if args.diff:
                base = _normalize(json.load(open(args.diff)))
                now = snapshot(cam, layout)
                changes = diff(base, now)
                if not changes:
                    print("no differences from", args.diff)
                for u, sel, ov, nv in changes:
                    print(f"  {u} 0x{sel:02x}: {ov}  ->  {nv}")
                return 0

            if args.monitor:
                prev = snapshot(cam, layout)
                print_snapshot(prev)
                print("\n--- monitoring; change a setting, Ctrl+C to stop ---")
                try:
                    while True:
                        time.sleep(args.interval)
                        cur = snapshot(cam, layout)
                        for u, sel, ov, nv in diff(prev, cur):
                            ts = time.strftime("%H:%M:%S")
                            print(f"[{ts}] {u} 0x{sel:02x}: {ov}  ->  {nv}")
                        prev = cur
                except KeyboardInterrupt:
                    print("\nstopped.")
                return 0

            snap = snapshot(cam, layout)
            print_snapshot(snap)
            if args.save:
                json.dump(snap, open(args.save, "w"), indent=2)
                print(f"\nsaved snapshot to {args.save}")
    except XUWinError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except PROBE_ERRORS as e:
        print(f"COM error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
