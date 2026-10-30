import random
import sys
import time
from dataclasses import replace
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                               QPushButton, QLabel, QLineEdit, QSpinBox, QCheckBox,
                               QComboBox, QPlainTextEdit, QFileDialog, QMessageBox, QScrollArea, QTabWidget, QGroupBox)
from src.models.state import GameState, DECK, POSITIONS
from src.capture.sources import MockSource, Region, WindowsMockCapture, load_image
from src.capture.worker import AnalysisWorker
from src.capture.desktop import DesktopRegionCapture, ReferenceCapture, AutomaticMonitorCapture
from src.vision.pokernow import PokerNowRecognizer
from src.vision.screen import ScreenProfile, ScreenRecognizer
from src.gui.calibration import CalibrationDialog
from src.gui.mock_window import MockWindow
from src.gui.dashboard import Dashboard
from src.gui.theme import STYLE
from src.gui.mini import MiniWindow
from src.gui.seat_view import SeatView
from src.strategy.scenarios import pot_odds, call_ev, bet_scenarios


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Texas Hold'em Vision Analyzer · 0.5.0")
        self.resize(940, 940)
        self.setMinimumSize(720, 650)
        self.source = MockSource()
        self.mock = MockWindow(self.source.state)
        self.mock.region_selected.connect(self.set_region)
        self.worker = AnalysisWorker(self.source, self)
        self.worker.observed.connect(self.on_observed)
        self.worker.analyzed.connect(self.on_analyzed)
        self.worker.status.connect(self.on_status)
        self.last_seen = 0
        self.last_state = None
        self.result_state = None
        self.manual_mode = False
        self.accepted_revision = 0
        self.closing = False
        self.profile_path = Path(__file__).resolve().parents[2] / '.local' / 'screen-profile.json'
        self.profile = None
        self.reference = None
        self.mini = MiniWindow(self)
        self.mini.restore.connect(self.restore_main)
        self.mini.stop.connect(self.stop_capture)
        self.next_step = 'start'
        self.recognition_errors = []
        self.last_table = None
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        header = QHBoxLayout()
        title = QLabel("HOLD'EM VISION"); title.setObjectName('appTitle')
        header.addWidget(title); header.addStretch()
        self.status_label = QLabel('중지됨 / 갱신 필요')
        self.status_label.setObjectName('statusPill')
        self.status_label.setWordWrap(True); self.status_label.setMaximumWidth(440)
        header.addWidget(self.status_label)
        layout.addLayout(header)
        controls = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(['자체 모의 화면', 'PokerNow 자동 인식 (보정 없음)', '직접 보정 (고급)'])
        self.mode.currentIndexChanged.connect(lambda _: self.stop_capture())
        controls.addWidget(self.mode, 1)
        self.start_button = self.button(controls, '분석 시작 / 재개', self.start_capture)
        self.start_button.setObjectName('primary')
        self.button(controls, '중지', self.stop_capture)
        self.button(controls, '미니 보기', self.show_mini)
        layout.addLayout(controls)
        self.tabs = QTabWidget()
        self.play_page = QScrollArea(); self.play_page.setWidgetResizable(True)
        self.dashboard = Dashboard()
        self.dashboard.next_button.clicked.connect(self.perform_next_step)
        self.play_page.setWidget(self.dashboard)
        self.tabs.addTab(self.play_page, '플레이 보기')
        self.seat_view=SeatView();self.tabs.addTab(self.seat_view,'좌석·베팅')
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(root)

        settings = QWidget(); settings_layout = QVBoxLayout(settings)
        settings_layout.setSpacing(16)
        hint = QLabel('자동 모드는 모니터 번호만 확인하고 위의 분석 시작을 누르세요. 직접 보정은 고급 모드에서만 사용합니다.')
        hint.setWordWrap(True); settings_layout.addWidget(hint)
        screen_group = QGroupBox('1. 화면 입력')
        screen_layout = QVBoxLayout(screen_group)
        auto_hint=QLabel('자동 모드: PokerNow 창을 크게 띄우고 상단에서 분석 시작을 누르세요. 카드 정답·영역 등록이 필요 없습니다.')
        auto_hint.setWordWrap(True); screen_layout.addWidget(auto_hint)
        self.button(screen_layout,'PokerNow 사진 자동 읽기',self.open_auto_image)
        row = QHBoxLayout()
        row.addWidget(QLabel('캡처 모니터 번호'))
        self.monitor = QSpinBox(); self.monitor.setRange(1,16); row.addWidget(self.monitor); row.addStretch()
        screen_layout.addLayout(row)
        optional=QLabel('아래 보정 기능은 직접 보정 (고급) 모드 전용이며, 자동 모드에는 필요하지 않습니다.')
        optional.setWordWrap(True);screen_layout.addWidget(optional)
        self.button(screen_layout, '실제 화면 캡처·보정 (1.5초 뒤)', self.calibrate_live)
        row = QHBoxLayout()
        self.button(row, '스크린샷으로 보정', self.calibrate_file)
        self.button(row, '저장된 보정 불러오기', self.load_profile)
        screen_layout.addLayout(row)
        self.profile_label = QLabel('직접 보정은 선택 사항입니다. 자동 모드는 프로필·영역·정답 등록을 사용하지 않습니다.')
        self.profile_label.setWordWrap(True); screen_layout.addWidget(self.profile_label)
        settings_layout.addWidget(screen_group)
        mock_group = QGroupBox('모의 화면으로 시험하기')
        mock_layout = QVBoxLayout(mock_group)
        row = QHBoxLayout()
        self.button(row, '모의 창', self.show_mock)
        self.button(row, '새 모의 패', self.deal)
        self.button(row, '테스트 이미지 열기', self.open_image)
        mock_layout.addLayout(row)
        row = QHBoxLayout()
        self.button(row, '모의 창 영역 선택', self.select_region)
        self.button(row, '영역 전체로 복원', lambda: self.set_region(Region()))
        mock_layout.addLayout(row)
        self.native = QCheckBox('Windows mss로 자체 모의 창 캡처 (맨 앞에 표시 필요)')
        self.native.setEnabled(sys.platform == 'win32')
        self.native.toggled.connect(lambda _: self.stop_capture())
        mock_layout.addWidget(self.native)
        self.region_label = QLabel('영역: 모의 화면 전체'); self.region_label.setWordWrap(True)
        mock_layout.addWidget(self.region_label)
        settings_layout.addWidget(mock_group)
        analysis_group = QGroupBox('2. 분석 설정')
        form = QFormLayout(analysis_group)
        self.interval = QSpinBox(); self.interval.setRange(100,5000)
        self.interval.setValue(1000); self.interval.setSuffix(' ms')
        form.addRow('캡처 간격 (1000ms = 1초)', self.interval)
        self.iterations = QSpinBox(); self.iterations.setRange(100,50000); self.iterations.setValue(3000)
        form.addRow('시뮬레이션 표본 수', self.iterations)
        self.ranges = QLineEdit('random')
        self.ranges.setPlaceholderText('random 또는 AA,AKs / 상대별 구분 ;')
        form.addRow('상대 범위', self.ranges)
        self.hero_name=QLineEdit();self.hero_name.setPlaceholderText('선택 사항: 여러 공개 카드 쌍이 있으면 입력')
        form.addRow('내 닉네임 (좌석 식별용)',self.hero_name)
        self.button(form, '분석 설정 적용', self.apply_settings)
        settings_layout.addWidget(analysis_group)
        display_group = QGroupBox('표시 옵션')
        display_layout = QVBoxLayout(display_group)
        self.top = QCheckBox('항상 위에 표시'); self.top.toggled.connect(self.toggle_top)
        display_layout.addWidget(self.top)
        self.passthrough = QCheckBox('클릭 통과 (10초 후 자동 해제)')
        self.passthrough.toggled.connect(self.toggle_passthrough); display_layout.addWidget(self.passthrough)
        settings_layout.addWidget(display_group)
        settings_layout.addStretch()
        self.settings_page = self.scroll_page(settings)
        self.tabs.addTab(self.settings_page, '화면 설정')

        manual = QWidget(); manual_layout = QVBoxLayout(manual)
        hint = QLabel('① 마지막 인식값 가져오기 → ② 잘못 읽힌 값 수정 → ③ 수정값 수동 분석\n카드 예시: As Kh / Qs Jh 2c. 스택은 나 먼저, 상대 수+1개 입력하세요.')
        hint.setWordWrap(True); manual_layout.addWidget(hint)
        edits = QFormLayout()
        self.hole = QLineEdit('As Kh'); self.board = QLineEdit('Qs Jh 2c')
        self.pot = QLineEdit('120'); self.call = QLineEdit('20')
        self.stacks = QLineEdit('1000 1000 1000')
        self.opponents = QSpinBox(); self.opponents.setRange(1,9); self.opponents.setValue(2)
        self.position = QComboBox(); self.position.addItems(POSITIONS); self.position.setCurrentText('BTN')
        for text, widget in (('홀 카드',self.hole),('보드 (프리플롭은 비움)',self.board),
                             ('팟 (내 콜 이전, 상대 베팅 포함)',self.pot),('내 유효 콜 금액',self.call),
                             ('스택 (나, 상대 순서)',self.stacks),('상대 수',self.opponents),('포지션',self.position)):
            edits.addRow(text,widget)
        manual_layout.addLayout(edits)
        self.button(manual_layout, '마지막 인식값 가져오기', self.copy_recognized)
        b = self.button(manual_layout, '수정값 수동 분석', self.analyze_manual); b.setObjectName('primary')
        self.button(manual_layout, '수정값을 모의 창에 적용', self.update_mock)
        manual_layout.addStretch()
        self.manual_page = self.scroll_page(manual)
        self.tabs.addTab(self.manual_page, '수동 수정')

        details = QWidget(); detail_layout = QVBoxLayout(details)
        self.confidence_label = QLabel('인식 결과 없음'); self.confidence_label.setWordWrap(True)
        detail_layout.addWidget(self.confidence_label)
        self.output = QPlainTextEdit(); self.output.setReadOnly(True); self.output.setMinimumHeight(220)
        detail_layout.addWidget(self.output, 1)
        self.tabs.addTab(details, '분석 상세')
        self.pass_timer = QTimer(self); self.pass_timer.setSingleShot(True)
        self.pass_timer.timeout.connect(lambda: self.passthrough.setChecked(False))
        self.setStyleSheet(STYLE)
        self.mini.setStyleSheet(STYLE)
        self.invalidate('중지됨 / 갱신 필요')
        self.stale_timer = QTimer(self)
        self.stale_timer.timeout.connect(self.check_stale); self.stale_timer.start(500)

    @staticmethod
    def scroll_page(widget):
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(widget)
        return scroll

    @staticmethod
    def button(layout, text, callback):
        b = QPushButton(text)
        b.clicked.connect(callback)
        if isinstance(layout, QFormLayout):
            layout.addRow(b)
        else:
            layout.addWidget(b)
        return b

    def invalidate(self, message="갱신 필요"):
        self.result_state = None
        self.output.clear()
        self.dashboard.clear()
        if self.last_table is None:self.dashboard.seat_hint.clear()
        self.status_label.setText(message)
        self.next_step = 'settings'
        self.dashboard.next_button.setText('화면 설정 열기')
        self.dashboard.next_button.show()
        if self.last_table is not None and self.last_table.phase=='paused':
            self.dashboard.message('게임 일시정지','방장이 게임을 재개할 때까지 기다리세요. 체크 말풍선은 이전 행동 표시입니다.',badge='일시정지')
            self.dashboard.next_button.hide()
        elif self.last_table is not None and self.last_table.phase=='waiting':
            self.dashboard.message('플레이어 / 딜 대기 중','좌석·베팅 탭에서 앉은 사람과 빈 자리를 확인할 수 있습니다.',badge='대기 중')
            self.dashboard.next_button.hide()
        elif self.is_live() and not self.is_auto() and self.profile is None and not self.manual_mode:
            self.dashboard.message('먼저 화면을 설정하세요',
                                   '화면 설정에서 저장된 보정을 불러오거나, 실제 테이블의 카드·팟·콜 영역을 지정하세요.',
                                   'caution','설정 필요')
        elif 'Tesseract' in message:
            self.dashboard.message('Tesseract 설치를 확인하세요',message,'caution','설정 필요')
        elif '중지' in message:
            self.dashboard.message('분석을 시작하세요',
                                   '분석 시작 / 재개를 누르면 현재 화면을 읽고 검토할 행동과 금액을 표시합니다.',badge='중지됨')
            self.next_step = 'start'; self.dashboard.next_button.setText('분석 시작 / 재개')
        elif '계산' in message or '안정화' in message or '화면 변경' in message or '새 화면' in message:
            self.dashboard.message('새 결과를 기다려 주세요',
                                   '같은 상태를 두 프레임에서 확인하고 계산합니다. 이전 결과는 표시하지 않습니다.',badge='분석 중')
            self.dashboard.next_button.hide()
        elif '최신 화면 없음' in message:
            self.dashboard.message('화면을 다시 확인하세요',
                                   '최신 화면을 읽지 못했습니다. 테이블이 가려지지 않았는지 확인하고 분석을 재개하세요.',
                                   'caution','오래된 결과')
            self.next_step = 'start'; self.dashboard.next_button.setText('분석 다시 시작')
        elif '인식 실패' in message:
            errors='; '.join(self.recognition_errors)
            if self.is_auto():
                self.dashboard.message('자동 인식을 확인하세요',errors or 'PokerNow 창을 크게 띄우고 카드·숫자·행동 버튼이 가려지지 않게 해 주세요.','caution','인식 실패')
                self.dashboard.next_button.setText('모니터·자동 인식 확인')
            elif self.is_live() and 'OCR' in errors:
                self.dashboard.message('숫자 인식 실패',
                                       '화면 설정에서 팟·콜 영역에 숫자만 포함되도록 다시 지정하세요.',
                                       'caution','인식 실패')
            elif self.is_live() and 'card' in errors:
                self.dashboard.message('카드 인식 실패',
                                       '화면 설정에서 현재 보이는 카드의 정답 샘플을 추가하세요.',
                                       'caution','인식 실패')
            else:
                instruction = ('화면 설정에서 카드 샘플과 숫자 영역을 확인하세요. 잘못 읽힌 값은 수동 수정에서 고칠 수 있습니다.'
                               if self.is_live() else '모의 화면 전체가 선택됐는지 확인하세요. 잘린 영역은 화면 설정에서 전체로 복원하세요.')
                self.dashboard.message('화면을 읽지 못했습니다',instruction,'caution','인식 실패')
        else:
            self.dashboard.message('확인이 필요합니다',message,'caution')
        self.mini.clear(self.dashboard.title.text(),self.dashboard.instruction.text())
        if self.last_table is not None and self.last_table.phase=='waiting':
            seats=self.last_table.seats
            self.mini.cards.setText(f'확인된 플레이어 {sum(s.occupied is True for s in seats)}명 / 빈 자리 {sum(s.occupied is False for s in seats)}개')

    def show_mini(self):
        geometry=self.screen().availableGeometry()
        self.mini.move(geometry.left()+8,geometry.top()+round(geometry.height()*.35))
        self.mini.show()
        self.showMinimized()

    def restore_main(self):
        self.mini.hide();self.showNormal();self.raise_();self.activateWindow()

    def perform_next_step(self):
        if self.next_step == 'start':
            self.start_capture()
        else:
            self.tabs.setCurrentWidget(self.settings_page)

    def show_mock(self):
        self.mock.show()
        self.mock.raise_()
        self.mock.activateWindow()

    def settings(self, manual=None):
        recognizer=None
        if manual is None:
            if self.is_auto():recognizer=PokerNowRecognizer(hero_name=self.hero_name.text())
            elif self.is_live() and self.profile is not None:recognizer=ScreenRecognizer(self.profile)
        self.accepted_revision = self.worker.configure(self.interval.value(),self.iterations.value(),
                                                       self.ranges.text(),manual,recognizer)
        self.manual_mode=manual is not None
        self.last_table=None;self.seat_view.set_snapshot(None)
        self.last_seen=0
        self.invalidate('계산 준비 / 갱신 필요')

    def apply_settings(self):
        try:
            self.settings(self.read_manual() if self.manual_mode else None)
        except ValueError as exc:
            self.error(exc)

    def start_capture(self):
        try:
            state, region, image, _, _ = self.source.snapshot()
            native = None
            if self.is_auto():
                native=AutomaticMonitorCapture(self.monitor.value())
                region,image=Region(),None
                self.region_label.setText('선택한 모니터의 PokerNow 테이블·카드·숫자를 자동으로 찾습니다.')
            elif self.is_live():
                if self.profile is None:
                    raise ValueError('실제 화면 캡처·보정 또는 저장된 보정 불러오기를 먼저 실행하세요.')
                native = DesktopRegionCapture(self.profile)
                region, image = Region(), None
                self.region_label.setText('실제 화면: 저장된 테이블 영역만 캡처 (가림/브라우저 크기 변경에 주의)')
            elif self.native.isChecked():
                self.show_mock()
                native = WindowsMockCapture(self.mock)
                image = None
            self.source.configure(region=region, file_image=image, native=native)
            self.settings()
            self.worker.launch()
            self.tabs.setCurrentWidget(self.play_page)
            if self.is_auto():self.show_mini()
        except (ValueError, RuntimeError) as exc:
            self.error(exc)

    def stop_capture(self):
        self.worker.stop()
        self.last_table=None
        self.seat_view.set_snapshot(None)
        self.dashboard.seat_hint.clear()
        self.manual_mode = False
        self.invalidate("중지됨 / 갱신 필요")
        # Never wait synchronously on the UI thread. Restart is available after finish.

    def select_region(self):
        if self.is_live():
            self.error(ValueError('실제 화면 영역은 실제 화면 캡처·보정에서 변경하세요.'))
            return
        self.show_mock()
        self.mock.selecting = True
        self.status_label.setText("모의 창 안에서 드래그하세요. 표식/필드가 잘리면 인식 실패합니다.")

    def set_region(self, region):
        if self.is_live():
            self.error(ValueError('실제 화면 영역은 실제 화면 캡처·보정에서 변경하세요.'))
            return
        _, _, image, native, _ = self.source.snapshot()
        self.source.configure(region=region, file_image=image, native=native)
        self.region_label.setText(f"모의 화면 상대 영역: {region}")
        self.invalidate()

    def open_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "자체 모의 테스트 이미지", "assets", "Images (*.png *.jpg *.bmp)")
        if path:
            try:
                self.mode.setCurrentIndex(0)
                self.source.configure(file_image=load_image(path), region=Region())
                self.native.setChecked(False)
                self.start_capture()
            except (ValueError, OSError) as exc:
                self.error(exc)

    def read_manual(self):
        return GameState(tuple(self.hole.text().split()), tuple(self.board.text().split()),
                         float(self.pot.text()), float(self.call.text()),
                         tuple(float(x) for x in self.stacks.text().split()), self.opponents.value(),
                         self.position.currentText())

    def analyze_manual(self):
        try:
            self.settings(self.read_manual())
            self.worker.launch()
            self.tabs.setCurrentWidget(self.play_page)
        except ValueError as exc:
            self.error(exc)

    def update_mock(self):
        try:
            state = self.read_manual()
            self.mode.setCurrentIndex(0)
            # Validate fixture capacity before changing the source.
            self.mock.set_state(state)
            self.source.configure(state=state, region=Region())
            self.native.setChecked(False)
            self.start_capture()
            self.show_mock()
        except ValueError as exc:
            self.error(exc)

    def deal(self):
        self.mode.setCurrentIndex(0)
        self.native.setChecked(False)
        cards = random.sample(DECK, 7)
        state = replace(self.source.state, hole=tuple(cards[:2]), board=tuple(cards[2:]),
                        pot=random.randrange(50, 501), to_call=random.randrange(0, 51))
        self.source.configure(state=state, region=Region())
        self.mock.set_state(state)
        self.invalidate()
        self.show_mock()

    def copy_recognized(self):
        if self.last_state is None:
            self.error(ValueError("유효한 인식 결과가 없습니다."))
            return
        s = self.last_state
        self.hole.setText(" ".join(s.hole))
        self.board.setText(" ".join(s.board))
        self.pot.setText(str(s.pot))
        self.call.setText(str(s.to_call) if s.to_call is not None else '')
        self.stacks.setText(" ".join(map(str, s.stacks)))
        self.opponents.setValue(s.opponents)
        self.position.setCurrentText(s.position)

    def on_observed(self, observation, source_revision):
        if self.worker.stop_event.is_set() or self.manual_mode or source_revision != self.source.snapshot()[-1]:
            return
        self.last_state = observation.state
        self.last_table=observation.table
        self.seat_view.set_snapshot(observation.table)
        if observation.table is not None:
            seats=observation.table.seats;occupied=[s for s in seats if s.occupied is True]
            betters=[f'{s.name or s.slot_id}: {s.bet:g}' for s in occupied if s.bet is not None]
            self.dashboard.seat_hint.setText(f'확인된 플레이어 {len(occupied)}명 · 현재 베팅 '+(' / '.join(betters[:3]) or '표시 미확인')+' · 상세는 좌석·베팅 탭')
        else:self.dashboard.seat_hint.clear()
        self.last_seen = time.monotonic()
        if observation.state is None:
            self.recognition_errors = observation.errors
            self.invalidate("인식 실패 / 갱신 필요")
            self.confidence_label.setText("; ".join(observation.errors))
        else:
            self.recognition_errors = []
            s = observation.state
            if self.result_state != s:
                self.invalidate("새 화면 안정화 / 갱신 필요")
            fields = " · ".join(f"{k} {v:.0%}" for k, v in observation.confidence.items())
            self.confidence_label.setText(f"템플릿 일치도 (통계적 확률 아님): {fields}")

    def on_status(self, text):
        if self.worker.stop_event.is_set():
            return
        if text.startswith('갱신 필요:'):
            self.last_table=None;self.seat_view.set_snapshot(None)
        self.status_label.setText(text)
        if "갱신 필요" in text or '안정화' in text:
            self.invalidate(text)

    def on_analyzed(self, s, result, revision, source_revision):
        if (self.worker.stop_event.is_set() or revision != self.accepted_revision
                or source_revision != self.source.snapshot()[-1]):
            return
        self.result_state = s
        self.last_seen = time.monotonic()
        call_text=f'{s.to_call:g}' if s.to_call is not None else '확인 필요'
        lines = [f"{'수동 입력' if self.manual_mode else ('자동 화면' if self.is_auto() else '모의/보정 화면')} · {s.street} · 위치 {s.position} · 상대 {s.opponents}",
                 f"홀 {' '.join(s.hole)} | 보드 {' '.join(s.board) or '(없음)'}",
                 f"팟 {s.pot:g} / 콜 {call_text} / 스택 {s.stacks}",
                 f"단독 승리 {result.win:.2%} · 무승부 발생 {result.tie:.2%}",
                 f"예상 팟 지분 {result.equity:.2%} (무승부 분배 포함)",
                 f"MC 표준오차 {result.standard_error:.2%} · {result.samples}회 · 범위 {self.ranges.text()}"]
        if s.to_call is not None:
            lines += [f'팟 오즈 / 콜 손익분기 지분 {pot_odds(s.pot,s.to_call):.2%}',
                      f'추가 베팅 없는 쇼다운 가정 EV {call_ev(result.equity,s.pot,s.to_call):+.2f}']
        else:
            lines.append('콜 금액 미확인: 팟 오즈·행동 EV 계산 보류')
        if s.hero_turn is False:lines.append('상대 차례: 행동 판단 대기')
        elif s.hero_turn is None:lines.append('내 차례 여부 미확인: 행동 판단 보류')
        if s.to_call==0 and s.hero_turn is True:
            for b in bet_scenarios(s.pot,min(s.stacks)):
                lines.append(f'팟 {b.fraction:.0%}: {b.amount:g}칩 / 순수 블러프 손익분기 전체 폴드 {b.pure_bluff_break_even:.1%} / EV 미상')
        lines += ['사이드 팟·레이크·미래 베팅 미반영. 상대 범위 가정에 민감합니다.',
                  '이력은 캡처 이후 관측한 말풍선/표시 베팅입니다. 완전한 게임 로그가 아닙니다.']
        if self.is_live() and not self.is_auto() and not self.manual_mode:
            lines.append('직접 보정 모드의 상대 수·포지션·영역 미지정 스택은 수동 가정입니다.')
        if s.settled_pot is not None:lines.append(f'중앙 팟 {s.settled_pot:g} / 총 팟 {s.pot:g}')
        lines.extend(f'{a.player} · {a.street} · {a.action} · {a.amount:g}' for a in s.history[-12:])
        self.output.setPlainText("\n".join(lines))
        source = '수동 입력' if self.manual_mode else ('자동 인식' if self.is_auto() else ('직접 보정' if self.is_live() else '모의 화면'))
        self.dashboard.show_result(s,result,source,self.ranges.text(),self.is_live() and not self.is_auto() and not self.manual_mode)
        self.mini.show_result(s,result)
        self.status_label.setText("수동 입력 분석 완료" if self.manual_mode else "분석 갱신 완료")

    def check_stale(self):
        threshold = max(2.0, self.interval.value()/1000 * 3)
        if not self.manual_mode and self.last_seen and time.monotonic() - self.last_seen > threshold:
            self.last_table=None;self.seat_view.set_snapshot(None)
            self.invalidate("갱신 필요 (최신 화면 없음)")
        elif self.result_state is not None and not self.manual_mode:
            age=max(0,round(time.monotonic()-self.last_seen))
            self.dashboard.freshness.setText('방금 갱신' if age==0 else f'{age}초 전 확인')

    def is_auto(self):
        return self.mode.currentIndex()==1

    def is_live(self):
        return self.mode.currentIndex()!=0

    def open_auto_image(self):
        path,_=QFileDialog.getOpenFileName(self,'PokerNow 화면 사진 자동 읽기','','Images (*.png *.jpg *.bmp)')
        if path:
            try:
                self.stop_capture()
                self.mode.setCurrentIndex(1)
                self.source.configure(file_image=load_image(path),region=Region())
                self.settings()
                self.worker.launch()
                self.tabs.setCurrentWidget(self.play_page)
            except (ValueError,OSError) as exc:self.error(exc)

    def calibrate_live(self):
        if sys.platform != 'win32':
            self.error(ValueError('실제 화면 캡처는 내 Windows PC에서 실행하세요. 클라우드는 사용자 화면을 볼 수 없습니다.'))
            return
        if self.reference is not None and self.reference.isRunning():
            return
        try:
            self.calibration_base = self.read_manual()
        except ValueError as exc:
            self.error(exc)
            return
        self.stop_capture()
        self.mock.hide()
        self.reference = ReferenceCapture(self.monitor.value(), self)
        self.reference.captured.connect(self.reference_ready)
        self.reference.failed.connect(self.reference_failed)
        self.hide()
        self.reference.start()

    def reference_ready(self, image, bounds):
        if self.closing:
            return
        self.show()
        self.edit_profile(image, bounds, self.calibration_base)

    def reference_failed(self, message):
        if not self.closing:
            self.show()
            self.error(ValueError(message))

    def calibrate_file(self):
        path, _ = QFileDialog.getOpenFileName(self, '실제 화면 전체 PNG 스크린샷', '', 'Images (*.png *.jpg *.bmp)')
        if path:
            try:
                base = self.read_manual()
                self.stop_capture()
                image = load_image(path)
                bounds = {'left':0, 'top':0, 'width':image.shape[1], 'height':image.shape[0]}
                self.edit_profile(image, bounds, base)
            except (ValueError,OSError) as exc:
                self.error(exc)

    def edit_profile(self, image, bounds, base):
        dialog = CalibrationDialog(image,bounds,self.monitor.value(),base,self.profile,self)
        if dialog.exec():
            try:
                dialog.profile.save(self.profile_path)
                self.profile = dialog.profile
                self.mode.setCurrentIndex(2)
                self.profile_label.setText(f'실제 화면 보정 저장됨: {self.profile_path} · 등록 카드/빈칸 {len(self.profile.samples)}종. 새 카드는 추가 보정 필요.')
                self.invalidate('보정 완료. Tesseract를 설치한 뒤 시작을 누르세요.')
            except (ValueError,OSError) as exc:
                self.error(exc)

    def load_profile(self):
        try:
            self.profile = ScreenProfile.load(self.profile_path)
            self.mode.setCurrentIndex(2)
            self.profile_label.setText(f'보정 불러옴: {self.profile_path} · {len(self.profile.samples)}종 카드/빈칸')
        except (ValueError,OSError,TypeError,KeyError) as exc:
            self.error(ValueError(f'보정을 불러오지 못했습니다. 먼저 실제 화면 캡처·보정을 실행하세요. ({exc})'))

    def toggle_top(self, checked):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
        self.show()

    def toggle_passthrough(self, checked):
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, checked)
        self.show()
        if checked:
            self.pass_timer.start(10000)
        else:
            self.pass_timer.stop()

    def error(self, exc):
        self.invalidate(str(exc))
        if 'Tesseract' in str(exc):
            self.dashboard.message('Tesseract 설치를 확인하세요',str(exc),'caution','설정 필요')
        QMessageBox.warning(self, "입력 / 실행 오류", str(exc))

    def closeEvent(self, event):
        self.closing = True
        self.stale_timer.stop()
        self.pass_timer.stop()
        if self.reference is not None and self.reference.isRunning():
            self.reference.finished.connect(self.close, Qt.ConnectionType.SingleShotConnection)
            event.ignore()
        elif self.worker.isRunning():
            self.worker.stop()
            self.worker.finished.connect(self.close, Qt.ConnectionType.SingleShotConnection)
            self.invalidate("작업 정리 중…")
            event.ignore()
        else:
            self.mock.close()
            self.mini.close()
            event.accept()
