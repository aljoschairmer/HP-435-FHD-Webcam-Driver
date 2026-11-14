# Sunplus UVC extension-unit protocol

This summarises how the upstream fwupd `sunplus-camera` plugin talks to Sunplus
ISPs, and how that maps onto the HP 430/435 FHD Webcam.

Source: `plugins/sunplus-camera/` in [fwupd](https://github.com/fwupd/fwupd)
(fwupd ≥ 2.1.2), reference device `1bcf:2ced` (HYGD "Hy-UXGA(9240)" camera with a
Sunplus **SPCA2092C** ISP and an OV2740 sensor, shipped by Star Labs).

## Extension unit

| | Reference camera `1bcf:2ced` | HP 430/435 `03f0:794a` |
|---|---|---|
| Unit 3 GUID | `28F03370-6311-4A2E-BA2C-6890EB334016` | `D5C2F42C-1808-4D9F-BE56-753E271C9244` |
| Unit 4 GUID | `63610682-5070-49AB-B8CC-B3855E8D221D` | `63610682-5070-49AB-B8CC-B3855E8D221D` ✅ |
| fwupd uses | unit **4** (hard-coded) | unit 4 present |

## Selectors (unit 4)

UVC selector *n* corresponds to bit *n‑1* of the XU's `bmControls`.
HP 435 unit 4 `bmControls = FF FF 77 07`.

| Selector | fwupd name | Purpose | Direction | HP 435 advertises |
|---|---|---|---|---|
| `0x02` | `Reg16Cmd` | select 16-bit ASIC register address | SET | ✅ |
| `0x03` | `Reg8Data` | read/write 8-bit ASIC register value | GET/SET | ✅ |
| `0x09` | `Enable` | enter/leave ISP download mode | SET | ✅ |
| `0x0A` | `Access` | stream firmware payload | SET | ✅ |
| `0x0B` | `Checksum` | XOR-8 checksum of transferred data | GET | ✅ |
| `0x0C` | `Finish` | finalise transfer | SET | ✅ |
| `0x0E` | `ReadAddr` | set flash read address (u32 LE) | SET | ✅ |
| `0x16` | `ReadChunk` | read 64 bytes from flash at read address | GET | ✅ |

Notable ASIC registers used by fwupd: `0x2501` download state; soft reset is a
write sequence to `0x2030..0x2034`.

## Update flow in fwupd (for reference only)

1. `Enable = 1`, clear download-state register `0x2501`
2. stream payload through `Access` in chunks (`GET_LEN` of `Access` = chunk size)
3. compare device `Checksum` with host XOR-8 of the payload
4. `Finish = 1`
5. verify by reading back 64-byte blocks (`ReadAddr` + `ReadChunk`)
6. soft reset via ASIC registers, wait for re-enumeration

fwupd flags the device `UNSIGNED_PAYLOAD`: there is **no cryptographic signature
check**, only the XOR-8 checksum and the read-back verification. Version numbers
are the USB `bcdDevice` interpreted as BCD (reference: `0x0907` → 9.7, matching the
LVFS release; HP 435: `0x2011` → 20.11).

The reference firmware image on LVFS is ~32 KiB. Its byte statistics (very high
frequency of `MOV DPTR,#` / `MOVX` opcodes) strongly suggest an **8051-family** core.

## What this repository does with it

Only the read path: `ReadAddr` (`SET_CUR`, 4 bytes) followed by `ReadChunk`
(`GET_CUR`, 64 bytes). See `tools/flash_dump.py`. It is **not yet confirmed**
that the read path works without first entering download mode on this camera;
the tool reports this instead of trying to force it.
