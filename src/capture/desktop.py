"""Explicit user-selected desktop pixels. No website or browser integration."""
import sys
import numpy as np
from PySide6.QtCore import QThread, Signal


def monitor_bounds(session, monitor):
    if not 1 <= monitor < len(session.monitors):
        raise ValueError('선택한 모니터가 없습니다. 모니터 번호를 확인하세요.')
    return dict(session.monitors[monitor])


class DesktopRegionCapture:
    def __init__(self, profile, session_factory=None):
        if session_factory is None:
            if sys.platform != 'win32':
                raise RuntimeError('실제 데스크톱 캡처는 Windows에서 실행하세요.')
            import mss
            session_factory=mss.mss
        self.profile=profile
        self.session_factory=session_factory

    def grab(self):
        p=self.profile
        with self.session_factory() as session:
            bounds=monitor_bounds(session,p.monitor)
            if bounds != p.bounds:
                raise RuntimeError('모니터 위치/해상도/DPI 구성이 변경됐습니다. 실제 화면 영역을 다시 설정하세요.')
            r=p.table
            rectangle={'left':bounds['left']+round(r.x*bounds['width']),
                       'top':bounds['top']+round(r.y*bounds['height']),
                       'width':round(r.width*bounds['width']),
                       'height':round(r.height*bounds['height'])}
            return np.asarray(session.grab(rectangle))[:,:,:3].copy()


class ReferenceCapture(QThread):
    captured=Signal(object,object)
    failed=Signal(str)

    def __init__(self,monitor,parent=None):
        super().__init__(parent)
        self.monitor=monitor

    def run(self):
        try:
            if sys.platform != 'win32':
                raise RuntimeError('실제 화면 캡처는 Windows에서 실행하세요. 파일 이미지는 어느 OS에서나 보정 가능합니다.')
            import mss
            # GUI hides itself before this one-time, explicitly requested capture.
            self.msleep(1500)
            with mss.mss() as session:
                bounds=monitor_bounds(session,self.monitor)
                image=np.asarray(session.grab(bounds))[:,:,:3].copy()
            self.captured.emit(image,bounds)
        except Exception as exc:
            self.failed.emit(str(exc))


class AutomaticMonitorCapture:
    """Capture the explicitly selected monitor; layout is discovered per frame."""
    def __init__(self,monitor=1,session_factory=None):
        if not 1<=monitor<=16:raise ValueError('모니터 번호는 1~16입니다.')
        if session_factory is None:
            if sys.platform!='win32':raise RuntimeError('실제 자동 캡처는 내 Windows PC에서 실행하세요.')
            import mss
            session_factory=mss.mss
        self.monitor,self.session_factory=monitor,session_factory

    def grab(self):
        with self.session_factory() as session:
            bounds=monitor_bounds(session,self.monitor)
            image=np.asarray(session.grab(bounds))[:,:,:3].copy()
            return mask_application_windows(image,bounds)


def mask_application_windows(image,bounds):
    """Ignore this analyzer's own windows, preventing visual feedback loops.

    Windows coordinates are queried inside the capture thread. This neither
    inspects browser internals nor changes another application's windows.
    """
    if sys.platform!='win32':return image
    import ctypes
    from ctypes import wintypes
    import os
    u=ctypes.WinDLL('user32',use_last_error=True)
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    u.EnumWindows.argtypes=[callback_type,wintypes.LPARAM]
    u.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    u.IsWindowVisible.argtypes=[wintypes.HWND]
    u.IsIconic.argtypes=[wintypes.HWND]
    u.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    def visit(hwnd,_):
        pid=wintypes.DWORD();u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value==os.getpid() and u.IsWindowVisible(hwnd) and not u.IsIconic(hwnd):
            rect=wintypes.RECT()
            if u.GetWindowRect(hwnd,ctypes.byref(rect)):
                left=max(0,rect.left-bounds['left']);top=max(0,rect.top-bounds['top'])
                right=min(image.shape[1],rect.right-bounds['left']);bottom=min(image.shape[0],rect.bottom-bounds['top'])
                if right>left and bottom>top:image[top:bottom,left:right]=0
        return True
    callback=callback_type(visit)
    if not u.EnumWindows(callback,0):raise RuntimeError('분석창 영역을 제외하지 못했습니다. 분석을 다시 시작하세요.')
    return image
