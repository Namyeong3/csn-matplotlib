"""The precision touchpad, read directly (Raw Input, HID digitizer "touch pad" 0x0D/0x05) - only to
know when fingers are on it: two or more down is a two-finger scroll going on, fewer is the
fingers lifted (what Windows' wheel messages then carry is its own coasting). A thread of its own
with a hidden message-only window, no Tk. shared() gives the one reader of the app (None where
there's no precision touchpad, or off Windows).

    reader = shared()
    reader.changes   # [(time.perf_counter() when, touching?)] - appended to as it changes
"""
import ctypes
import ctypes.wintypes as w
import os
import threading
import time

HIDP_STATUS_SUCCESS = 0x00110000
WM_INPUT, WM_QUIT = 0x00FF, 0x0012
RIDEV_INPUTSINK, RID_INPUT, RIM_TYPEHID = 0x00000100, 0x10000003, 2
RIDI_DEVICEINFO, RIDI_PREPARSEDDATA = 0x2000000b, 0x20000005


class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [('hDevice', ctypes.c_void_p), ('dwType', w.DWORD)]


class RID_DEVICE_INFO_HID(ctypes.Structure):
    _fields_ = [('dwVendorId', w.DWORD), ('dwProductId', w.DWORD), ('dwVersionNumber', w.DWORD),
                ('usUsagePage', w.USHORT), ('usUsage', w.USHORT)]


