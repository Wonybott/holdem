"""Live seat map and per-seat amounts, including empty/unknown places."""
from PySide6.QtCore import Qt,QRectF
from PySide6.QtGui import QPainter,QColor,QPen
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel,QTableWidget,QTableWidgetItem,QHeaderView


class SeatMap(QWidget):
    def __init__(self):
        super().__init__();self.snapshot=None;self.setMinimumHeight(290)
    def set_snapshot(self,snapshot):self.snapshot=snapshot;self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w,h=self.width(),self.height()
        def point(x,y):return ((x+.30)/1.60*w,(y+.38)/1.78*h)
        x,y=point(0,0);x2,y2=point(1,1)
        p.setBrush(QColor('#48215e'));p.setPen(QPen(QColor('#956bb0'),2));p.drawEllipse(QRectF(x,y,x2-x,y2-y))
        p.setPen(QColor('#d9cde5'));p.drawText(QRectF(x,y,x2-x,y2-y),Qt.AlignmentFlag.AlignCenter,'테이블 / 공통 카드')
        if self.snapshot is None:return
        for seat in self.snapshot.seats:
            cx,cy=point(seat.x,seat.y)
            box=QRectF(cx-63,cy-25,126,50)
            color='#126653' if seat.hero else ('#314c64' if seat.occupied is True else '#1c2935')
            p.setBrush(QColor(color));p.setPen(QPen(QColor('#e2c67c' if seat.dealer else '#71869a'),1))
            p.drawRoundedRect(box,6,6)
            label=f'{seat.number}번' if seat.number is not None else seat.slot_id+' (번호?)'
            if seat.dealer:label+=' · D'
            name=seat.name[:9] if seat.occupied is True else ('빈 자리' if seat.occupied is False else '확인 중')
            if seat.hero:name='나 · '+name
            p.setPen(QColor('#eef4fa'));p.drawText(box,Qt.AlignmentFlag.AlignCenter,label+'\n'+name)


class SeatView(QWidget):
    def __init__(self):
        super().__init__();layout=QVBoxLayout(self)
        self.summary=QLabel('좌석을 읽으면 빈 자리와 플레이어를 구분해 표시합니다.')
        self.summary.setWordWrap(True);layout.addWidget(self.summary)
        self.map=SeatMap();layout.addWidget(self.map)
        self.rows=QTableWidget(0,6);self.rows.setHorizontalHeaderLabels(['좌석','플레이어','스택','현재 표시 베팅','최근 말풍선','상태'])
        self.rows.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.rows.verticalHeader().hide();self.rows.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.rows,1)
        note=QLabel('번호?는 실제 좌석 번호를 읽지 못한 위치 ID입니다. —는 미확인이며 0이 아닙니다. 말풍선은 현재 콜 금액의 근거로 사용하지 않습니다.')
        note.setWordWrap(True);layout.addWidget(note)

    def set_snapshot(self,snapshot):
        self.map.set_snapshot(snapshot)
        if snapshot is None:
            self.rows.setRowCount(0);self.summary.setText('최신 좌석 정보 없음');return
        occupied=sum(s.occupied is True for s in snapshot.seats)
        empty=sum(s.occupied is False for s in snapshot.seats)
        phases={'waiting':'플레이어 / 딜 대기','playing':'핸드 진행','paused':'게임 일시정지','observing':'카드·참여자 확인 중'}
        total=f'{snapshot.total_pot:g}' if snapshot.total_pot is not None else '미확인'
        main=f'{snapshot.settled_pot:g}' if snapshot.settled_pot is not None else '미확인'
        self.summary.setText(f'{phases.get(snapshot.phase,snapshot.phase)} · 앉은 사람 {occupied}명 · 확인된 빈 자리 {empty}개\n중앙 팟 {main} / 총 팟 {total} (콜 이전)')
        self.rows.setRowCount(len(snapshot.seats))
        for i,s in enumerate(sorted(snapshot.seats,key=lambda s:(s.number is None,s.number or 0,s.slot_id))):
            status='빈 자리' if s.occupied is False else ('참여 중' if s.in_hand is True else ('폴드' if s.in_hand is False else '확인 중'))
            if s.waiting:status='다음 핸드 대기'
            if s.offline:status+=' · 오프라인'
            if s.hero:status+=' · 나'
            if s.dealer:status+=' · D'
            values=(f'{s.number}번' if s.number is not None else s.slot_id+'(?)',s.name or '—',
                    f'{s.stack:g}' if s.stack is not None else '—',f'{s.bet:g}' if s.bet is not None else '—',s.last_action or '—',status)
            for j,value in enumerate(values):self.rows.setItem(i,j,QTableWidgetItem(value))
