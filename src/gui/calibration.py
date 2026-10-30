"""Local screenshot calibration; every label is supplied explicitly by the user."""
from dataclasses import replace
import cv2
from PySide6.QtCore import Qt, Signal, QRect
from PySide6.QtGui import QImage, QPainter, QPen
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QComboBox,QLabel,QPushButton,
                               QMessageBox,QDialogButtonBox,QWidget)
from src.capture.sources import Region
from src.models.state import DECK
from src.vision.screen import ScreenProfile,CARD_FIELDS,encode_sample


class SelectionImage(QWidget):
    selected=Signal(object)

    def __init__(self,image):
        super().__init__()
        self.origin=self.end=None
        self.set_image(image)

    def set_image(self,image):
        self.raw=image.copy()
        h,w=image.shape[:2]
        factor=min(1000/w,520/h,1)
        self.setFixedSize(max(1,round(w*factor)),max(1,round(h*factor)))
        rgb=cv2.cvtColor(image,cv2.COLOR_BGR2RGB)
        self.image=QImage(rgb.data,w,h,rgb.strides[0],QImage.Format.Format_RGB888).copy()
        self.origin=self.end=None
        self.update()

    def paintEvent(self,event):
        p=QPainter(self)
        p.drawImage(self.rect(),self.image)
        if self.origin is not None and self.end is not None:
            p.setPen(QPen(Qt.GlobalColor.yellow,2))
            p.drawRect(QRect(self.origin,self.end).normalized())

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.origin=self.end=event.position().toPoint()
            self.update()

    def mouseMoveEvent(self,event):
        if self.origin is not None:
            self.end=event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self,event):
        if self.origin is None:
            return
        rect=QRect(self.origin,event.position().toPoint()).normalized().intersected(self.rect())
        self.end=event.position().toPoint()
        self.update()
        if rect.width()>3 and rect.height()>3:
            self.selected.emit(Region(rect.x()/self.width(),rect.y()/self.height(),
                                      rect.width()/self.width(),rect.height()/self.height()))


class CalibrationDialog(QDialog):
    def __init__(self,image,bounds,monitor,base,previous=None,parent=None):
        super().__init__(parent)
        self.setWindowTitle('PokerNow 화면 보정 — 픽셀만 사용')
        self.original=image.copy()
        # Reuse known samples, but keep geometry only for the same display bounds.
        same=previous is not None and previous.bounds==bounds
        self.profile=ScreenProfile(monitor,bounds,previous.table if same else Region(),
                                   dict(previous.fields) if same else {},
                                   {k:list(v) for k,v in previous.samples.items()} if previous else {},
                                   base.opponents,base.stacks,base.position)
        self.table_ready=same
        layout=QVBoxLayout(self)
        info=QLabel('① 대상에서 테이블 전체 선택 → 이미지에 드래그\n'
                    '② 홀 카드 2곳·보드 5곳·팟·콜 영역을 각각 선택\n'
                    '카드는 숫자와 무늬가 함께 보이는 동일한 크기의 영역을 지정하세요.\n'
                    '③ 카드 영역을 지정할 때 현재 정답도 선택하면 학습 샘플로 추가됩니다.\n'
                    '알 수 없는 새 카드는 추측하지 않습니다. 이후 보정을 다시 열어 샘플을 추가하세요.')
        info.setWordWrap(True); layout.addWidget(info)
        row=QHBoxLayout()
        self.field=QComboBox()
        self.field.addItem('먼저: 테이블 전체 선택','table')
        for i,key in enumerate(CARD_FIELDS):
            self.field.addItem(f'{"홀 카드" if i<2 else "보드"} {i+1 if i<2 else i-1} ({key})',key)
        self.field.addItem('팟 숫자만 (pot)','pot')
        self.field.addItem('콜 숫자만 (to_call)','to_call')
        for i in range(base.opponents+1):
            self.field.addItem(f'스택 {i} (선택 사항, 0=나)',f'stack{i}')
        row.addWidget(self.field)
        self.label=QComboBox()
        self.label.addItem('정답 선택 (영역만 지정하려면 그대로)','')
        self.label.addItem('보드 빈 칸','--')
        for card in DECK:
            self.label.addItem(card,card)
        row.addWidget(self.label)
        layout.addLayout(row)
        self.preview=SelectionImage(self.profile.table.crop(self.original))
        self.preview.selected.connect(self.select)
        layout.addWidget(self.preview,alignment=Qt.AlignmentFlag.AlignCenter)
        self.summary=QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        clear=QPushButton('카드 샘플 모두 지우기 (잘못 등록한 경우)')
        clear.clicked.connect(self.clear_samples)
        layout.addWidget(clear)
        layout.addWidget(QLabel(f'상대 {base.opponents}명 · 스택 {base.stacks} · 위치 {base.position}: 수동 가정\n'
                               '스택 영역을 생략하면 이 값을 유지합니다. 팟/콜 영역은 숫자만 포함하세요.'))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.update_summary()

    def select(self,region):
        key=self.field.currentData()
        if key=='table':
            old=self.profile.table
            self.profile.table=Region(old.x+region.x*old.width,old.y+region.y*old.height,
                                      region.width*old.width,region.height*old.height)
            self.profile.fields.clear()
            self.preview.set_image(self.profile.table.crop(self.original))
            self.table_ready=True
            self.field.setCurrentIndex(1)
        elif not self.table_ready:
            QMessageBox.warning(self,'테이블 선택','테이블 전체 영역을 먼저 선택하세요.')
        else:
            self.profile.fields[key]=region
            label=self.label.currentData()
            if key in CARD_FIELDS and label:
                if label=='--':
                    if key in CARD_FIELDS[:2]:
                        QMessageBox.warning(self,'정답 오류','홀 카드는 빈 칸으로 지정할 수 없습니다.')
                        return
                    label=f'empty:{key}'
                values=self.profile.samples.setdefault(label,[])
                value=encode_sample(region.crop(self.preview.raw))
                if value not in values:
                    values.append(value)
            self.label.setCurrentIndex(0)
        self.update_summary()

    def clear_samples(self):
        self.profile.samples.clear()
        self.update_summary()

    def update_summary(self):
        fields=', '.join(self.profile.fields) or '(없음)'
        labels=', '.join(self.profile.samples) or '(없음)'
        self.summary.setText(f'지정 영역: {fields}\n등록 카드/빈 칸: {labels}')

    def save(self):
        try:
            self.profile.validate()
            self.accept()
        except ValueError as exc:
            QMessageBox.warning(self,'설정 미완료',str(exc))
