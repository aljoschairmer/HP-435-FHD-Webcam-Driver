"""Windows helper for UVC extension-unit (XU) access via DirectShow IKsControl.

No driver swap: this talks to the in-box usbvideo.sys through the KS property
mechanism the UVC class driver exposes for extension units. An XU control is
addressed by a KSP_NODE whose property Set is the extension unit's GUID, whose
property Id is the UVC control selector, and whose NodeId is the XU's topology
node. Background:
  https://learn.microsoft.com/windows-hardware/drivers/stream/device-requirements-for-usb-video-class-extension-units
  https://learn.microsoft.com/windows-hardware/drivers/stream/extension-unit-plug-in-architecture

Requires:  pip install comtypes   (Python 3.8+, Windows)

Read-only by intent: the shipped tools use get()/get_info()/probe_size() and only
set() the read-address selector. Nothing here enters download or write mode.

NOTE: This has not been executed in-house. If a COM call raises, capture the full
traceback and HRESULT; the interface vtable layout is the most likely thing to fix.
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER, byref, c_void_p, c_ulong, sizeof
from ctypes.wintypes import ULONG

import comtypes
from comtypes import GUID, COMMETHOD, HRESULT, IUnknown, CoCreateInstance
from comtypes.persist import IPersistStream, IPropertyBag

# ---- CLSIDs / IIDs ---------------------------------------------------------

CLSID_SystemDeviceEnum = GUID("{62BE5D10-60EB-11D0-BD3B-00A0C911CE86}")
CLSID_VideoInputDeviceCategory = GUID("{860BB310-5D01-11D0-BD3B-00A0C911CE86}")
IID_ICreateDevEnum = GUID("{29840822-5B84-11D0-BD3B-00A0C911CE86}")
IID_IEnumMoniker = GUID("{00000102-0000-0000-C000-000000000046}")
IID_IMoniker = GUID("{0000000F-0000-0000-C000-000000000046}")
IID_IKsControl = GUID("{28F54685-06FD-11D2-B27A-00A0C9223196}")
IID_IKsTopologyInfo = GUID("{720D4AC0-7533-11D0-A5D6-28DB04C10000}")
IID_IBaseFilter = GUID("{56A86895-0AD4-11CE-B03A-0020AF0BA770}")

# KS property flags
KSPROPERTY_TYPE_GET = 0x00000001
KSPROPERTY_TYPE_SET = 0x00000002
KSPROPERTY_TYPE_TOPOLOGY = 0x10000000

# XU property id 0 = KSPROPERTY_EXTENSION_UNIT_INFO (capabilities / descriptor)
KSPROPERTY_EXTENSION_UNIT_INFO = 0


# ---- Structures ------------------------------------------------------------

class KSPROPERTY(ctypes.Structure):
    _fields_ = [("Set", GUID), ("Id", ULONG), ("Flags", ULONG)]


class KSP_NODE(ctypes.Structure):
    _fields_ = [("Property", KSPROPERTY), ("NodeId", ULONG), ("Reserved", ULONG)]


# ---- COM interfaces (only the methods we call; vtable order matters) -------

class IEnumMoniker(IUnknown):
    _iid_ = IID_IEnumMoniker
    _methods_ = [
        COMMETHOD([], HRESULT, "Next",
                  (["in"], ULONG, "celt"),
                  (["out"], POINTER(c_void_p), "rgelt"),
                  (["out"], POINTER(ULONG), "pceltFetched")),
        COMMETHOD([], HRESULT, "Skip", (["in"], ULONG, "celt")),
        COMMETHOD([], HRESULT, "Reset"),
    ]


class IMoniker(IPersistStream):
    # IMoniker : IPersistStream : IPersist : IUnknown
    # Only BindToObject and BindToStorage are needed; they are the first two
    # IMoniker-specific methods, so later methods can be omitted safely.
    _iid_ = IID_IMoniker
    _methods_ = [
        COMMETHOD([], HRESULT, "BindToObject",
                  (["in"], c_void_p, "pbc"),
                  (["in"], c_void_p, "pmkToLeft"),
                  (["in"], POINTER(GUID), "riidResult"),
                  (["out"], POINTER(c_void_p), "ppvResult")),
        COMMETHOD([], HRESULT, "BindToStorage",
                  (["in"], c_void_p, "pbc"),
                  (["in"], c_void_p, "pmkToLeft"),
                  (["in"], POINTER(GUID), "riid"),
                  (["out"], POINTER(c_void_p), "ppvObj")),
    ]


class ICreateDevEnum(IUnknown):
    _iid_ = IID_ICreateDevEnum
    _methods_ = [
        COMMETHOD([], HRESULT, "CreateClassEnumerator",
                  (["in"], POINTER(GUID), "clsidDeviceClass"),
                  (["out"], POINTER(POINTER(IEnumMoniker)), "ppEnum"),
                  (["in"], ULONG, "dwFlags")),
    ]


class IKsControl(IUnknown):
    _iid_ = IID_IKsControl
    _methods_ = [
        COMMETHOD([], HRESULT, "KsProperty",
                  (["in"], POINTER(KSPROPERTY), "Property"),
                  (["in"], ULONG, "PropertyLength"),
                  (["in", "out"], c_void_p, "PropertyData"),
                  (["in"], ULONG, "DataLength"),
                  (["out"], POINTER(ULONG), "BytesReturned")),
        COMMETHOD([], HRESULT, "KsMethod",
                  (["in"], c_void_p, "Method"), (["in"], ULONG, "MethodLength"),
                  (["in", "out"], c_void_p, "MethodData"), (["in"], ULONG, "DataLength"),
                  (["out"], POINTER(ULONG), "BytesReturned")),
        COMMETHOD([], HRESULT, "KsEvent",
                  (["in"], c_void_p, "Event"), (["in"], ULONG, "EventLength"),
                  (["in", "out"], c_void_p, "EventData"), (["in"], ULONG, "DataLength"),
                  (["out"], POINTER(ULONG), "BytesReturned")),
    ]


class IKsTopologyInfo(IUnknown):
    _iid_ = IID_IKsTopologyInfo
    _methods_ = [
        COMMETHOD([], HRESULT, "get_NumCategories", (["out"], POINTER(ULONG), "n")),
        COMMETHOD([], HRESULT, "get_Category",
                  (["in"], ULONG, "index"), (["out"], POINTER(GUID), "cat")),
        COMMETHOD([], HRESULT, "get_NumNodes", (["out"], POINTER(ULONG), "n")),
        COMMETHOD([], HRESULT, "get_NodeType",
                  (["in"], ULONG, "index"), (["out"], POINTER(GUID), "typ")),
        COMMETHOD([], HRESULT, "get_NodeName",
                  (["in"], ULONG, "index"), (["in", "out"], c_void_p, "buf"),
                  (["in"], ULONG, "buflen"), (["out"], POINTER(ULONG), "used")),
        COMMETHOD([], HRESULT, "get_NumConnections", (["out"], POINTER(ULONG), "n")),
        COMMETHOD([], HRESULT, "get_ConnectionInfo",
                  (["in"], ULONG, "index"), (["in", "out"], c_void_p, "info")),
        COMMETHOD([], HRESULT, "CreateNodeInstance",
                  (["in"], ULONG, "index"),
                  (["in"], POINTER(GUID), "iid"),
                  (["out"], POINTER(c_void_p), "ppv")),
    ]


class XUWinError(Exception):
    pass


# ---- Device discovery ------------------------------------------------------

def _match_device_path(path: str, vid: int, pid: int) -> bool:
    return f"vid_{vid:04x}&pid_{pid:04x}" in path.lower()


def _bind_filter(vid: int, pid: int):
    """Return (IBaseFilter-as-IUnknown, device_path) for the first match."""
    dev_enum = CoCreateInstance(CLSID_SystemDeviceEnum, interface=ICreateDevEnum)
    try:
        enum = dev_enum.CreateClassEnumerator(
            byref(CLSID_VideoInputDeviceCategory), 0)
    except TypeError:
        # some comtypes builds return the out-param directly
        enum = POINTER(IEnumMoniker)()
        dev_enum.CreateClassEnumerator(
            byref(CLSID_VideoInputDeviceCategory), byref(enum), 0)
    if not enum:
        raise XUWinError("no video capture devices (CreateClassEnumerator empty)")

    while True:
        fetched = ULONG(0)
        raw = c_void_p()
        hr = enum.Next(1, byref(raw), byref(fetched))
        if hr != 0 or not fetched.value or not raw.value:
            break
        moniker = ctypes.cast(raw, POINTER(IMoniker))

        bag_ptr = moniker.BindToStorage(None, None, byref(IPropertyBag._iid_))
        bag = ctypes.cast(bag_ptr, POINTER(IPropertyBag))
        try:
            path = bag.Read("DevicePath", None)
        except Exception:
            continue
        if not _match_device_path(str(path), vid, pid):
            continue
        obj = moniker.BindToObject(None, None, byref(IID_IBaseFilter))
        base = ctypes.cast(obj, POINTER(IUnknown))
        return base, str(path)

    raise XUWinError(f"camera {vid:04x}:{pid:04x} not found among capture devices")


# ---- Public API ------------------------------------------------------------

class WinXU:
    """Open a UVC device by VID/PID and talk to its extension units."""

    def __init__(self, vid: int, pid: int):
        self.vid, self.pid = vid, pid
        self.device_path = None
        self._topo = None
        self._nodes: dict[str, int] = {}
        self._ksctl: dict[int, IKsControl] = {}

    def open(self):
        comtypes.CoInitialize()
        base, path = _bind_filter(self.vid, self.pid)
        self.device_path = path
        self._topo = base.QueryInterface(IKsTopologyInfo)
        n = ULONG(0)
        self._topo.get_NumNodes(byref(n))
        for i in range(n.value):
            g = GUID()
            self._topo.get_NodeType(i, byref(g))
            self._nodes.setdefault(str(g).lower(), i)
        return self

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        comtypes.CoUninitialize()

    def nodes(self) -> dict:
        return dict(self._nodes)

    def node_for_guid(self, xu_guid: str) -> int:
        key = str(GUID(xu_guid)).lower()
        if key not in self._nodes:
            raise XUWinError(f"extension unit {xu_guid} not in topology; "
                             f"nodes present: {list(self._nodes)}")
        return self._nodes[key]

    def _ks(self, node_id: int) -> IKsControl:
        if node_id not in self._ksctl:
            ppv = c_void_p()
            self._topo.CreateNodeInstance(node_id, byref(IID_IKsControl),
                                          byref(ppv))
            if not ppv.value:
                raise XUWinError(f"CreateNodeInstance failed for node {node_id}")
            self._ksctl[node_id] = ctypes.cast(ppv, POINTER(IKsControl))
        return self._ksctl[node_id]

    def _prop(self, xu_guid, selector, flags, buf, size) -> int:
        node_id = self.node_for_guid(xu_guid)
        ks = self._ks(node_id)
        node = KSP_NODE()
        node.Property.Set = GUID(xu_guid)
        node.Property.Id = selector
        node.Property.Flags = flags | KSPROPERTY_TYPE_TOPOLOGY
        node.NodeId = node_id
        returned = ULONG(0)
        data = ctypes.cast(buf, c_void_p) if buf is not None else None
        ks.KsProperty(ctypes.cast(byref(node), POINTER(KSPROPERTY)),
                      sizeof(node), data, size, byref(returned))
        return returned.value

    def get(self, xu_guid: str, selector: int, size: int) -> bytes:
        buf = (ctypes.c_ubyte * size)()
        got = self._prop(xu_guid, selector, KSPROPERTY_TYPE_GET, buf, size)
        return bytes(buf[:got or size])

    def set(self, xu_guid: str, selector: int, data: bytes) -> None:
        buf = (ctypes.c_ubyte * len(data))(*data)
        self._prop(xu_guid, selector, KSPROPERTY_TYPE_SET, buf, len(data))

    def get_info(self, xu_guid: str) -> bytes:
        buf = (ctypes.c_ubyte * 32)()
        got = self._prop(xu_guid, KSPROPERTY_EXTENSION_UNIT_INFO,
                         KSPROPERTY_TYPE_GET, buf, 32)
        return bytes(buf[:got or 1])

    def probe_size(self, xu_guid, selector,
                   candidates=(1, 2, 4, 8, 16, 32, 34, 64)):
        """Best-effort GET length discovery by trying candidate buffer sizes."""
        for sz in candidates:
            try:
                self.get(xu_guid, selector, sz)
                return sz
            except OSError:
                continue
        return None
