#!/usr/bin/env python3
"""Show (and optionally set) the HP 430/435 FHD Webcam's standard UVC controls.

Reads the camera's standard UVC controls through the DirectShow interfaces the
in-box driver exposes: IAMVideoProcAmp (brightness, contrast, white balance, ...)
and IAMCameraControl (exposure, focus, ...). For each control it prints the
current value, whether it is in auto or manual mode, and its min/max/step/default.

This does not touch the firmware flash or the vendor extension units. The
standard UVC controls are the same knobs any camera app (Teams, the Camera app,
Poly Lens) changes; writing them with --set is safe and non-persistent across
re-plugging in the usual case.

Requires:  pip install comtypes
Usage:
    py -3 windows\\settings_win.py                 # list all controls
    py -3 windows\\settings_win.py --set brightness 140
    py -3 windows\\settings_win.py --set focus auto
"""

from __future__ import annotations

import argparse
import os
import sys
from ctypes import POINTER, byref, c_long

from comtypes import GUID, COMMETHOD, HRESULT, IUnknown

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uvcxu_win import WinXU, XUWinError, PROBE_ERRORS  # noqa: E402

VID, PID = 0x03F0, 0x794A

# KSPROPERTY_*_FLAGS_AUTO / _MANUAL (shared by both control interfaces)
FLAG_AUTO = 0x0001
FLAG_MANUAL = 0x0002


class IAMVideoProcAmp(IUnknown):
    _iid_ = GUID("{C6E13360-30AC-11D0-A18C-00A0C9118956}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetRange",
                  (["in"], c_long, "Property"),
                  (["in"], POINTER(c_long), "pMin"),
                  (["in"], POINTER(c_long), "pMax"),
                  (["in"], POINTER(c_long), "pSteppingDelta"),
                  (["in"], POINTER(c_long), "pDefault"),
                  (["in"], POINTER(c_long), "pCapsFlags")),
        COMMETHOD([], HRESULT, "Set",
                  (["in"], c_long, "Property"),
                  (["in"], c_long, "lValue"),
                  (["in"], c_long, "Flags")),
        COMMETHOD([], HRESULT, "Get",
                  (["in"], c_long, "Property"),
                  (["in"], POINTER(c_long), "lValue"),
                  (["in"], POINTER(c_long), "Flags")),
    ]


class IAMCameraControl(IUnknown):
    _iid_ = GUID("{C6E13370-30AC-11D0-A18C-00A0C9118956}")
    _methods_ = IAMVideoProcAmp._methods_  # identical vtable shape


# property index -> name, per interface
VIDEOPROCAMP = {
    0: "brightness", 1: "contrast", 2: "hue", 3: "saturation",
    4: "sharpness", 5: "gamma", 6: "color_enable", 7: "white_balance",
    8: "backlight_compensation", 9: "gain", 10: "digital_multiplier",
    11: "digital_multiplier_limit", 12: "white_balance_component",
    13: "powerline_frequency",
}
CAMERACONTROL = {
    0: "pan", 1: "tilt", 2: "roll", 3: "zoom", 4: "exposure",
    5: "iris", 6: "focus",
}


def _flags_str(flags: int) -> str:
    parts = []
    if flags & FLAG_AUTO:
        parts.append("auto")
    if flags & FLAG_MANUAL:
        parts.append("manual")
    return "/".join(parts) if parts else f"0x{flags:x}"


def list_controls(label: str, iface, props: dict) -> None:
    print(f"\n=== {label} ===")
    any_found = False
    for prop, name in sorted(props.items()):
        mn = c_long(); mx = c_long(); step = c_long(); dflt = c_long(); caps = c_long()
        try:
            iface.GetRange(prop, byref(mn), byref(mx), byref(step),
                           byref(dflt), byref(caps))
        except PROBE_ERRORS:
            continue  # control not supported by this camera
        any_found = True
        val = c_long(); fl = c_long()
        try:
            iface.Get(prop, byref(val), byref(fl))
            cur = f"{val.value}"
            mode = _flags_str(fl.value)
        except PROBE_ERRORS as e:
            cur, mode = "<error>", str(e)
        auto = "auto" if caps.value & FLAG_AUTO else "manual-only"
        print(f"  {name:24s} = {cur:>7}  [{mode}]   "
              f"range {mn.value}..{mx.value} step {step.value} "
              f"default {dflt.value} ({auto})")
    if not any_found:
        print("  (none supported)")


def find_control(name: str):
    name = name.lower()
    for prop, n in VIDEOPROCAMP.items():
        if n == name:
            return "procamp", prop
    for prop, n in CAMERACONTROL.items():
        if n == name:
            return "camera", prop
    return None, None


def do_set(cam: WinXU, name: str, value: str) -> int:
    which, prop = find_control(name)
    if which is None:
        print(f"unknown control '{name}'. Known: "
              f"{sorted(list(VIDEOPROCAMP.values()) + list(CAMERACONTROL.values()))}",
              file=sys.stderr)
        return 2
    iface = cam.query(IAMVideoProcAmp if which == "procamp" else IAMCameraControl)
    if value.lower() == "auto":
        iface.Set(prop, 0, FLAG_AUTO)
        print(f"{name}: set to auto")
    else:
        iface.Set(prop, int(value, 0), FLAG_MANUAL)
        print(f"{name}: set to {int(value, 0)} (manual)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", nargs=2, metavar=("CONTROL", "VALUE"),
                    help="set CONTROL to VALUE, or to 'auto'")
    args = ap.parse_args()

    try:
        with WinXU(VID, PID) as cam:
            print(f"Device path: {cam.device_path}")
            if args.set:
                return do_set(cam, args.set[0], args.set[1])
            list_controls("VideoProcAmp (image)",
                          cam.query(IAMVideoProcAmp), VIDEOPROCAMP)
            list_controls("CameraControl (lens/exposure)",
                          cam.query(IAMCameraControl), CAMERACONTROL)
    except XUWinError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except PROBE_ERRORS as e:
        print(f"COM error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
