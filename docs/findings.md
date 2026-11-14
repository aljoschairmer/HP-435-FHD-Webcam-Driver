# Findings: HP 430/435 FHD Webcam

## 1. Identification

Collected on Windows with PowerShell (`Get-PnpDevice` / `Get-PnpDeviceProperty`)
and [UsbTreeView](https://www.uwe-sieber.de/usbtreeview_e.html). The full decoded
descriptor set is in [`../descriptors/hp-435-usbtreeview.txt`](../descriptors/hp-435-usbtreeview.txt).

| Function | Hardware ID | Windows driver |
|---|---|---|
| Composite device | `USB\VID_03F0&PID_794A&REV_2011` | `usbccgp.sys` (`usb.inf`) |
| Camera (MI_00) | `USB\VID_03F0&PID_794A&REV_2011&MI_00` | `usbvideo.inf` (in-box UVC) |
| Microphone (MI_02) | `USB\VID_03F0&PID_794A&REV_2011&MI_02` | `wdma_usb.inf` (in-box UAC) |

- `03f0:794a` was not present in `usb.ids` or on linux-hardware.org at the time of writing.
- PID pattern matches HP's sibling webcams: 320 FHD `03f0:654a`, 325 FHD `03f0:664a`
  (SunplusIT), 620/625 FHD `03f0:714a` (Alpha Imaging).
- HP's datasheet lists the sensor as **OmniVision OV2735** and the management
  software as **Poly Lens**. The firmware image confirms the sensor and names
  the ISP as a **Sunplus SPCA2281D** — see [`firmware-analysis.md`](firmware-analysis.md).

## 2. Device descriptor

```
bcdUSB        0x0201   (BOS present)
bDeviceClass  0xEF/0x02/0x01 (IAD composite)
idVendor      0x03F0   HP Inc.
idProduct     0x794A
bcdDevice     0x2011   -> firmware 20.11 (BCD)
iManufacturer "SunplusIT Inc"
iProduct      "HP 430/435 FHD Webcam"
MaxPower      500 mA, High-Speed only
```

## 3. Video function (UVC 1.00, dwClockFreq 48 MHz)

**Camera terminal controls:** AE mode, AE priority, exposure (absolute),
focus (absolute), focus auto, window, region of interest.

**Processing unit controls:** brightness, contrast, hue, saturation, sharpness,
gamma, white-balance temperature (+auto), backlight compensation, power-line frequency.

**Extension units**

| Unit | GUID | Controls | Source |
|---|---|---|---|
| 3 | `{D5C2F42C-1808-4D9F-BE56-753E271C9244}` | 3 (`bmControls 07 00 00 00`) | PU 2 |
| 4 | `{63610682-5070-49AB-B8CC-B3855E8D221D}` | 25 (`bmControls FF FF 77 07`) | XU 3 |

Unit 4 is the Sunplus vendor XU used by fwupd (see
[`sunplus-xu-protocol.md`](sunplus-xu-protocol.md)). Unit 3 differs from the
reference Sunplus camera and is probably an HP/Poly-specific extension.

**Formats** (default modes):

| Resolution | MJPEG | YUY2 |
|---|---|---|
| 1920×1080 | 30 fps | 5 fps |
| 1280×720 | 60 fps | 10 fps |
| 1024×576 | 30 | 15 |
| 800×600 | 30 | 20 |
| 640×480 / 640×360 / 320×240 | 30 | 30 |
| 160×120 | 30 | 5 |

Isochronous alternate settings: 192 … 944 bytes/µframe (single transaction).

## 4. Other interfaces

**Audio (interfaces 2/3):** standard USB Audio Class 1, "HP 430/435 FHD Webcam microphone".

**Vendor HID (interface 4)**, interrupt IN EP 0x84, 1 ms:

| Usage page | Report ID | Type | Size |
|---|---|---|---|
| `0xFFA0` | `0x05` | Feature | 511 bytes |
| `0xFFA0` | `0x06` | Feature | 256 bytes |
| `0xFFA0` | `0x08` | Feature | 4 bytes |
| `0xFFA0` | `0x09` | Input | 3 bytes |
| `0xFF99` | `0x9A` | Feature | 31 bytes |

The large feature reports look like a bulk data/command channel, most likely used
by Poly Lens (settings and possibly firmware updates). Not yet analysed.

**BOS:** one MS OS 2.0 platform capability (Windows ≥ 10.0, descriptor set 232 bytes,
vendor code `0x01`).

## 5. Feasibility

| Goal | Assessment |
|---|---|
| Custom host driver / tool (Linux, Windows, macOS) | **Easy.** Standard UVC/UAC; vendor XUs and HID channel identified. |
| Firmware backup over USB (no soldering) | **Confirmed** via XU 4 `ReadAddr`/`ReadChunk` on Windows (read-only, no download mode). See [`windows-probe.md`](windows-probe.md). |
| Modifying existing firmware (strings, formats, tuning tables) | **Plausible.** fwupd treats the protocol as unsigned (XOR-8 checksum only). Requires care. |
| Writing new firmware from scratch | **Hard.** No SDK, no ISP/ROM documentation; probably 8051-based. |

Hardware limits that firmware cannot change: OV2735 maxes out at 1080p30;
USB 2.0 High-Speed bandwidth limits uncompressed modes.

## 6. Open questions / next steps

1. Run `tools/xu_probe.py` on Linux: confirm `GET_LEN` for unit 4 selectors
   (`0x0E` → 4, `0x16` → 64 expected).
2. Run `tools/flash_dump.py`: check whether reads work outside download mode; dump twice and compare hashes.
3. Capture a Poly Lens session/firmware update with Wireshark + USBPcap to see
   whether HP uses XU 4 or the HID channel, and to obtain the official image.
4. Open the case: confirm ISP part number and SPI flash chip (backup path via
   CH341A + SOIC-8 clip).
5. Map the unit 3 controls and the HID reports.
