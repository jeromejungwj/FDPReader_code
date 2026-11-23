"""Precision Touchpad 원시 입력 (Raw Input + HidP).

`python -m features.sign.touchpad_input` 으로 이 PC 의 장치 정보를 확인할 수 있음.
"""

from __future__ import annotations

import ctypes as C
import logging
from ctypes import wintypes as W
from dataclasses import dataclass

from .contacts import Contact, FrameAssembler

log = logging.getLogger(__name__)

WM_INPUT = 0x00FF

_RID_INPUT = 0x10000003
_RIDI_PREPARSEDDATA = 0x20000005
_RIDI_DEVICEINFO = 0x2000000B
_RIM_TYPEHID = 2
_RIDEV_REMOVE = 0x00000001
_HIDP_INPUT = 0
_HIDP_SUCCESS = 0x00110000
_ERROR = 0xFFFFFFFF

PAGE_GENERIC, PAGE_DIGITIZER = 0x01, 0x0D
USAGE_X, USAGE_Y = 0x30, 0x31
USAGE_TOUCHPAD = 0x05
USAGE_TIP, USAGE_CONFIDENCE = 0x42, 0x47
USAGE_CONTACT_ID, USAGE_CONTACT_COUNT = 0x51, 0x54


class _RawDevice(C.Structure):
    _fields_ = [("page", W.USHORT), ("usage", W.USHORT), ("flags", W.DWORD), ("hwnd", W.HWND)]


class _RawDeviceListItem(C.Structure):
    _fields_ = [("handle", W.HANDLE), ("kind", W.DWORD)]


class RawHeader(C.Structure):
    _fields_ = [("kind", W.DWORD), ("size", W.DWORD), ("device", W.HANDLE), ("wparam", W.WPARAM)]


class _HidInfo(C.Structure):
    _fields_ = [
        ("vendor", W.DWORD), ("product", W.DWORD), ("version", W.DWORD),
        ("page", W.USHORT), ("usage", W.USHORT),
    ]


class _DeviceInfoUnion(C.Union):
    _fields_ = [("hid", _HidInfo), ("_size", W.BYTE * 24)]


class _DeviceInfo(C.Structure):
    _fields_ = [("size", W.DWORD), ("kind", W.DWORD), ("u", _DeviceInfoUnion)]


class _Caps(C.Structure):
    _fields_ = [
        ("usage", W.USHORT), ("page", W.USHORT),
        ("input_bytes", W.USHORT), ("output_bytes", W.USHORT), ("feature_bytes", W.USHORT),
        ("reserved", W.USHORT * 17),
        ("link_nodes", W.USHORT),
        ("input_buttons", W.USHORT), ("input_values", W.USHORT), ("input_indices", W.USHORT),
        ("rest", W.USHORT * 6),
    ]


class _ValueCaps(C.Structure):
    _fields_ = [
        ("page", W.USHORT), ("report_id", C.c_ubyte), ("is_alias", C.c_ubyte),
        ("bit_field", W.USHORT), ("link", W.USHORT),
        ("link_usage", W.USHORT), ("link_page", W.USHORT),
        ("is_range", C.c_ubyte), ("is_string_range", C.c_ubyte),
        ("is_designator_range", C.c_ubyte), ("is_absolute", C.c_ubyte),
        ("has_null", C.c_ubyte), ("reserved", C.c_ubyte),
        ("bits", W.USHORT), ("count", W.USHORT), ("reserved2", W.USHORT * 5),
        ("unit_exp", W.ULONG), ("unit", W.ULONG),
        ("log_min", W.LONG), ("log_max", W.LONG),
        ("phys_min", W.LONG), ("phys_max", W.LONG),
        ("usage", W.USHORT), ("usage_max", W.USHORT), ("indices", W.USHORT * 6),
    ]


# 구조체 크기가 틀리면 엉뚱한 좌표를 읽게 되므로 바로 멈춤
assert C.sizeof(_ValueCaps) == 72 and C.sizeof(_Caps) == 64 and C.sizeof(_DeviceInfo) == 32

# 다른 모듈의 ctypes 선언과 섞이지 않도록 전용 핸들을 씀
_user32 = C.WinDLL("user32", use_last_error=True)
_hid = C.WinDLL("hid")


def _declare(dll, name, result, *args):
    func = getattr(dll, name)
    func.restype, func.argtypes = result, args
    return func


