"""The play view keeps the next step above all configuration controls."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QFrame,QLabel,QVBoxLayout,QHBoxLayout,QGridLayout,
                               QPushButton,QTableWidget,QTableWidgetItem,QHeaderView)
from src.strategy.guidance import explain_decision
from src.strategy.scenarios import pot_odds,call_ev,bet_scenarios

SUITS={'s':'♠','h':'♥','d':'♦','c':'♣'}


class CardRow(QWidget):
    def __init__(self, caption, count):
        super().__init__()
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        title=QLabel(caption); title.setObjectName('eyebrow'); layout.addWidget(title)
        row=QHBoxLayout(); row.setSpacing(8)
        self.cards=[]
        for _ in range(count):
            label=QLabel('—'); label.setObjectName('playingCard')
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumSize(50,68)
            row.addWidget(label); self.cards.append(label)
        layout.addLayout(row)

    def set_cards(self,cards):
        for i,label in enumerate(self.cards):
            value=cards[i] if i<len(cards) else None
            if value:
                label.setText(f'{value[0]}{SUITS[value[1]]}')
                label.setProperty('cardColor','red' if value[1] in 'hd' else 'black')
            else:
                label.setText('—'); label.setProperty('cardColor','empty')
            label.style().unpolish(label); label.style().polish(label)


class Metric(QFrame):
    def __init__(self,caption):
        super().__init__(); self.setObjectName('metric')
        layout=QVBoxLayout(self)
        self.caption=QLabel(caption); self.caption.setObjectName('eyebrow')
        self.value=QLabel('—'); self.value.setObjectName('metricValue')
        self.detail=QLabel('분석 대기'); self.detail.setWordWrap(True); self.detail.setObjectName('muted')
        layout.addWidget(self.caption); layout.addWidget(self.value); layout.addWidget(self.detail)

    def set(self,value,detail):
        self.value.setText(value); self.detail.setText(detail)


class Dashboard(QWidget):
    def __init__(self):
        super().__init__()
        layout=QVBoxLayout(self); layout.setSpacing(14); layout.setContentsMargins(0,12,0,0)
        self.action_panel=QFrame(); self.action_panel.setObjectName('actionPanel')
        action=QVBoxLayout(self.action_panel); action.setContentsMargins(20,16,20,16)
        heading=QHBoxLayout()
        self.badge=QLabel('시작 전'); self.badge.setObjectName('actionBadge'); heading.addWidget(self.badge)
        heading.addStretch()
        self.freshness=QLabel('결과 없음'); self.freshness.setObjectName('muted'); heading.addWidget(self.freshness)
        action.addLayout(heading)
        self.title=QLabel(); self.title.setObjectName('actionTitle'); self.title.setWordWrap(True)
        self.amount=QLabel(); self.amount.setObjectName('actionAmount'); self.amount.setWordWrap(True)
        self.instruction=QLabel(); self.instruction.setObjectName('actionInstruction'); self.instruction.setWordWrap(True)
        self.assumption=QLabel(); self.assumption.setObjectName('muted'); self.assumption.setWordWrap(True)
        self.next_button=QPushButton('분석 시작'); self.next_button.setObjectName('primary')
        self.next_button.setMinimumHeight(38)
        for widget in (self.title,self.amount,self.instruction,self.assumption,self.next_button):
            action.addWidget(widget)
        layout.addWidget(self.action_panel)
        cards=QHBoxLayout(); cards.setSpacing(24)
        self.hero=CardRow('내 카드',2); self.board=CardRow('공통 카드',5)
        cards.addWidget(self.hero,2); cards.addWidget(self.board,5); layout.addLayout(cards)
        self.context=QLabel('카드와 금액을 읽으면 여기에 표시합니다.'); self.context.setObjectName('muted')
        self.context.setWordWrap(True); layout.addWidget(self.context)
        grid=QGridLayout(); grid.setSpacing(10)
        self.equity=Metric('내 예상 팟 지분')
        self.required=Metric('콜에 필요한 지분')
        self.ev=Metric('콜 EV · 쇼다운 가정')
        for i,metric in enumerate((self.equity,self.required,self.ev)): grid.addWidget(metric,0,i)
        layout.addLayout(grid)
        self.scenario_label=QLabel('베팅 시나리오는 분석 후 표시합니다.'); self.scenario_label.setObjectName('muted')
        self.scenario_label.setWordWrap(True); layout.addWidget(self.scenario_label)
        self.scenarios=QTableWidget(0,3)
        self.scenarios.setHorizontalHeaderLabels(['팟 비율','검토 금액','베팅 EV'])
        self.scenarios.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.scenarios.verticalHeader().hide()
        self.scenarios.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.scenarios.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.scenarios.setMaximumHeight(166)
        self.scenarios.hide(); layout.addWidget(self.scenarios)
        self.note=QLabel('승률과 금액은 입력·인식한 상태에 대한 추정입니다. 최적 행동을 보장하지 않습니다.')
        self.note.setObjectName('muted'); self.note.setWordWrap(True); layout.addWidget(self.note)
        layout.addStretch()
        self.clear()

    def message(self,title,instruction,tone='neutral',badge='갱신 필요',amount='',assumption=''):
        self.title.setText(title); self.instruction.setText(instruction)
        self.amount.setText(amount); self.amount.setVisible(bool(amount))
        self.assumption.setText(assumption); self.assumption.setVisible(bool(assumption))
        self.badge.setText(badge)
        self.action_panel.setProperty('tone',tone)
        self.action_panel.style().unpolish(self.action_panel); self.action_panel.style().polish(self.action_panel)

    def clear(self):
        self.hero.set_cards(()); self.board.set_cards(())
        for metric in (self.equity,self.required,self.ev): metric.set('—','새 분석 대기')
        self.context.setText('유효한 최신 분석이 없습니다.')
        self.freshness.setText('결과 없음')
        self.scenarios.setRowCount(0); self.scenarios.hide()
        self.scenario_label.setText('결과가 준비되면 베팅 시나리오를 표시합니다.')

    def show_result(self,state,result,source,ranges,live_assumptions=False):
        guidance=explain_decision(state,result)
        self.message(guidance.title,guidance.instruction,guidance.tone,'조건부 판단',
                     guidance.amount,guidance.assumption)
        self.next_button.hide()
        self.hero.set_cards(state.hole); self.board.set_cards(state.board)
        streets={'Preflop':'프리플롭','Flop':'플롭','Turn':'턴','River':'리버'}
        self.context.setText(f'{source} · {streets[state.street]} · 상대 {state.opponents}명 · 위치 {state.position}'
                             f' · 팟 {state.pot:g}칩 · 콜 {state.to_call:g}칩 · 내 스택 {state.stacks[0]:g}칩')
        self.equity.set(f'{result.equity:.1%}',f'단독 승리 {result.win:.1%} · 무승부 {result.tie:.1%}')
        self.required.set(f'{pot_odds(state.pot,state.to_call):.1%}',f'콜 비용 {state.to_call:g}칩')
        self.ev.caption.setText('콜 EV · 쇼다운 가정' if state.to_call else '체크 EV · 쇼다운 가정')
        self.ev.set(f'{call_ev(result.equity,state.pot,state.to_call):+.1f}칩',f'상대 범위: {ranges}')
        self.freshness.setText('수동 입력 결과' if source=='수동 입력' else '방금 갱신')
        if state.to_call:
            self.scenario_label.setText('콜이 필요한 상태입니다. 합법 레이즈 최소액을 모르므로 레이즈 금액 판단을 보류합니다.')
            self.scenarios.hide()
        else:
            self.scenario_label.setText('베팅 크기 비교 · 추천 금액 아님 · 상대 폴드 확률이 없어 EV는 미상')
            rows=bet_scenarios(state.pot,min(state.stacks))
            self.scenarios.setRowCount(len(rows))
            for i,row in enumerate(rows):
                for j,value in enumerate((f'{row.fraction:.0%}',f'{row.amount:g}칩','미상')):
                    item=QTableWidgetItem(value); item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.scenarios.setItem(i,j,item)
            self.scenarios.show()
        if live_assumptions:
            self.note.setText('상대 수·위치·영역 미지정 스택은 수동 가정입니다. 바뀌면 화면 설정에서 보정하세요.')
        else:
            self.note.setText('범위와 미래 베팅에 따라 판단은 달라집니다. 사이드 팟·레이크는 반영하지 않습니다.')
