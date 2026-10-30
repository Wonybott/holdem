"""Mock sources and local files. Explicit desktop selection lives in desktop.py."""
from dataclasses import dataclass
from threading import Lock
import sys
import cv2
import numpy as np
from PIL import Image
from src.models.state import GameState
from src.vision.mock import render, WIDTH, HEIGHT


@dataclass(frozen=True)
class Region:
    x: float = 0
    y: float = 0
    width: float = 1
    height: float = 1

    def __post_init__(self):
        if not (0 <= self.x < 1 and 0 <= self.y < 1 and self.width > 0 and self.height > 0
                and self.x + self.width <= 1.00001 and self.y + self.height <= 1.00001):
            raise ValueError("영역은 모의 화면 내부여야 합니다.")

    def crop(self, image):
        h, w = image.shape[:2]
        return image[round(self.y*h):round((self.y+self.height)*h),
                     round(self.x*w):round((self.x+self.width)*w)].copy()


class MockSource:
    def __init__(self):
        self.lock = Lock()
        self.state = GameState()
        self.region = Region()
        self.file_image = None
        self.native = None
        self.revision = 0

    def configure(self, *, state=None, region=None, file_image=None, native=None):
        with self.lock:
            if state is not None:
                self.state = state
            if region is not None:
                self.region = region
            self.file_image = file_image
            self.native = native
            self.revision += 1

    def snapshot(self):
        with self.lock:
            return self.state, self.region, self.file_image, self.native, self.revision

    def grab(self):
        state, region, file_image, native, revision = self.snapshot()
        image = file_image.copy() if file_image is not None else (native.grab() if native else render(state))
        return region.crop(image), revision


def load_image(path):
    with Image.open(path) as image:
        if image.width * image.height > 20_000_000:
            raise ValueError("이미지가 너무 큽니다 (최대 2000만 픽셀).")
        return cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)


class WindowsMockCapture:
    """Only instantiated with the live mock widget owned by this application.

    Resolve client bounds for every frame (DPI/move/resize). Require foreground
    ownership; arbitrary HWNDs, monitor selection and browser capture are absent.
    """
    def __init__(self, mock_widget):
        if sys.platform != "win32":
            raise RuntimeError("mss 실화면 캡처는 Windows에서만 지원합니다.")
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.types = ctypes, wintypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.hwnd = int(mock_widget.winId())
        u = self.user32
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        u.IsWindow.argtypes = [wintypes.HWND]
        u.IsIconic.argtypes = [wintypes.HWND]
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(self.hwnd, ctypes.byref(pid))
        import os
        if pid.value != os.getpid():
            raise RuntimeError("이 앱의 모의 창만 캡처할 수 있습니다.")

    def grab(self):
        import mss
        u, c, t = self.user32, self.ctypes, self.types
        if not u.IsWindow(self.hwnd) or u.IsIconic(self.hwnd) or u.GetForegroundWindow() != self.hwnd:
            raise RuntimeError("모의 창을 복원하고 클릭해 맨 앞으로 가져오세요. 자동 재시도 중입니다.")
        rect, point = t.RECT(), t.POINT(0, 0)
        if not u.GetClientRect(self.hwnd, c.byref(rect)) or not u.ClientToScreen(self.hwnd, c.byref(point)):
            raise RuntimeError("모의 창 크기를 읽지 못했습니다.")
        width, height = rect.right, rect.bottom
        if width < 480 or height < 320:
            raise RuntimeError("모의 창을 더 크게 해 주세요.")
        with mss.mss() as session:
            image = np.asarray(session.grab({"left": point.x, "top": point.y,
                                            "width": width, "height": height}))[:, :, :3].copy()
        if u.GetForegroundWindow() != self.hwnd:
            raise RuntimeError("캡처 중 전경 창이 바뀌었습니다.")
        return image
