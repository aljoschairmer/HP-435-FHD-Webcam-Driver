# Firmware analysis — HP 430/435 FHD Webcam

Static analysis of the 128 KiB flash image read from the camera (firmware
20.11, SHA256 `247eb743…b35985`). Tools used: a purpose-built 8051 disassembler,
signature and string scanning, a recursive-descent code tracer, and Ghidra
11.3.2 headless (8051 language). The firmware image itself is **not** in this
repository (proprietary; `*.bin` is git-ignored); only offsets, sizes and
non-proprietary structural facts are recorded here.

> Scope and honesty: the hardware identity, flash layout and embedded protocols
> below are **read directly out of the image** and are solid data. Instruction-
> level behaviour is **not** recoverable from this dump: the image does not
> disassemble as flat in-place code (see §3), so no per-function claims are made.

## 1. Hardware identity (confirmed from embedded strings)

The image contains build tags that name the silicon and sensor outright:

| Offset | String |
|---|---|
| `0x5357` | `YJGD_SPCA2281D_OV2735_J20220524_V0_M5` |
| `0x6448` | `YJGD_SPCA2281D_OV2735_J20230413_V0_M5 FaceAe 60hz HID BCD1001` |
| `0x635a` | `J20230413V0` |
| `0x63a4` | `AM1NPAFAT V0` |

- **ISP / USB controller: Sunplus SPCA2281D.** (The fwupd reference camera we
  compared against earlier used an SPCA2092C; this unit is the newer 2281D.)
- **Image sensor: OmniVision OV2735** — matches HP's datasheet.
- **ODM tag `YJGD`**, build dates 2022-05-24 and 2023-04-13 (the image carries
  two build stamps; the active descriptor reports firmware 20.11).
- **Feature tag:** `FaceAe` (face-priority auto-exposure), `60hz` (flicker),
  `HID` (the vendor HID management interface), `BCD1001`.

This supersedes the earlier guess ("SunplusIT or Alpha Imaging"): it is
definitively a Sunplus SPCA2281D.

## 2. Flash layout (128 KiB)

| Range | Contents |
|---|---|
| `0x00000`–~`0x1E00` | code region (8051-family; not in-place executable, see §3) |
| `0x01E77`–`0x01FFF` | embedded JSON command protocol strings (see §4) |
| `0x02080` | USB **device descriptor** (verbatim), then a sparse region |
| `0x02142` | per-unit identity block (holds the USB serial string) |
| ~`0x03000`–`0x05000` | code/data, tuning and sensor tables (OV2735 init) |
| `0x05541` | second USB device descriptor copy (bcdDevice `0x2010`) |
| `0x0559E` | `MSFT100` — Microsoft OS string descriptor |
| ~`0x05500`–`0x05900` | full USB **configuration descriptor** incl. both XU descriptors |
| `0x0623E`–`0x062F0` | Windows UVC registry flags (see §5) |
| `0x06312`–`0x063E0` | USB string descriptors (`SunplusIT Inc`, `HP 430/435 FHD Webcam`, …) |
| `0x06400`,`0x06422` | manufacturing test entry names `Register_Test`, `Controller_Test` |
| ~`0x07000`–`0x1D8D3` | bulk code/data region (8051-family, not in-place) |
| `0x1D8D4`–`0x1EFFF` | erased (`FF`) |
| `0x1F000`–`0x1F12F` | small settings/parameter block on a 4 KiB sector boundary |
| `0x1F130`–`0x1FFFF` | erased (`FF`) |

The USB device descriptor at `0x2080`
(`12 01 01 02 ef 02 01 40 f0 03 4a 79 11 20 01 02 03 01`) is byte-for-byte the
descriptor the camera enumerates with. The full configuration descriptor,
including the two Extension Unit descriptors (unit 3 GUID `D5C2F42C…`, unit 4
Sunplus GUID `63610682…` with `bNumControls 0x19`, `bmControls FF FF 77 07`), is
stored verbatim around `0x5500`, confirming where the device's advertised
topology comes from.

## 3. CPU core and why the code does not disassemble in place

The image carries hallmarks of an **8051-family** image — byte `0x00` at offset
0 is `02 07 C0` = `LJMP 0x07C0`, and `MOVX`/`MOV DPTR`/`LJMP`/`LCALL` opcode
bytes are common — but it **does not execute flat from this flash layout**, and
its instruction stream is not statically recoverable from the dump alone:

- A recursive-descent trace from the reset vector (and the would-be interrupt
  vectors at `0x03`,`0x0B`,…) collapses after ~37 bytes, hitting undefined
  opcodes and incoherent branches.