_get_list = _declare(
    _user32, "GetRawInputDeviceList", W.UINT, C.c_void_p, C.POINTER(W.UINT), W.UINT
)
_get_info = _declare(
    _user32, "GetRawInputDeviceInfoW", W.UINT, W.HANDLE, W.UINT, C.c_void_p, C.POINTER(W.UINT)
)
_get_data = _declare(
    _user32, "GetRawInputData", W.UINT, W.HANDLE, W.UINT, C.c_void_p, C.POINTER(W.UINT), W.UINT
)
_register = _declare(
    _user32, "RegisterRawInputDevices", W.BOOL, C.POINTER(_RawDevice), W.UINT, W.UINT
)
_get_caps = _declare(_hid, "HidP_GetCaps", W.ULONG, C.c_void_p, C.POINTER(_Caps))
_get_value_caps = _declare(
    _hid, "HidP_GetValueCaps", W.ULONG, C.c_int, C.c_void_p, C.POINTER(W.USHORT), C.c_void_p
)
_get_value = _declare(
    _hid, "HidP_GetUsageValue", W.ULONG,
    C.c_int, W.USHORT, W.USHORT, W.USHORT, C.POINTER(W.ULONG), C.c_void_p, C.c_void_p, W.ULONG,
)
_get_usages = _declare(
    _hid, "HidP_GetUsages", W.ULONG,
    C.c_int, W.USHORT, W.USHORT, C.c_void_p, C.POINTER(W.ULONG), C.c_void_p, C.c_void_p, W.ULONG,
)


def _span(cap: _ValueCaps) -> tuple[int, int]:
    low, high = cap.log_min, cap.log_max
    if high <= low:  # 부호 없는 최댓값을 음수로 보고하는 장치가 있음
        high = (1 << cap.bits) - 1
    return low, high


def _physical(cap: _ValueCaps) -> float:
    exponent = cap.unit_exp & 0xF
    if exponent > 7:
        exponent -= 16
    return (cap.phys_max - cap.phys_min) * 10.0**exponent


@dataclass(frozen=True)
class _Finger:
    link: int
    x: tuple[int, int]
    y: tuple[int, int]


class Device:
    def __init__(self, handle: int):
        self.handle = handle
        size = W.UINT(0)
        _get_info(handle, _RIDI_PREPARSEDDATA, None, C.byref(size))
        if not size.value:
            raise OSError("preparsed data 없음")
        self.preparsed = C.create_string_buffer(size.value)
        if _get_info(handle, _RIDI_PREPARSEDDATA, self.preparsed, C.byref(size)) == _ERROR:
            raise C.WinError(C.get_last_error())

        caps = _Caps()
        if _get_caps(self.preparsed, C.byref(caps)) != _HIDP_SUCCESS:
            raise OSError("HidP_GetCaps 실패")
        self.report_bytes = caps.input_bytes
        n = W.USHORT(caps.input_values)
        values = (_ValueCaps * n.value)()
        if _get_value_caps(_HIDP_INPUT, values, C.byref(n), self.preparsed) != _HIDP_SUCCESS:
            raise OSError("HidP_GetValueCaps 실패")

        xs, ys, with_id = {}, {}, set()
        self.count_link = None
        for cap in values[: n.value]:
            last = cap.usage_max if cap.is_range else cap.usage
            for usage in range(cap.usage, last + 1):
                if (cap.page, usage) == (PAGE_GENERIC, USAGE_X):
                    xs[cap.link] = cap
                elif (cap.page, usage) == (PAGE_GENERIC, USAGE_Y):
                    ys[cap.link] = cap
                elif (cap.page, usage) == (PAGE_DIGITIZER, USAGE_CONTACT_ID):
                    with_id.add(cap.link)
                elif (cap.page, usage) == (PAGE_DIGITIZER, USAGE_CONTACT_COUNT):
                    self.count_link = cap.link
        links = sorted(set(xs) & set(ys) & with_id)
        if not links or self.count_link is None:
            raise OSError("접촉 좌표가 없는 장치")
        self.fingers = [_Finger(link, _span(xs[link]), _span(ys[link])) for link in links]

        width, height = _physical(xs[links[0]]), _physical(ys[links[0]])
        if width <= 0 or height <= 0:  # 물리 크기를 안 알려 주면 논리 범위 비율로 대신함
            width = self.fingers[0].x[1] - self.fingers[0].x[0]
            height = self.fingers[0].y[1] - self.fingers[0].y[0]
        self.aspect = width / height

    def _value(self, report, page: int, usage: int, link: int) -> int | None:
        out = W.ULONG()
        status = _get_value(
            _HIDP_INPUT, page, link, usage, C.byref(out), self.preparsed, report, len(report)
        )
        return out.value if status == _HIDP_SUCCESS else None

    def _pressed(self, report, page: int, link: int) -> list[int]:
        buf = (W.USHORT * 16)()
        n = W.ULONG(len(buf))
        status = _get_usages(
            _HIDP_INPUT, page, link, buf, C.byref(n), self.preparsed, report, len(report)
        )
        return list(buf[: n.value]) if status == _HIDP_SUCCESS else []

    def parse(self, report: bytes) -> tuple[int, list[Contact]] | None:
        """(접촉 수, 손가락 슬롯들). 터치 보고서가 아니면 None."""
        count = self._value(report, PAGE_DIGITIZER, USAGE_CONTACT_COUNT, self.count_link)
        if count is None:
            return None
        contacts = []
        for f in self.fingers:
            x = self._value(report, PAGE_GENERIC, USAGE_X, f.link)
            y = self._value(report, PAGE_GENERIC, USAGE_Y, f.link)
            cid = self._value(report, PAGE_DIGITIZER, USAGE_CONTACT_ID, f.link)
            if x is None or y is None or cid is None:
                break
            flags = self._pressed(report, PAGE_DIGITIZER, f.link)
            contacts.append(
                Contact(
                    cid,
                    min(1.0, max(0.0, (x - f.x[0]) / (f.x[1] - f.x[0]))),
                    min(1.0, max(0.0, (y - f.y[0]) / (f.y[1] - f.y[0]))),
                    USAGE_TIP in flags,
                    USAGE_CONFIDENCE in flags,
                )
            )
        return count, contacts


