# Decoding the vendor extension-unit controls

Units 3 and 4 carry vendor-specific controls with no public documentation. This
page records what is **confirmed**, what is **inferred**, and how to decode the
rest. Everything here is read-only observation unless stated otherwise.

## What is confirmed

### Unit 4 — Sunplus `{63610682-5070-49AB-B8CC-B3855E8D221D}` (25 controls)

Eight selectors match the fwupd `sunplus-camera` plugin's firmware-update
protocol exactly (same GUID, same unit, same selector numbers). These are **not
user settings** — they are the flash update/read machinery:

| Sel | Role (from fwupd) | Notes |
|----:|---|---|
| 0x02 | Reg16Cmd | select a 16-bit ASIC register address |
| 0x03 | Reg8Data | read/write the 8-bit value at that register |
| 0x09 | Enable | enter/leave ISP download mode (**write**) |
| 0x0A | Access | stream firmware payload (**write**) |
| 0x0B | Checksum | XOR-8 of transferred data |
| 0x0C | Finish | finalise transfer |
| 0x0E | ReadAddr | set 32-bit flash read address |
| 0x16 | ReadChunk | read 64 bytes at ReadAddr (used for the flash dump) |

`0x02`/`0x03` are a general ASIC register window: with them the whole register
space is reachable, which is how the other behaviour is ultimately controlled.

### Unit 3 — HP `{D5C2F42C-1808-4D9F-BE56-753E271C9244}` (3 controls)

Selectors `0x01`, `0x02`, `0x03`, each 1 byte, all read `00` at rest. Likely an
HP/Poly-specific extension (e.g. a feature toggle or a Poly Lens handshake).
Purpose not yet established.

## Result of the automatic sweep

`windows/xu_autodecode_win.py` drove all 11 standard controls the camera exposes
(brightness, contrast, hue, saturation, sharpness, gamma, white balance + auto,
backlight compensation, power-line frequency, exposure + auto, focus + auto) to
their min/max and toggled auto, while watching 20 vendor selectors
(unit 3: 3, unit 4: 17).

A second run read every control back after setting it: all 22 stimuli (min and
max for each of the 11 controls) were applied by the camera, so the result is
not an artefact of ignored writes.

**No vendor selector changed for any standard control.** The standard controls
are handled by the regular UVC units (Processing Unit, Camera Terminal) inside the
firmware; the vendor extension units are *separate channels*, not mirrors of the
standard settings:

- **Unit 4** behaves as a service channel: firmware update, flash read, ASIC
  register access (see the confirmed table above), plus vendor-only values.
- **Unit 3** is a small HP-specific extension (3 controls).

Consequence: the remaining selectors can only be decoded through features that
have **no** standard UVC control — i.e. what Poly Lens toggles — or by capturing
what Poly Lens sends (Method D below). Selectors that act as write-triggered
commands may never change on GET_CUR at all, which is why the USB capture is the
more reliable route.

## What is still unknown

Unit 4 selectors that are **not** part of the update protocol, with their
observed length and value at rest (from `docs/windows-probe.md`):

| Sel | len | at rest | working hypothesis (unverified) |
|----:|----:|---|---|
| 0x01 | 1 | `01` | an enable/mode flag |
| 0x04 | 2 | `00 00` | ? |
| 0x05 | 2 | `ff 00` | ? (0x00ff) |
| 0x06 | 1 | `01` | ? |
| 0x07 | 1 | `01` | ? |
| 0x08 | 1 | `03` | ? |
| 0x0D | 4 | `00 00 00 00` | ? |
| 0x10 | 1 | `00` | ? |
| 0x11 | 2 | `01 00` | ? |
| 0x12 | 8 | `08 08 4c 55 ff …` | looks like an ID / build field |
| 0x13 | 16 | `00 00 00 00 1e 00 1e 00 04 04 00 …` | `1e 00 1e 00` = 30,30 → maybe fps-related |
| 0x15 | 1 | `00` | ? |
| 0x17 | 4 | `00 00 00 …` | ? |

These hypotheses are guesses from a single at-rest reading and must not be
trusted until the decode steps below confirm them.

## How to decode the rest

### Method 0 — automatic sweep (Windows, start here)

`windows\xu_autodecode_win.py` does methods A below for you: it drives every
standard UVC control to its extremes (and toggles auto), watches the unit 3/4
selectors, and prints which selector each control moved, plus the selectors no
standard control touched. Run it first to get the base map, then use Method A
for the Poly-Lens-only features that have no standard control.

```
py -3 windows\xu_autodecode_win.py --save report.json
```

### Method A — watch a value change (Windows, no reboot)

The reliable way to map a selector to a feature. In one terminal:

```
py -3 windows\xu_watch_win.py --monitor
```

Then change exactly one thing at a time — in Poly Lens, the Windows Camera app,
or with `windows\settings_win.py --set <control> <value>` — and read off which
selector moves. Work through: brightness, contrast, white-balance auto on/off,
exposure auto/manual, focus near/far, the privacy shutter, any Poly Lens
"auto-framing"/"boundary"/HDR toggle. Record each mapping in the table above.

Snapshot/diff instead of live monitoring:

```
py -3 windows\xu_watch_win.py --save before.json
# change one setting
py -3 windows\xu_watch_win.py --diff before.json
```

### Method B — read the ranges (Linux live-USB)

Windows only exposes GET_CUR for XU controls. Linux (`uvcvideo`) also exposes
GET_MIN/MAX/RES/DEF, which reveal a control's range and default — often enough
to guess its meaning (a 0..10000 range vs a 0..1 toggle vs a fixed ID string):

```
python3 tools/xu_probe.py
```

The probe now prints cur/min/max/res/def per selector where available.

### Method D — capture what Poly Lens sends (Windows, most reliable)

Poly Lens is HP's management app for this camera. Whatever it toggles is sent
as UVC class requests to the extension units, so capturing them shows the
selector *and* the payload directly — including command-style selectors that
never show up as a GET_CUR change:

1. Install Wireshark with the USBPcap component.
2. Start a capture on the USBPcap root hub the camera is connected to.
3. In Poly Lens, change one feature at a time and note the time.
4. Filter for extension-unit SET_CUR requests:
   `usb.bmRequestType == 0x21 && usb.setup.bRequest == 0x01`
   In UVC, `wValue` high byte = selector, `wIndex` high byte = unit ID
   (3 or 4), low byte = interface 0.

Do not use Poly Lens's firmware-update function while experimenting.

See [`usb-capture.md`](usb-capture.md) for the full step-by-step (interfaces,
filters) and `tools/parse_uvc_capture.py`, which turns a `.pcapng` into a table
of UVC/HID control transfers with the unit, selector and payload decoded.

### Method C — correlate with ASIC registers (advanced)

Because `0x02`/`0x03` expose the ASIC register window, a change seen in Method A
can be traced to a specific hardware register by reading neighbouring registers
before/after. This is how the sensor/ISP tuning is ultimately stored; it is the
most invasive to explore and is not needed just to map the user-facing controls.

## Notes

- Keep changes to one setting at a time, or the diff is ambiguous.
- Some Poly Lens features may be implemented host-side and touch **no** selector.
- Setting standard UVC controls (via `settings_win.py`) is safe; it does not
  write to flash. The update-protocol selectors (`0x09`/`0x0A`/`0x0C`) are the
  only genuinely dangerous ones and the read-only tools never write them.