- Linear disassembly at the reset target `0x07C0`, and at the most-referenced
  branch targets (`0x7CB3`, reached by 87 `LCALL`s; `0xB492` by 168 `LJMP`s),
  decodes to noise.
- Ghidra's headless 8051 analysis of the low 32 KiB, imported flat, defined **no
  functions or instructions** — consistent with the same conclusion.

The most likely explanation for a Sunplus SPCA-series ISP: the SPI image is
**not** run in place. A boot ROM reads it — behind a header and possibly
descrambled or overlaid — and loads code into the chip's internal program RAM at
run time. The branch-byte histogram still shows a few dominant targets, hinting
at shared routines, but without the boot ROM's load/relocation map the executable
form cannot be reconstructed from this dump. **No per-instruction or
per-function claims are made in this report.** Recovering the code would need the
boot ROM, or on-device tracing of what actually executes.

## 4. Embedded management protocol (JSON over the HID interface)

The common bank contains a small JSON request/response protocol with HTTP-style
status codes — the clearest "how it works" artefact in the image:

```
@type
device_info
{ "device_name":"HP 435 FHD Webcam", "version_hw":"1", "model":"HP 435 FHD Webcam",
  "sn":"20221201", "version_sw":"12.01" }
{ "status code":"200", "msg id":"… }
{ "status code":"404", "status string":"Not Found", "msg id":"0", "diag info":"Fail" }
```

Observed keys: `@type`, `device_info`, `device_name`, `model`, `version_hw`,
`version_sw`, `sn`, `status code`, `status string`, `msg id`, `diag info`.

Interpretation (consistent with the descriptors): this is the transport the
**Poly Lens** app uses to talk to the camera. It almost certainly rides on the
vendor **HID interface (interface 4, usage page `0xFFA0`)** whose feature
reports are 511 and 256 bytes — large enough for these JSON blobs — rather than
on the UVC extension units. A request names a `@type`/command (e.g.
`device_info`) and the camera replies with a JSON object and a status code.
`version_sw` here reads `12.01`, distinct from the USB `bcdDevice` (20.11); the
two version fields come from different build stamps.

This is the decode answer for the earlier open question: the Poly-Lens-only
features are driven through this HID JSON channel, which is why sweeping the
standard UVC controls moved none of the vendor XU selectors.

## 5. USB / host integration

- `MSFT100` at `0x559E`: the Microsoft OS 1.0 string descriptor (index `0xEE`),
  so Windows requests the extended/compat descriptors.
- Windows UVC behaviour flags stored as strings:
  `UVC-EnableDependentStillPinCapture`, `UVC-EnablePlatformDmft`,
  `EnableDshowRedirection`. These correspond to the registry values the UVC
  driver reads — i.e. the camera asks Windows to enable still-image capture, the
  platform camera DMFT, and DirectShow redirection.
- String descriptors `SunplusIT Inc`, `HP 430/435 FHD Webcam`,
  `HP 430/435 FHD Webcam microphone` sit together near `0x6312`.

## 6. Extension-unit / flash machinery (ties to the earlier work)

The unit 4 selectors identified in `windows-probe.md` and
`sunplus-xu-protocol.md` (`0x02`/`0x03` ASIC register window, `0x09` enable,
`0x0A` stream, `0x0B` checksum, `0x0C` finish, `0x0E` read address, `0x16` read
chunk) are the SPCA2281D's standard runtime flash-update/readback interface. The
read path (`0x0E`+`0x16`) is what produced this very image.

## 7. What is established vs. open

**Established (read from the image):** SPCA2281D + OV2735 hardware; full flash
map; verbatim USB descriptors and XU topology; a JSON/HID management protocol
with its command and status vocabulary; Windows integration flags; manufacturing
test hooks; the flash update/read interface; and that the image is an
8051-family blob that is loaded rather than executed in place.

**Open (not recoverable from this static dump):**
- The executable code itself — the dump is not flat in-place code (§3). Would
  need the boot ROM / run-time load map, or on-device tracing.
- The exact command set of the HID JSON protocol beyond `device_info` — capture
  Poly Lens traffic (USBPcap) to enumerate commands and payloads.
- The meaning of individual vendor XU selectors `0x04`,`0x05`,`0x11`,`0x12`,
  `0x13`,`0x17` — best obtained from the same USB capture.

None of this analysis modifies the camera; it is all static inspection of a
read-only dump plus one headless disassembly pass.