def find_touchpads() -> list[Device]:
    item = C.sizeof(_RawDeviceListItem)
    n = W.UINT(0)
    _get_list(None, C.byref(n), item)
    if not n.value:
        return []
    items = (_RawDeviceListItem * n.value)()
    got = _get_list(items, C.byref(n), item)
    if got == _ERROR:
        log.warning("입력 장치 목록을 읽지 못함: %s", C.WinError(C.get_last_error()))
        return []

    found = []
    for entry in items[:got]:
        if entry.kind != _RIM_TYPEHID:
            continue
        info = _DeviceInfo(size=C.sizeof(_DeviceInfo))
        size = W.UINT(C.sizeof(info))
        if _get_info(entry.handle, _RIDI_DEVICEINFO, C.byref(info), C.byref(size)) == _ERROR:
            continue
        if (info.u.hid.page, info.u.hid.usage) != (PAGE_DIGITIZER, USAGE_TOUCHPAD):
            continue
        try:
            found.append(Device(entry.handle))
        except OSError:
            log.exception("터치패드 장치를 해석하지 못함")
    return found


class TouchpadInput:
    """창 하나에 터치패드 원시 입력을 연결함. 그 창이 앞에 있을 때만 들어옴."""

    def __init__(self, devices: list[Device]):
        self.devices = {d.handle: d for d in devices}
        self._assemblers = {d.handle: FrameAssembler() for d in devices}
        self._registered = False

    def start(self, hwnd: int) -> None:
        dev = _RawDevice(PAGE_DIGITIZER, USAGE_TOUCHPAD, 0, hwnd)
        if not _register(C.byref(dev), 1, C.sizeof(dev)):
            raise C.WinError(C.get_last_error())
        self._registered = True

    def stop(self) -> None:
        if self._registered:
            dev = _RawDevice(PAGE_DIGITIZER, USAGE_TOUCHPAD, _RIDEV_REMOVE, None)
            _register(C.byref(dev), 1, C.sizeof(dev))
            self._registered = False
        for assembler in self._assemblers.values():
            assembler.reset()

    def read(self, lparam: int) -> list[list[Contact]]:
        """WM_INPUT 하나에서 완성된 접촉 프레임들을 꺼냄."""
        header = C.sizeof(RawHeader)
        size = W.UINT(0)
        if _get_data(lparam, _RID_INPUT, None, C.byref(size), header) == _ERROR or not size.value:
            return []
        buf = C.create_string_buffer(size.value)
        if _get_data(lparam, _RID_INPUT, buf, C.byref(size), header) == _ERROR:
            return []
        return self.decode(buf.raw)

    def decode(self, raw: bytes) -> list[list[Contact]]:
        head = RawHeader.from_buffer_copy(raw)
        device = self.devices.get(head.device)
        if head.kind != _RIM_TYPEHID or device is None:
            return []
        at = C.sizeof(RawHeader)
        length, count = (W.DWORD * 2).from_buffer_copy(raw, at)
        at += 8
        frames = []
        for i in range(count):
            parsed = device.parse(raw[at + i * length : at + (i + 1) * length])
            if parsed is not None:
                frame = self._assemblers[head.device].feed(*parsed)
                if frame is not None:
                    frames.append(frame)
        return frames


if __name__ == "__main__":
    pads = find_touchpads()
    print(f"Precision Touchpad: {len(pads)}")
    for pad in pads:
        print(
            f"  slots={len(pad.fingers)} x={pad.fingers[0].x} y={pad.fingers[0].y} "
            f"aspect={pad.aspect:.3f} report={pad.report_bytes}B"
        )
