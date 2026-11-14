# Windows tools (no Linux required)

These talk to the camera's vendor extension units through the in-box UVC driver
(`usbvideo.sys`) using DirectShow `IKsControl`. No driver swap, no admin-only
filter install. They are the Windows counterparts of the `tools/` scripts.

> **Status: needs a first test run.** The COM/KS plumbing was written without a
> Windows machine to execute it on. If something raises, copy the full error and
> it can be corrected quickly — the extension-unit node id and selector lengths
> reported by `xu_probe_win.py` are what the dump relies on.

## Setup

1. Install Python 3 for Windows (python.org or `winget install Python.Python.3.12`).
2. Install the dependency:
   ```
   py -3 -m pip install -r windows\requirements.txt
   ```
3. Close any app using the camera (Teams, Camera, browser tabs). The KS property
   calls work while the device is idle; a streaming app can hold the node busy.

## Probe (safe, read-only)

```
py -3 windows\xu_probe_win.py
```

Expected: the device path containing `vid_03f0&pid_794a`, a list of topology
nodes, and for unit 4 (`{63610682-…221D}`) responding selectors including
`0x0E` (len 4) and `0x16` (len 64). Paste this output back to confirm the model
before dumping.

## Firmware backup (read-only)

```
py -3 windows\flash_dump_win.py --out hp435-fw.bin
```

Run it twice to different files and compare the printed `sha256` values; equal
hashes mean the read is stable. `--size` defaults to 128 KiB (`0x20000`), the
full flash of this camera: reads beyond that wrap around to address 0. See
[`../docs/windows-probe.md`](../docs/windows-probe.md) for the flash layout.

## Camera settings (safe, read / write standard controls)

```
py -3 windows\settings_win.py
```

Lists the standard UVC controls the driver exposes — image controls
(brightness, contrast, white balance, ...) via `IAMVideoProcAmp` and
lens/exposure controls (exposure, focus, ...) via `IAMCameraControl` — with each
control's current value, auto/manual mode, and range/step/default.

Optionally change one (these are the same knobs any camera app uses; the
firmware is not touched):

```
py -3 windows\settings_win.py --set brightness 140
py -3 windows\settings_win.py --set focus auto
```

## How it works

| UVC concept | Windows mechanism |
|---|---|
| Extension unit | KS topology node; its node *type GUID* equals the XU GUID |
| XU control selector | `KSPROPERTY.Id` on the property set = XU GUID |
| GET_CUR / SET_CUR | `IKsControl::KsProperty` with `KSP_NODE`, `TYPE_GET`/`TYPE_SET` + `TYPE_TOPOLOGY` |
| GET_LEN | approximated by trying candidate buffer sizes (`probe_size`) |

See [`../docs/sunplus-xu-protocol.md`](../docs/sunplus-xu-protocol.md) for the
selector map.

## Limitations vs. Linux

- Windows exposes XU controls only if the firmware numbers them per the UVC
  conformance rules; a gap in the control bitmap can hide later selectors. If a
  selector the Linux notes expect is missing here, that is why — fall back to a
  Linux live-USB for those.
- There is no clean `GET_LEN`; lengths are discovered by probing.