class RID_DEVICE_INFO(ctypes.Structure):   # its union is 24 bytes (the keyboard's)
    _fields_ = [('cbSize', w.DWORD), ('dwType', w.DWORD), ('hid', RID_DEVICE_INFO_HID), ('pad', ctypes.c_byte * 8)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [('usUsagePage', w.USHORT), ('usUsage', w.USHORT), ('dwFlags', w.DWORD), ('hwndTarget', w.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [('dwType', w.DWORD), ('dwSize', w.DWORD), ('hDevice', ctypes.c_void_p), ('wParam', w.WPARAM)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [('Usage', w.USHORT), ('UsagePage', w.USHORT), ('InputReportByteLength', w.USHORT),
                ('OutputReportByteLength', w.USHORT), ('FeatureReportByteLength', w.USHORT), ('Reserved', w.USHORT * 17),
                ('NumberLinkCollectionNodes', w.USHORT), ('NumberInputButtonCaps', w.USHORT), ('NumberInputValueCaps', w.USHORT),
                ('NumberInputDataIndices', w.USHORT), ('NumberOutputButtonCaps', w.USHORT), ('NumberOutputValueCaps', w.USHORT),
                ('NumberOutputDataIndices', w.USHORT), ('NumberFeatureButtonCaps', w.USHORT), ('NumberFeatureValueCaps', w.USHORT),
                ('NumberFeatureDataIndices', w.USHORT)]


class HIDP_VALUE_CAPS(ctypes.Structure):
    _fields_ = [('UsagePage', w.USHORT), ('ReportID', ctypes.c_ubyte), ('IsAlias', ctypes.c_ubyte), ('BitField', w.USHORT),
                ('LinkCollection', w.USHORT), ('LinkUsage', w.USHORT), ('LinkUsagePage', w.USHORT), ('IsRange', ctypes.c_ubyte),
                ('IsStringRange', ctypes.c_ubyte), ('IsDesignatorRange', ctypes.c_ubyte), ('IsAbsolute', ctypes.c_ubyte),
                ('HasNull', ctypes.c_ubyte), ('Reserved', ctypes.c_ubyte), ('BitSize', w.USHORT), ('ReportCount', w.USHORT),
                ('Reserved2', w.USHORT * 5), ('UnitsExp', w.ULONG), ('Units', w.ULONG), ('LogicalMin', w.LONG),
                ('LogicalMax', w.LONG), ('PhysicalMin', w.LONG), ('PhysicalMax', w.LONG), ('Usage', w.USHORT),
                ('UsageMax', w.USHORT), ('StringMin', w.USHORT), ('StringMax', w.USHORT), ('DesignatorMin', w.USHORT),
                ('DesignatorMax', w.USHORT), ('DataIndexMin', w.USHORT), ('DataIndexMax', w.USHORT)]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [('style', w.UINT), ('lpfnWndProc', WNDPROC), ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                ('hInstance', w.HINSTANCE), ('hIcon', w.HICON), ('hCursor', ctypes.c_void_p), ('hbrBackground', w.HBRUSH),
                ('lpszMenuName', w.LPCWSTR), ('lpszClassName', w.LPCWSTR)]


class TouchpadReader:
    """Reads the touchpad on a thread of its own; changes: [(when, touching?)] - two fingers or more
    down being touching, as a two-finger scroll needs."""

    def __init__(self):
        self.changes, self.error, self.touching = [], None, False
        self._ready = threading.Event()
        self._pending = None   # a frame coming in several reports ("hybrid" touchpads): (expected, so far)
        self.user32 = ctypes.WinDLL('user32')   # their own: these argument types stay here
        self.kernel32 = ctypes.WinDLL('kernel32')
        self.hid = ctypes.WinDLL('hid')
        u, h = self.user32, self.hid
        u.GetRawInputDeviceInfoW.argtypes = [ctypes.c_void_p, w.UINT, ctypes.c_void_p, ctypes.POINTER(w.UINT)]
        u.GetRawInputData.argtypes = [ctypes.c_void_p, w.UINT, ctypes.c_void_p, ctypes.POINTER(w.UINT), w.UINT]
        u.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        u.DefWindowProcW.restype = ctypes.c_ssize_t
        u.CreateWindowExW.restype = w.HWND
        u.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]
        h.HidP_GetUsageValue.argtypes = [ctypes.c_int, w.USHORT, w.USHORT, w.USHORT, ctypes.POINTER(w.ULONG),
                                         ctypes.c_void_p, ctypes.c_void_p, w.ULONG]
        h.HidP_GetUsages.argtypes = [ctypes.c_int, w.USHORT, w.USHORT, ctypes.POINTER(w.USHORT), ctypes.POINTER(w.ULONG),
                                     ctypes.c_void_p, ctypes.c_void_p, w.ULONG]

    def start(self):
        threading.Thread(target=self._run, daemon=True, name='touchpad').start()
        self._ready.wait(3)
        return self.error is None and getattr(self, 'preparsed', None) is not None

    def stop(self):
        if getattr(self, 'thread_id', None):
            self.user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)

    # ---- the device

    def _find(self):
        u = self.user32
        count = w.UINT()
        u.GetRawInputDeviceList(None, ctypes.byref(count), ctypes.sizeof(RAWINPUTDEVICELIST))
        devices = (RAWINPUTDEVICELIST * count.value)()
        u.GetRawInputDeviceList(devices, ctypes.byref(count), ctypes.sizeof(RAWINPUTDEVICELIST))
        for device in devices:
            if device.dwType != RIM_TYPEHID:
                continue
            info = RID_DEVICE_INFO()
            info.cbSize = ctypes.sizeof(info)
            size = w.UINT(ctypes.sizeof(info))
            u.GetRawInputDeviceInfoW(device.hDevice, RIDI_DEVICEINFO, ctypes.byref(info), ctypes.byref(size))
            if (info.hid.usUsagePage, info.hid.usUsage) == (0x0D, 0x05):
                return device.hDevice
        return None

    def _layout(self, handle):
        """Where its reports hold the fingers (one link collection each) and how many there are."""
        size = w.UINT(0)
        self.user32.GetRawInputDeviceInfoW(handle, RIDI_PREPARSEDDATA, None, ctypes.byref(size))
        self.preparsed = ctypes.create_string_buffer(size.value)
        self.user32.GetRawInputDeviceInfoW(handle, RIDI_PREPARSEDDATA, self.preparsed, ctypes.byref(size))
        caps = HIDP_CAPS()
        self.hid.HidP_GetCaps(self.preparsed, ctypes.byref(caps))
        count = w.USHORT(caps.NumberInputValueCaps)
        values = (HIDP_VALUE_CAPS * max(count.value, 1))()
        self.hid.HidP_GetValueCaps(0, values, ctypes.byref(count), self.preparsed)
        self.slots, self.count_link = [], None
        for value in values[:count.value]:
            if value.UsagePage == 0x01 and value.Usage == 0x30 and value.LinkCollection not in self.slots:   # X: a finger
                self.slots.append(value.LinkCollection)
            if value.UsagePage == 0x0D and value.Usage == 0x54:   # contact count
                self.count_link = value.LinkCollection

    def _contact_count(self, report, length):
        if self.count_link is None:
            return None
        out = w.ULONG()
        status = self.hid.HidP_GetUsageValue(0, 0x0D, self.count_link, 0x54, ctypes.byref(out), self.preparsed, report, length)
        return out.value if status & 0xFFFFFFFF == HIDP_STATUS_SUCCESS else None

    def _down(self, report, length, link):
        usages = (w.USHORT * 16)()
        count = w.ULONG(16)
        status = self.hid.HidP_GetUsages(0, 0x0D, link, usages, ctypes.byref(count), self.preparsed, report, length)
        return status & 0xFFFFFFFF == HIDP_STATUS_SUCCESS and 0x42 in usages[:count.value]   # tip switch

    # ---- the thread

    def _run(self):
        u = self.user32
        try:
            self.thread_id = self.kernel32.GetCurrentThreadId()
            handle = self._find()
            if handle is None:
                self.error = "no precision touchpad"
                return
            self._layout(handle)
            self._proc = WNDPROC(self._procedure)
            window_class = WNDCLASSW()
            window_class.lpfnWndProc = self._proc
            window_class.lpszClassName = f"TouchpadReader{id(self)}"
            window_class.hInstance = self.kernel32.GetModuleHandleW(None)
            u.RegisterClassW(ctypes.byref(window_class))
            hwnd = u.CreateWindowExW(0, window_class.lpszClassName, "touchpad", 0, 0, 0, 0, 0, w.HWND(-3), None,
                                     window_class.hInstance, None)   # HWND_MESSAGE: message-only
            device = RAWINPUTDEVICE(0x0D, 0x05, RIDEV_INPUTSINK, hwnd)
            if not u.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(device)):
                self.error = f"RegisterRawInputDevices failed ({self.kernel32.GetLastError()})"
                return
        except Exception as error:
            self.error = str(error)
            return
        finally:
            self._ready.set()
        msg = w.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))

    def _procedure(self, hwnd, message, wparam, lparam):
        if message == WM_INPUT:
            try:
                self._read(lparam)
            except Exception as error:
                self.error = str(error)
        return self.user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _read(self, handle):
        u = self.user32
        size = w.UINT(0)
        header_size = ctypes.sizeof(RAWINPUTHEADER)
        u.GetRawInputData(handle, RID_INPUT, None, ctypes.byref(size), header_size)
        buffer = ctypes.create_string_buffer(size.value)
        u.GetRawInputData(handle, RID_INPUT, buffer, ctypes.byref(size), header_size)
        if RAWINPUTHEADER.from_buffer(buffer).dwType != RIM_TYPEHID:
            return
        report_size = ctypes.c_uint32.from_buffer(buffer, header_size).value
        reports = ctypes.c_uint32.from_buffer(buffer, header_size + 4).value
        now = time.perf_counter()
        for index in range(reports):
            report = ctypes.cast(ctypes.byref(buffer, header_size + 8 + index * report_size), ctypes.c_void_p)
            count = self._contact_count(report, report_size)
            slots = [self._down(report, report_size, link) for link in self.slots]
            if count:   # a frame begins, saying how many contacts it has (lifting ones too)
                self._pending = (count, [])
            elif self._pending is None:
                if count == 0:
                    self._frame(now, 0)
                continue
            expected, so_far = self._pending
            so_far = so_far + slots[:expected - len(so_far)]
            if len(so_far) >= expected:
                self._frame(now, sum(so_far))
                self._pending = None
            else:
                self._pending = (expected, so_far)

    def _frame(self, now, down):
        touching = down >= 2
        if touching != self.touching:
            self.touching = touching
            self.changes.append((now, touching))


_shared = None


def shared():
    """The app's one touchpad reader - started the first time it's asked for; None without one."""
    global _shared
    if _shared is None:
        reader = TouchpadReader() if os.name == 'nt' else None
        _shared = reader if reader is not None and reader.start() else False
    return _shared or None
