import cv2
from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget
from src.capture.sources import Region
from src.vision.mock import render, WIDTH, HEIGHT


class MockWindow(QWidget):
    region_selected = Signal(object)

    def __init__(self, state):
        super().__init__()
        self.setWindowTitle("HVA 자체 모의 테이블 — 사이트 캡처 아님")
        self.resize(WIDTH, HEIGHT)
        self.setMinimumSize(480, 320)
        self.selecting = False
        self.origin = self.end = None
        self.set_state(state)

    def set_state(self, state):
        self.state = state
        rgb = cv2.cvtColor(render(state), cv2.COLOR_BGR2RGB)
        self.image = QImage(rgb.data, WIDTH, HEIGHT, rgb.strides[0], QImage.Format.Format_RGB888).copy()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.drawImage(self.rect(), self.image)
        if self.selecting and self.origin is not None and self.end is not None:
            p.setPen(QPen(Qt.GlobalColor.yellow, 2))
            p.drawRect(QRect(self.origin, self.end).normalized())

    def mousePressEvent(self, event):
        if self.selecting and event.button() == Qt.MouseButton.LeftButton:
            self.origin = self.end = event.position().toPoint()
            self.update()

    def mouseMoveEvent(self, event):
        if self.selecting and self.origin is not None:
            self.end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if self.selecting and self.origin is not None:
            r = QRect(self.origin, event.position().toPoint()).normalized().intersected(self.rect())
            self.selecting = False
            self.origin = self.end = None
            self.update()
            if r.width() > 10 and r.height() > 10:
                self.region_selected.emit(Region(r.x()/self.width(), r.y()/self.height(),
                                                 r.width()/self.width(), r.height()/self.height()))
