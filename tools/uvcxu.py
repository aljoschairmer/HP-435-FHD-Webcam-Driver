"""Minimal helper for UVC extension-unit (XU) queries on Linux via UVCIOC_CTRL_QUERY.

Pure stdlib. Talks to /dev/videoN through the uvcvideo driver's ioctl interface.
Read-only by design: this module exposes GET_* queries and SET_CUR, but the
higher-level tools in this repo only use SET_CUR for the read-address selector.

References:
- linux/uapi/linux/uvcvideo.h  (struct uvc_xu_control_query, UVCIOC_CTRL_QUERY)
- USB Video Class 1.1/1.5 spec, section 4 (GET_CUR/SET_CUR/GET_MIN/.../GET_INFO)
"""

from __future__ import annotations

import ctypes
import fcntl
import struct

# uvc_xu_control_query.query selector codes (UVC request codes)
UVC_SET_CUR = 0x01
UVC_GET_CUR = 0x81
UVC_GET_MIN = 0x82
UVC_GET_MAX = 0x83
UVC_GET_RES = 0x84
UVC_GET_LEN = 0x85
UVC_GET_INFO = 0x86
UVC_GET_DEF = 0x87

_QUERY_NAMES = {
    UVC_SET_CUR: "SET_CUR",
    UVC_GET_CUR: "GET_CUR",
    UVC_GET_MIN: "GET_MIN",
    UVC_GET_MAX: "GET_MAX",
    UVC_GET_RES: "GET_RES",
    UVC_GET_LEN: "GET_LEN",
    UVC_GET_INFO: "GET_INFO",
    UVC_GET_DEF: "GET_DEF",
}


class uvc_xu_control_query(ctypes.Structure):
    _fields_ = [
        ("unit", ctypes.c_uint8),
        ("selector", ctypes.c_uint8),
        ("query", ctypes.c_uint8),
        ("size", ctypes.c_uint16),
        ("data", ctypes.POINTER(ctypes.c_uint8)),
    ]


def _ioc(direction, type_, nr, size):
    # _IOC(dir, type, nr, size) with Linux generic encoding
    return (direction << 30) | (size << 16) | (ord(type_) << 8) | nr


_IOC_READ = 2
_IOC_WRITE = 1
# UVCIOC_CTRL_QUERY = _IOWR('u', 0x21, struct uvc_xu_control_query)
UVCIOC_CTRL_QUERY = _ioc(_IOC_READ | _IOC_WRITE, "u", 0x21,
                         ctypes.sizeof(uvc_xu_control_query))


class XUError(OSError):
    pass


class XU:
    """Open a V4L2 node and run extension-unit queries against it."""

    def __init__(self, path: str):
        self.path = path
        self._fd = None

    def __enter__(self):
        import os
        self._fd = os.open(self.path, os.O_RDWR)
        return self

    def __exit__(self, *exc):
        import os
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def _query(self, unit, selector, query, size, data=None):
        buf = (ctypes.c_uint8 * size)()
        if data is not None:
            for i, b in enumerate(data[:size]):
                buf[i] = b
        q = uvc_xu_control_query(
            unit=unit, selector=selector, query=query, size=size,
            data=ctypes.cast(buf, ctypes.POINTER(ctypes.c_uint8)),
        )
        try:
            fcntl.ioctl(self._fd, UVCIOC_CTRL_QUERY, q)
        except OSError as e:
            raise XUError(
                e.errno,
                f"{_QUERY_NAMES.get(query, hex(query))} unit=0x{unit:02x} "
                f"selector=0x{selector:02x} size={size}: {e.strerror}",
            ) from None
        return bytes(buf)

    def get_len(self, unit, selector) -> int:
        raw = self._query(unit, selector, UVC_GET_LEN, 2)
        return struct.unpack("<H", raw)[0]

    def get_info(self, unit, selector) -> int:
        return self._query(unit, selector, UVC_GET_INFO, 1)[0]

    def get_cur(self, unit, selector, size) -> bytes:
        return self._query(unit, selector, UVC_GET_CUR, size)

    def get(self, unit, selector, query, size) -> bytes:
        return self._query(unit, selector, query, size)

    def set_cur(self, unit, selector, data: bytes) -> None:
        self._query(unit, selector, UVC_SET_CUR, len(data), data)


def decode_info(info: int) -> str:
    caps = []
    if info & 0x01:
        caps.append("GET")
    if info & 0x02:
        caps.append("SET")
    if info & 0x04:
        caps.append("disabled")
    if info & 0x08:
        caps.append("autoupdate")
    if info & 0x10:
        caps.append("async")
    return "|".join(caps) if caps else "none"
