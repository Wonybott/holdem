"""Small read-only window so the analyzer itself need not cover the table."""
from PySide6.QtCore import Qt,Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel,QPushButton,QHBoxLayout
from src.strategy.guidance import explain_decision


class MiniWindow(QWidget):
    restore=Signal()
    stop=Signal()

    def __init__(self,parent):
        super().__init__(None,Qt.WindowType.Window|Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle('Hold’em 실시간 분석')
        self.resize(310,285)
        layout=QVBoxLayout(self)
        self.title=QLabel('자동 인식 대기');self.title.setWordWrap(True)
        self.title.setStyleSheet('font-size:23px;font-weight:700;')
        self.amount=QLabel('');self.amount.setStyleSheet('font-size:21px;font-weight:700;')
        self.cards=QLabel('');self.cards.setWordWrap(True)
        self.metrics=QLabel('');self.metrics.setWordWrap(True)
        self.help=QLabel('PokerNow 창을 크게 표시하세요. 이 창은 드래그해 옮길 수 있습니다.')
        self.help.setWordWrap(True)
        for widget in (self.title,self.amount,self.cards,self.metrics,self.help):layout.addWidget(widget)
        row=QHBoxLayout();full=QPushButton('전체 보기');full.clicked.connect(self.restore.emit)
        stop=QPushButton('중지');stop.clicked.connect(self.stop.emit)
        row.addWidget(full);row.addWidget(stop);layout.addLayout(row)

    def clear(self,title,instruction):
        self.title.setText(title);self.help.setText(instruction)
        self.amount.clear();self.cards.clear();self.metrics.clear()

    def show_result(self,state,result):
        decision=explain_decision(state,result)
        self.title.setText(decision.title);self.amount.setText(decision.amount)
        suits={'s':'♠','h':'♥','d':'♦','c':'♣'}
        pretty=lambda cards:' '.join(c[0]+suits[c[1]] for c in cards)
        self.cards.setText('내 카드 '+pretty(state.hole)+'\n보드 '+(pretty(state.board) or '없음'))
        self.metrics.setText(f'예상 팟 지분 {result.equity:.1%} · 팟 {state.pot:g}칩')
        self.help.setText(decision.assumption)
