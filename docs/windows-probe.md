# Confirmed: Windows extension-unit probe

Captured with `windows/xu_probe_win.py` against a real HP 430/435 FHD Webcam
(`03f0:794a`, firmware 20.11) through the in-box `usbvideo.sys` driver. Both
vendor extension units are fully reachable from user space via DirectShow
`IKsControl` — no driver swap, no Linux required.

The KS topology has 6 nodes. `IKsTopologyInfo::get_NodeType` returns unusable
values on this device, so the extension-unit node is found by probing the XU
property set on each node (the node that is not the XU answers with HRESULT
`0x80070492`, "property set not present"). Resolved nodes: unit 3 → node 2,
unit 4 → node 5 also answers generically and is ignored.

## Unit 3 — HP `{D5C2F42C-1808-4D9F-BE56-753E271C9244}` (node 2)

`EXTENSION_UNIT_INFO`: GUID + `03 01 02 04 07 00 00 00` → 3 controls,
`bmControls 07`. Readable selectors: `0x01`, `0x02`, `0x03` (all 1 byte). Likely
an HP/Poly-specific extension; purpose not yet mapped.

## Unit 4 — Sunplus `{63610682-5070-49AB-B8CC-B3855E8D221D}` (node 3)

`EXTENSION_UNIT_INFO`: GUID + `19 01 03 04 ff ff 77 07` → **25 controls**,
`bmControls FF FF 77 07`, matching the USB descriptor exactly.

Confirmed selectors (GET lengths and sample current values):

| Sel | len | fwupd role | sample GET_CUR |
|----:|----:|---|---|
| 0x01 | 1 | — | `01` |
| 0x02 | 2 | Reg16Cmd (ASIC reg addr) | `00 20` |
| 0x03 | 1 | Reg8Data (ASIC reg value) | `00` |
| 0x04 | 2 | — | `00 00` |
| 0x05 | 2 | — | `ff 00` |
| 0x06 | 1 | — | `01` |
| 0x07 | 1 | — | `01` |
| 0x08 | 1 | — | `03` |
| 0x09 | — | Enable (download) — **write, not probed** | — |
| 0x0A | — | Access (payload) — **write, not probed** | — |
| 0x0B | 1 | Checksum (XOR-8) | `00` |
| 0x0C | 1 | Finish | `00` |
| 0x0D | 4 | — | `00 00 00 00` |
| 0x0E | 4 | **ReadAddr (u32 LE)** | `00 00 00 00` |
| 0x10 | 1 | — | `00` |
| 0x11 | 2 | — | `01 00` |
| 0x12 | 8 | — | `08 08 4c 55 ff …` |
| 0x13 | 16 | — | `00 00 00 00 1e 00 1e 00 04 04 00 …` |
| 0x15 | 1 | — | `00` |
| 0x16 | 64 | **ReadChunk (64 bytes @ ReadAddr)** | see below |
| 0x17 | 4 | — | `00 00 00` |

`0x16` read at the default address (0) returned:

```
02 07 c0 8a 81 d5 8c 00 7d 00 96 00 c8 01 2c 01 90 01 f4 03 e8 07 d0 0b b8
0f a0 13 88 17 70 1b 58 1f 40 23 28 27 10 aa aa 00 00 8a 81 d6 1d 00 00 00
00 8a 81 cf 85 01 03 00 30 00 01 00 00 00
```

The first bytes `02 07 c0` are an 8051 `LJMP 0x07C0` reset vector, so `0x16`
reads the firmware image itself. The ascending big-endian words
`03 e8 … 27 10` (1000, 2000, … 10000) are a vendor table a little further in.

## Consequences

- A firmware **backup is readable on Windows**, via `0x0E` + `0x16`, without
  entering download mode (no write path touched). See `windows/flash_dump_win.py`.
- The feasibility table in `findings.md` for "firmware backup over USB" moves
  from *likely* to **confirmed** on this unit.
- Reads happen outside download mode, so a dump is low-risk; the risky path
  (`0x09`/`0x0A`/`0x0C` + ASIC soft reset) is only needed for writing and is not
  exercised by the read-only tools.
