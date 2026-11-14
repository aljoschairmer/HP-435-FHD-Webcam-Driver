"""Windows helper for UVC extension-unit (XU) access via DirectShow IKsControl.

No driver swap: this talks to the in-box usbvideo.sys through the KS property
mechanism the UVC class driver exposes for extension units. An XU control is
addressed by a KSP_NODE whose property Set is the extension unit's GUID, whose
property Id is the UVC control selector, and whose NodeId is the XU's topology
node. Background:
  https://learn.microsoft.com/windows-hardware/drivers/stream/device-requirements-for-usb-video-class-extension-units
  https://learn.microsoft.com/windows-hardware/drivers/stream/extension-unit-plug-in-architecture

Requires:  pip install comtypes   (Python 3.8+, Windows)

All COM interfaces used here are declared locally with their methods as plain
["in"] parameters, so every call returns the raw HRESULT and we manage buffers
and out-pointers by hand. This avoids depending on which helper interfaces a
given comtypes build happens to export.

Read-only by intent: the shipped tools use get()/get_info()/probe_size() and
only set() the read-address selector. Nothing here enters download/write mode.
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER, byref, c_int, c_void_p, c_wchar_p, sizeof
from ctypes.wintypes import ULONG

import comtypes
from comtypes import GUID, COMMETHOD, HRESULT, IUnknown, CoCreateInstance, COMError
from comtypes.automation import VARIANT

# ---- CLSIDs / IIDs ---------------------------------------------------------

CLSID_SystemDeviceEnum = GUID("{62BE5D10-60EB-11D0-BD3B-00A0C911CE86}")
CLSID_VideoInputDeviceCategory = GUID("{860BB310-5D01-11D0-BD3B-00A0C911CE86}")
IID_ICreateDevEnum = GUID("{29840822-5B84-11D0-BD3B-00A0C911CE86}")
IID_IEnumMoniker = GUID("{00000102-0000-0000-C000-000000000046}")
IID_IMoniker = GUID("{0000000F-0000-0000-C000-000000000046}")
IID_IPropertyBag = GUID("{55272A00-42CB-11CE-8135-00AA004BB851}")
IID_IKsControl = GUID("{28F54685-06FD-11D2-B27A-00A0C9223196}")
IID_IKsTopologyInfo = GUID("{720D4AC0-7533-11D0-A5D6-28DB04C10000}")
IID_IBaseFilter = GUID("{56A86895-0AD4-11CE-B03A-0020AF0BA770}")

S_OK = 0

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


# ---- COM interfaces (methods declared ["in"]; we call them manually) -------

class IEnumMoniker(IUnknown):
    _iid_ = IID_IEnumMoniker
    _methods_ = [
        COMMETHOD([], HRESULT, "Next",
                  (["in"], ULONG, "celt"),
                  (["in"], POINTER(c_void_p), "rgelt"),
                  (["in"], POINTER(ULONG), "pceltFetched")),
        COMMETHOD([], HRESULT, "Skip", (["in"], ULONG, "celt")),
        COMMETHOD([], HRESULT, "Reset"),
    ]


class IMoniker(IUnknown):
    # IMoniker : IPersistStream : IPersist : IUnknown.
    # The 5 inherited methods (GetClassID, IsDirty, Load, Save, GetSizeMax) are
    # declared as placeholders so BindToObject/BindToStorage land at the right
    # vtable slots. Only the latter two are ever called.
    _iid_ = IID_IMoniker
    _methods_ = [
        COMMETHOD([], HRESULT, "_GetClassID", (["in"], c_void_p, "p")),
        COMMETHOD([], HRESULT, "_IsDirty"),
        COMMETHOD([], HRESULT, "_Load", (["in"], c_void_p, "p")),
        COMMETHOD([], HRESULT, "_Save", (["in"], c_void_p, "p"), (["in"], c_int, "f")),
        COMMETHOD([], HRESULT, "_GetSizeMax", (["in"], c_void_p, "p")),
        COMMETHOD([], HRESULT, "BindToObject",
                  (["in"], c_void_p, "pbc"),
                  (["in"], c_void_p, "pmkToLeft"),
                  (["in"], POINTER(GUID), "riidResult"),
                  (["in"], POINTER(c_void_p), "ppvResult")),
        COMMETHOD([], HRESULT, "BindToStorage",
                  (["in"], c_void_p, "pbc"),
                  (["in"], c_void_p, "pmkToLeft"),
                  (["in"], POINTER(GUID), "riid"),
                  (["in"], POINTER(c_void_p), "ppvObj")),
    ]


class IPropertyBag(IUnknown):
    _iid_ = IID_IPropertyBag
    _methods_ = [
        COMMETHOD([], HRESULT, "Read",
                  (["in"], c_wchar_p, "pszPropName"),
                  (["in"], POINTER(VARIANT), "pVar"),
                  (["in"], c_void_p, "pErrorLog")),
        COMMETHOD([], HRESULT, "Write",
                  (["in"], c_wchar_p, "pszPropName"),
                  (["in"], POINTER(VARIANT), "pVar")),
    ]


class ICreateDevEnum(IUnknown):
    _iid_ = IID_ICreateDevEnum
    _methods_ = [
        COMMETHOD([], HRESULT, "CreateClassEnumerator",
                  (["in"], POINTER(GUID), "clsidDeviceClass"),
                  (["in"], POINTER(POINTER(IEnumMoniker)), "ppEnum"),
                  (["in"], ULONG, "dwFlags")),
    ]


class IKsControl(IUnknown):
    _iid_ = IID_IKsControl
    _methods_ = [
        COMMETHOD([], HRESULT, "KsProperty",
                  (["in"], POINTER(KSPROPERTY), "Property"),
                  (["in"], ULONG, "PropertyLength"),
                  (["in"], c_void_p, "PropertyData"),
                  (["in"], ULONG, "DataLength"),
                  (["in"], POINTER(ULONG), "BytesReturned")),
        COMMETHOD([], HRESULT, "KsMethod",
                  (["in"], c_void_p, "Method"), (["in"], ULONG, "MethodLength"),
                  (["in"], c_void_p, "MethodData"), (["in"], ULONG, "DataLength"),
                  (["in"], POINTER(ULONG), "BytesReturned")),
        COMMETHOD([], HRESULT, "KsEvent",
                  (["in"], c_void_p, "Event"), (["in"], ULONG, "EventLength"),
                  (["in"], c_void_p, "EventData"), (["in"], ULONG, "DataLength"),
                  (["in"], POINTER(ULONG), "BytesReturned")),
    ]


class IKsTopologyInfo(IUnknown):
    _iid_ = IID_IKsTopologyInfo
    _methods_ = [
        COMMETHOD([], HRESULT, "get_NumCategories", (["in"], POINTER(ULONG), "n")),
        COMMETHOD([], HRESULT, "get_Category",
                  (["in"], ULONG, "index"), (["in"], POINTER(GUID), "cat")),
        COMMETHOD([], HRESULT, "get_NumNodes", (["in"], POINTER(ULONG), "n")),
        COMMETHOD([], HRESULT, "get_NodeType",
                  (["in"], ULONG, "index"), (["in"], POINTER(GUID), "typ")),
        COMMETHOD([], HRESULT, "get_NodeName",
                  (["in"], ULONG, "index"), (["in"], c_void_p, "buf"),
                  (["in"], ULONG, "buflen"), (["in"], POINTER(ULONG), "used")),
        COMMETHOD([], HRESULT, "get_NumConnections", (["in"], POINTER(ULONG), "n")),
        COMMETHOD([], HRESULT, "get_ConnectionInfo",
                  (["in"], ULONG, "index"), (["in"], c_void_p, "info")),
        COMMETHOD([], HRESULT, "CreateNodeInstance",
                  (["in"], ULONG, "index"),
                  (["in"], POINTER(GUID), "iid"),
                  (["in"], POINTER(c_void_p), "ppv")),
    ]


class XUWinError(Exception):
    pass


# Extension units are reported as this node type by conforming UVC drivers.
KSNODETYPE_DEV_SPECIFIC = GUID("{941C7AC0-C559-11D0-8A2B-00A0C9255AC1}")

# HRESULT for "the specified property set is not present in the object": the
# node does not host this extension unit at all. Any other failure means the XU
# property set IS present but that particular selector/length was rejected.
HRESULT_SET_NOT_PRESENT = 0x80070492

# comtypes raises COMError on a failed HRESULT; OSError may surface from ctypes.
PROBE_ERRORS = (COMError, OSError)


def hresult_of(exc) -> int:
    hr = getattr(exc, "hresult", None)
    if hr is None:
        try:
            hr = exc.args[0]
        except Exception:
            hr = -1
    return hr & 0xFFFFFFFF


def _check(hr: int, what: str) -> None:
    if hr is not None and hr < 0:
        raise OSError(hr & 0xFFFFFFFF, f"{what}: HRESULT 0x{hr & 0xFFFFFFFF:08X}")


# ---- Device discovery ------------------------------------------------------

def _match_device_path(path: str, vid: int, pid: int) -> bool:
    return f"vid_{vid:04x}&pid_{pid:04x}" in path.lower()


def _bind_filter(vid: int, pid: int):
    """Return (IKsTopologyInfo, device_path) for the first matching device."""
    dev_enum = CoCreateInstance(CLSID_SystemDeviceEnum, interface=ICreateDevEnum)
    enum = POINTER(IEnumMoniker)()
    hr = dev_enum.CreateClassEnumerator(
        byref(CLSID_VideoInputDeviceCategory), byref(enum), 0)
    _check(hr, "CreateClassEnumerator")
    if not enum:
        raise XUWinError("no video capture devices present")

    while True:
        raw = c_void_p()
        fetched = ULONG(0)
        hr = enum.Next(1, byref(raw), byref(fetched))
        if hr != S_OK or not fetched.value or not raw.value:
            break
        moniker = ctypes.cast(raw, POINTER(IMoniker))

        bag_ptr = c_void_p()
        hr = moniker.BindToStorage(None, None, byref(IID_IPropertyBag),
                                   byref(bag_ptr))
        if hr < 0 or not bag_ptr.value:
            continue
        bag = ctypes.cast(bag_ptr, POINTER(IPropertyBag))
        var = VARIANT()
        if bag.Read("DevicePath", byref(var), None) < 0:
            continue
        path = var.value
        if not path or not _match_device_path(str(path), vid, pid):
            continue

        obj = c_void_p()
        hr = moniker.BindToObject(None, None, byref(IID_IKsTopologyInfo),
                                  byref(obj))
        if hr < 0 or not obj.value:
            # Fall back to IBaseFilter then QI, if direct bind is unsupported.
            obj = c_void_p()
            hr = moniker.BindToObject(None, None, byref(IID_IBaseFilter),
                                      byref(obj))
            _check(hr, "BindToObject(IBaseFilter)")
            base = ctypes.cast(obj, POINTER(IUnknown))
            topo = base.QueryInterface(IKsTopologyInfo)
            return topo, str(path)
        topo = ctypes.cast(obj, POINTER(IKsTopologyInfo))
        return topo, str(path)

    raise XUWinError(f"camera {vid:04x}:{pid:04x} not found among capture devices")


# ---- Public API ------------------------------------------------------------

class WinXU:
    """Open a UVC device by VID/PID and talk to its extension units."""

    def __init__(self, vid: int, pid: int):
        self.vid, self.pid = vid, pid
        self.device_path = None
        self._topo = None
        self._num_nodes = 0
        self._ksctl: dict[int, object] = {}
        self._xu_node: dict[str, int] = {}   # xu guid -> resolved node id

    def open(self):
        comtypes.CoInitialize()
        topo, path = _bind_filter(self.vid, self.pid)
        self.device_path = path
        self._topo = topo
        n = ULONG(0)
        _check(topo.get_NumNodes(byref(n)), "get_NumNodes")
        self._num_nodes = n.value
        return self

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        comtypes.CoUninitialize()

    @property
    def num_nodes(self) -> int:
        return self._num_nodes

    def query(self, interface):
        """QueryInterface on the capture filter object (e.g. IAMVideoProcAmp)."""
        return self._topo.QueryInterface(interface)

    def node_type(self, node_id: int) -> str:
        """Diagnostic: the driver-reported node-type GUID (may be unreliable)."""
        g = GUID()
        if self._topo.get_NodeType(node_id, byref(g)) < 0:
            return "<error>"
        return str(g)

    def _ks(self, node_id: int):
        if node_id not in self._ksctl:
            ppv = c_void_p()
            _check(self._topo.CreateNodeInstance(node_id, byref(IID_IKsControl),
                                                 byref(ppv)),
                   f"CreateNodeInstance(node {node_id})")
            if not ppv.value:
                raise XUWinError(f"CreateNodeInstance returned null for node {node_id}")
            self._ksctl[node_id] = ctypes.cast(ppv, POINTER(IKsControl))
        return self._ksctl[node_id]

    def _prop_on(self, node_id, xu_guid, selector, flags, buf, size) -> int:
        ks = self._ks(node_id)
        node = KSP_NODE()
        node.Property.Set = GUID(xu_guid)
        node.Property.Id = selector
        node.Property.Flags = flags | KSPROPERTY_TYPE_TOPOLOGY
        node.NodeId = node_id
        returned = ULONG(0)
        data = ctypes.cast(buf, c_void_p) if buf is not None else None
        hr = ks.KsProperty(ctypes.cast(byref(node), POINTER(KSPROPERTY)),
                           sizeof(node), data, size, byref(returned))
        _check(hr, f"KsProperty node={node_id} sel=0x{selector:02x}")
        return returned.value

    def supporting_nodes(self, xu_guid: str) -> list:
        """Node ids whose KS object hosts this extension unit's property set.

        Tries EXTENSION_UNIT_INFO (property id 0) on every node. A node that
        does not host this XU fails with HRESULT_SET_NOT_PRESENT; any other
        outcome (success, or a different error such as the selector being
        unsupported) means the property set is present on that node. This is
        more robust than matching get_NodeType, which some drivers report
        unreliably.
        """
        found = []
        for node_id in range(self._num_nodes):
            buf = (ctypes.c_ubyte * 32)()
            try:
                self._prop_on(node_id, xu_guid, KSPROPERTY_EXTENSION_UNIT_INFO,
                              KSPROPERTY_TYPE_GET, buf, 32)
                found.append(node_id)
            except PROBE_ERRORS as e:
                if hresult_of(e) != HRESULT_SET_NOT_PRESENT:
                    found.append(node_id)  # set present, id 0 just not readable
        return found

    def node_for_guid(self, xu_guid: str) -> int:
        key = str(GUID(xu_guid)).lower()
        if key in self._xu_node:
            return self._xu_node[key]
        nodes = self.supporting_nodes(xu_guid)
        if not nodes:
            raise XUWinError(
                f"no topology node accepts extension unit {xu_guid} "
                f"(checked nodes 0..{self._num_nodes - 1})")
        self._xu_node[key] = nodes[0]
        return nodes[0]

    def _prop(self, xu_guid, selector, flags, buf, size) -> int:
        return self._prop_on(self.node_for_guid(xu_guid), xu_guid,
                             selector, flags, buf, size)

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
            except PROBE_ERRORS:
                continue
        return None
