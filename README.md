# HP 430/435 FHD Webcam – driver & firmware research

Research notes and tooling for the **HP 430/435 FHD Webcam** (HP part 77B10AA / 77B11AA).
The goal is to understand the camera well enough to build custom host-side
drivers/tools and to evaluate whether its firmware can be backed up and modified.

> **Status:** research. The camera is identified, its vendor control channels are
> mapped, and read-only Linux tools are provided. Nothing here writes to the camera's flash.

## Key facts

| | |
|---|---|
| USB ID | `03f0:794a` (HP Inc.) |
| Manufacturer string | `SunplusIT Inc` → Sunplus image-signal-processor (ISP) |
| Product string | `HP 430/435 FHD Webcam` |
| Firmware version | `bcdDevice 0x2011` (BCD → **20.11**) |
| Sensor | OmniVision OV2735 (per HP datasheet), 1080p30 max |
| UVC | 1.00, MJPEG up to 1080p30 / 720p60, YUY2 (1080p only at 5 fps) |
| Interfaces | 0 Video Control · 1 Video Streaming · 2+3 USB Audio (dual mic) · 4 vendor HID |
| Windows drivers | in-box only: `usbvideo.inf`, `wdma_usb.inf`, `usbccgp` |
| Extension Units | Unit 3 `{D5C2F42C-1808-4D9F-BE56-753E271C9244}` (3 controls) |
| | Unit 4 `{63610682-5070-49AB-B8CC-B3855E8D221D}` (25 controls) – Sunplus vendor XU |

Unit 4's GUID and unit ID are identical to the Sunplus camera supported by the
[fwupd `sunplus-camera` plugin](https://fwupd.github.io/libfwupdplugin/sunplus-camera-README.html),
and every selector that plugin uses is advertised by this camera. See
[`docs/sunplus-xu-protocol.md`](docs/sunplus-xu-protocol.md).

## Repository layout

```
docs/findings.md             full write-up: identification, descriptors, feasibility
docs/sunplus-xu-protocol.md  Sunplus extension-unit protocol as used by fwupd
descriptors/                 decoded USB descriptors (UsbTreeView, serial redacted)
tools/uvcxu.py               small Linux helper for UVC extension-unit queries
tools/xu_probe.py            Linux, read-only: list XU controls (GET_INFO/GET_LEN/GET_CUR...)
tools/flash_dump.py          Linux, read-only: back up the SPI flash via XU unit 4
windows/uvcxu_win.py         Windows helper: XU access via DirectShow IKsControl
windows/xu_probe_win.py      Windows, read-only: probe XU controls
windows/flash_dump_win.py    Windows, read-only: back up the flash via XU unit 4
windows/README.md            Windows usage (no Linux needed; needs comtypes)
```

Linux is the most reliable host (see Quick start below). If you only have
Windows, use the `windows/` tools instead — same read-only approach, through the
in-box UVC driver; see [`windows/README.md`](windows/README.md).

## Quick start (Linux)

The tools need Python ≥ 3.8, the `uvcvideo` kernel driver and read/write access
to the camera's `/dev/videoN` node (run as root or add yourself to the `video` group).

```bash
python3 tools/xu_probe.py
```

```bash
python3 tools/flash_dump.py --out hp435-fw-20.11.bin
```

Both tools verify that the device is `03f0:794a` and that unit 4 carries the
expected Sunplus GUID before sending anything. They only issue `GET_*` requests,
plus `SET_CUR` on the *read-address* selector (`0x0E`). They never touch the
download/write/finish selectors or the ASIC register selectors.

Dumps (`*.bin`) are git-ignored on purpose: firmware images are HP/Sunplus
proprietary and must not be committed.

## Safety

- Reading should be harmless, but this is undocumented vendor functionality. Use at your own risk.
- **Never** flash firmware from another Sunplus camera (e.g. the Star Labs/HYGD
  SPCA2092C image on LVFS) onto this webcam: different sensor, possibly different ISP.
- A failed write can leave the ISP in recovery mode (`1bcf:0b09`), which fwupd does
  not support; recovery would then require an external SPI programmer.

## References

- fwupd Sunplus Camera plugin – <https://fwupd.github.io/libfwupdplugin/sunplus-camera-README.html>
- LVFS issue #935 (Sunplus/HP camera firmware) – <https://gitlab.com/fwupd/lvfs-website/-/issues/935>
- HP 435 FHD Webcam datasheet – <https://h20195.www2.hp.com/v2/GetDocument.aspx?docname=c08757898>
- OmniVision OV2735 product brief – <https://www.ovt.com/wp-content/uploads/2023/07/OV2735-PB-v1.4-WEB.pdf>
- Linux UVC driver – <https://www.ideasonboard.org/uvc/>
