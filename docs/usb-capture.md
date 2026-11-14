# Capturing the camera's control traffic (Windows, USBPcap)

The firmware code cannot be recovered statically (see
[`firmware-analysis.md`](firmware-analysis.md)), but the camera's **behaviour**
can be observed: whatever Poly Lens (or any app) changes is sent as USB control
transfers to the extension units and the vendor HID interface. Capturing them
reveals the selector/command and the payload for each feature — including the
JSON management protocol and the vendor XU selectors that never show up as a
GET_CUR change.

This is read-only observation of USB traffic. It does not modify the camera.
**Do not run Poly Lens's firmware-update function while experimenting.**

## 1. Install

Install **Wireshark** and, in its installer, tick the **USBPcap** component
(Wireshark ≥ 4.x bundles it). Reboot if the installer asks. `tshark.exe` is
installed alongside Wireshark (used by the parser in step 4).

## 2. Identify the camera's USB address

1. Plug the camera into a USB port (prefer a USB 2.0 port / direct, not a hub).
2. Launch Wireshark. You'll see capture interfaces named **USBPcap1**,
   **USBPcap2**, … one per host controller/root hub.
3. Start a capture on each USBPcap interface briefly, or use the one whose
   tree (Wireshark shows the connected devices per USBPcap interface) lists
   **HP 430/435 FHD Webcam**. Note its **device address** (e.g. 7). You can also
   read it later from any packet: `usb.device_address`.

Tip: close Teams, the Camera app and browser tabs so the only traffic is from
the app you are testing.

## 3. Capture one feature at a time

1. Start capture on the USBPcap interface the camera is on.
2. In **Poly Lens** (or the Windows Camera app), change **one** setting, wait a
   second, change the next. Narrate to yourself / keep a note of the order — it
   makes matching trivial.
3. Stop the capture and **File → Save As** a `.pcapng`.

### Useful Wireshark display filters

Paste into the filter bar to inspect live or a saved file:

| Goal | Filter |
|---|---|
| All class control transfers to interfaces | `usb.bmRequestType == 0x21 \|\| usb.bmRequestType == 0xa1` |
| UVC **SET_CUR** (app writes a control) | `usb.bmRequestType == 0x21 && usb.setup.bRequest == 0x01` |
| UVC **GET_CUR** (app reads a control) | `usb.bmRequestType == 0xa1 && usb.setup.bRequest == 0x81` |
| Only the **Sunplus XU (unit 4)** on VideoControl if0 | `usb.setup.wIndex == 0x0400` |
| Only the **HP XU (unit 3)** | `usb.setup.wIndex == 0x0300` |
| A specific selector, e.g. **0x0E** | `usb.setup.wValue == 0x0e00` |
| Vendor **HID** feature reports (JSON channel) | `usb.bmRequestType == 0x21 && usb.setup.bRequest == 0x09` (SET) / `0xa1 && 0x01` (GET) |
| Limit to the camera | add `&& usb.device_address == 7` (your address) |

How to read the setup fields:
- **wValue high byte = control selector** (e.g. `0x0e00` → selector `0x0E`).
- **wIndex high byte = entity/unit id** (`0x04` = Sunplus XU, `0x03` = HP XU),
  **low byte = interface** (`0x00` = VideoControl; `0x04` = the vendor HID).
- The transferred bytes are the control payload (`usb.capdata`).

## 4. Parse it into a table

`tools/parse_uvc_capture.py` extracts exactly these transfers, pairs each
GET request with its response, labels the unit and selector, and pulls any JSON
out of the HID feature reports.

```
python3 tools/parse_uvc_capture.py capture.pcapng
python3 tools/parse_uvc_capture.py capture.pcapng --device 7
```

(On Windows: `py -3 tools\parse_uvc_capture.py capture.pcapng`. If `tshark` is
not on PATH, pass `--tshark "C:\Program Files\Wireshark\tshark.exe"`.)

Example output:

```
 frame     t(s)  dir kind request   target                         data
    10    0.100  OUT UVC  SET_CUR   XU4-Sunplus if0 sel0x0e        00 10 00 00
    30    0.300  OUT HID  SET_REPORT HID if4 Feature report 0x05   7b 22 40 74 79 70 65 …
           json: {"@type": "device_info"}
```

## 5. Turn it into a map

For each feature you toggled, note the `request` + `target` + `data`. That gives
a confirmed "feature → selector/report + payload" table you can add to
[`vendor-controls.md`](vendor-controls.md). Send the parsed output over and it
can be folded into the docs, and — for selectors whose payload is a simple value
or the HID JSON commands — turned into a small control tool.

## Notes

- GET responses arrive on a separate completion packet; the parser pairs them by
  USB IRP id, so you still see the returned bytes.
- If a feature changes nothing in the capture, Poly Lens implemented it
  host-side (no device traffic) — a real finding in itself.
- Some controls are sent as standard UVC Processing-Unit / Camera-Terminal
  SET_CUR (entity 1/2), not to the vendor units; the parser labels those too.
