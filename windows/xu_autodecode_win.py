#!/usr/bin/env python3
"""Automatically map standard UVC controls to vendor XU selectors (Windows).

Instead of changing settings by hand and watching, this drives each standard UVC
control itself (via IAMVideoProcAmp / IAMCameraControl) and records which vendor
extension-unit selectors on units 3 and 4 move in response. The result is an
automatic "standard control -> vendor selector" map.

For every supported standard control it:
  1. reads and remembers the current value and auto/manual mode,
  2. snapshots all readable XU selectors as a baseline,
  3. sets the control to its min and its max (and toggles auto, if supported),
     snapshotting the XU selectors after each change,
  4. restores the original value and mode.

Only standard UVC controls are written — the same knobs any camera app uses. The
vendor extension units are read only; no firmware/flash path is touched.

Requires:  pip install comtypes
Usage:
    py -3 windows\\xu_autodecode_win.py
    py -3 windows\\xu_autodecode_win.py --settle 0.5 --save autodecode.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from ctypes import byref, c_long

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uvcxu_win import WinXU, XUWinError, PROBE_ERRORS  # noqa: E402
from xu_watch_win import UNITS, DEFAULT_EXCLUDE, discover, snapshot, diff  # noqa: E402
from settings_win import (IAMVideoProcAmp, IAMCameraControl,  # noqa: E402
                          VIDEOPROCAMP, CAMERACONTROL, FLAG_AUTO, FLAG_MANUAL)

VID, PID = 0x03F0, 0x794A


class Control:
    def __init__(self, iface, prop, name, mn, mx, step, dflt, caps):
        self.iface, self.prop, self.name = iface, prop, name
        self.min, self.max, self.step, self.default, self.caps = mn, mx, step, dflt, caps

    @property
    def has_auto(self) -> bool:
        return bool(self.caps & FLAG_AUTO)


def enumerate_controls(cam: WinXU):
    """Yield Control for every standard UVC control this camera supports."""
    for iface_cls, table in ((IAMVideoProcAmp, VIDEOPROCAMP),
                             (IAMCameraControl, CAMERACONTROL)):
        iface = cam.query(iface_cls)
        for prop, name in sorted(table.items()):
            mn = c_long(); mx = c_long(); st = c_long(); df = c_long(); cf = c_long()
            try:
                iface.GetRange(prop, byref(mn), byref(mx), byref(st),
                               byref(df), byref(cf))
            except PROBE_ERRORS:
                continue
            yield Control(iface, prop, name, mn.value, mx.value, st.value,
                          df.value, cf.value)


def read_control(ctl: Control):
    val = c_long(); fl = c_long()
    ctl.iface.Get(ctl.prop, byref(val), byref(fl))
    return val.value, fl.value


def set_control(ctl: Control, value: int, flags: int) -> None:
    ctl.iface.Set(ctl.prop, value, flags)


def test_values(ctl: Control):
    """The stimulus values to apply: min, max, and the opposite extreme."""
    vals = []
    if ctl.max != ctl.min:
        vals = [ctl.min, ctl.max]
    return vals


def autodecode(cam: WinXU, layout: dict, settle: float) -> dict:
    report = {}
    for ctl in enumerate_controls(cam):
        try:
            orig_val, orig_flags = read_control(ctl)
        except PROBE_ERRORS:
            continue

        baseline = snapshot(cam, layout)
        observed = {}  # "stimulus" -> [(unit, sel, old, new), ...]

        # sweep manual min/max
        for tv in test_values(ctl):
            try:
                set_control(ctl, tv, FLAG_MANUAL)
            except PROBE_ERRORS as e:
                observed[f"set={tv}"] = [("", "", "", f"<set failed: {e}>")]
                continue
            time.sleep(settle)
            changes = diff(baseline, snapshot(cam, layout))
            if changes:
                observed[f"manual={tv}"] = changes

        # toggle auto on/off, if supported
        if ctl.has_auto:
            try:
                set_control(ctl, orig_val, FLAG_AUTO)
                time.sleep(settle)
                changes = diff(baseline, snapshot(cam, layout))
                if changes:
                    observed["auto=on"] = changes
            except PROBE_ERRORS:
                pass

        # restore
        try:
            set_control(ctl, orig_val, orig_flags or FLAG_MANUAL)
        except PROBE_ERRORS:
            pass

        report[ctl.name] = {
            "range": [ctl.min, ctl.max], "step": ctl.step,
            "default": ctl.default, "orig": [orig_val, orig_flags],
            "observed": {k: [[u, (f"0x{s:02x}" if isinstance(s, int) else s), o, n]
                             for (u, s, o, n) in v]
                         for k, v in observed.items()},
        }
        _print_control_result(ctl, report[ctl.name])
    return report


def _print_control_result(ctl: Control, r: dict) -> None:
    print(f"\n[{ctl.name}]  range {r['range'][0]}..{r['range'][1]} "
          f"default {r['default']}"
          + ("  (auto-capable)" if ctl.has_auto else ""))
    if not r["observed"]:
        print("   no XU selector changed")
        return
    for stim, changes in r["observed"].items():
        sels = ", ".join(f"{u} {s}: {o}->{n}" for (u, s, o, n) in changes)
        print(f"   {stim:12s} -> {sels}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--settle", type=float, default=0.3,
                    help="seconds to wait after each change before reading (default 0.3)")
    ap.add_argument("--save", metavar="FILE", help="write the full report as JSON")
    args = ap.parse_args()

    try:
        with WinXU(VID, PID) as cam:
            print(f"Device path: {cam.device_path}")
            layout = discover(cam, set(DEFAULT_EXCLUDE), set())
            total = sum(len(s) for s in layout.values())
            print("Watching "
                  + ", ".join(f"{u}:{len(s)}" for u, s in layout.items())
                  + f" ({total} XU selectors)\n"
                  "Sweeping standard controls; the camera image will flicker. "
                  "Close other camera apps first.")
            report = autodecode(cam, layout, args.settle)

            # summary: which XU selectors were mapped, which never moved
            mapped = {}
            for name, r in report.items():
                for changes in r["observed"].values():
                    for (u, s, o, n) in changes:
                        if u:
                            mapped.setdefault(f"{u} {s}", set()).add(name)
            print("\n=== summary: XU selector -> controls that moved it ===")
            if mapped:
                for key in sorted(mapped):
                    print(f"  {key}: {', '.join(sorted(mapped[key]))}")
            else:
                print("  none — no standard control touched any watched selector")

            all_sels = {f"{u} 0x{s:02x}" for u, sels in layout.items() for s in sels}
            never = sorted(all_sels - set(mapped))
            print("\n=== selectors not moved by any standard control "
                  "(vendor/firmware-only candidates) ===")
            print("  " + (", ".join(never) if never else "(none)"))

            if args.save:
                json.dump(report, open(args.save, "w"), indent=2)
                print(f"\nsaved report to {args.save}")
    except XUWinError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except PROBE_ERRORS as e:
        print(f"COM error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
