import random
import sys
import time
from dataclasses import replace
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                               QPushButton, QLabel, QLineEdit, QSpinBox, QCheckBox,
                               QComboBox, QPlainTextEdit, QFileDialog, QMessageBox, QScrollArea)
from src.models.state import GameState, DECK, POSITIONS
from src.capture.sources import MockSource, Region, WindowsMockCapture, load_image
from src.capture.worker import AnalysisWorker
from src.capture.desktop import DesktopRegionCapture, ReferenceCapture
from src.vision.screen import ScreenProfile, ScreenRecognizer
from src.gui.calibration import CalibrationDialog
from src.gui.mock_window import MockWindow
from src.strategy.scenarios import pot_odds, call_ev, bet_scenarios


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Texas Hold'em Vision Analyzer")
        self.resize(820, 900)
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
        body = QWidget()
        layout = QVBoxLayout(body)
        banner = QLabel("선택한 화면의 픽셀만 분석 · 자동 클릭/베팅 없음\n승률은 가정한 범위에 대한 추정값이며 확정 행동 추천이 아닙니다.")
        banner.setWordWrap(True)
        layout.addWidget(banner)
        mode_row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(['자체 모의 화면', 'PokerNow / 실제 화면 (보정 필요)'])
        self.mode.currentIndexChanged.connect(lambda _: self.stop_capture())
        mode_row.addWidget(self.mode)
        mode_row.addWidget(QLabel('캡처 모니터 번호'))
        self.monitor = QSpinBox()
        self.monitor.setRange(1,16)
        mode_row.addWidget(self.monitor)
        layout.addLayout(mode_row)
        setup_row = QHBoxLayout()
        self.button(setup_row, '실제 화면 캡처·보정 (1.5초 뒤)', self.calibrate_live)
        self.button(setup_row, '스크린샷으로 보정', self.calibrate_file)
        self.button(setup_row, '저장된 보정 불러오기', self.load_profile)
        layout.addLayout(setup_row)
        self.profile_label = QLabel('실제 화면: 아직 인식 보정이 없습니다. 시작 전 테이블·카드·팟·콜을 지정하세요.')
        self.profile_label.setWordWrap(True)
        layout.addWidget(self.profile_label)
        row = QHBoxLayout()
        self.button(row, "모의 창", self.show_mock)
        self.button(row, "새 모의 패", self.deal)
        self.button(row, "테스트 이미지 열기", self.open_image)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.button(row, "시작 / 캡처 재개", self.start_capture)
        self.button(row, "중지", self.stop_capture)
        self.button(row, "모의 창 영역 선택", self.select_region)
        self.button(row, "영역 전체로 복원", lambda: self.set_region(Region()))
        layout.addLayout(row)
        self.native = QCheckBox("Windows mss로 자체 모의 창 캡처 (맨 앞에 표시 필요)")
        self.native.setEnabled(sys.platform == "win32")
        self.native.toggled.connect(lambda _: self.stop_capture())
        layout.addWidget(self.native)
        self.region_label = QLabel("영역: 모의 화면 전체 (안정적인 인식을 위해 전체 권장)")
        layout.addWidget(self.region_label)
        form = QFormLayout()
        self.interval = QSpinBox()
        self.interval.setRange(100, 5000)
        self.interval.setValue(1000)
        self.interval.setSuffix(" ms")
        form.addRow("캡처 간격", self.interval)
        self.iterations = QSpinBox()
        self.iterations.setRange(100, 50000)
        self.iterations.setValue(3000)
        form.addRow("Monte Carlo 표본 수", self.iterations)
        self.ranges = QLineEdit("random")
        self.ranges.setPlaceholderText("random 또는 AA,AKs / 상대별 구분 ;")
        form.addRow("상대 범위 (공통 또는 ; 구분)", self.ranges)
        self.button(form, "분석 설정 적용", self.apply_settings)
        layout.addLayout(form)
        options = QHBoxLayout()
        self.top = QCheckBox("항상 위")
        self.top.toggled.connect(self.toggle_top)
        options.addWidget(self.top)
        self.passthrough = QCheckBox("클릭 통과 (10초 후 자동 해제)")
        self.passthrough.toggled.connect(self.toggle_passthrough)
        options.addWidget(self.passthrough)
        layout.addLayout(options)
        self.pass_timer = QTimer(self)
        self.pass_timer.setSingleShot(True)
        self.pass_timer.timeout.connect(lambda: self.passthrough.setChecked(False))
        self.status_label = QLabel("중지됨 / 갱신 필요")
        self.confidence_label = QLabel("인식 결과 없음")
        self.confidence_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addWidget(self.confidence_label)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(220)
        layout.addWidget(self.output)
        layout.addWidget(QLabel("인식 결과 수정 / 수동 분석 (자동 캡처 입력 대신 사용)"))
        edits = QFormLayout()
        self.hole = QLineEdit("As Kh")
        self.board = QLineEdit("Qs Jh 2c")
        self.pot = QLineEdit("120")
        self.call = QLineEdit("20")
        self.stacks = QLineEdit("1000 1000 1000")
        self.opponents = QSpinBox()
        self.opponents.setRange(1, 8)
        self.opponents.setValue(2)
        self.position = QComboBox()
        self.position.addItems(POSITIONS)
        self.position.setCurrentText("BTN")
        for text, widget in (("홀 카드", self.hole), ("보드 (프리플롭은 비움)", self.board),
                             ("팟 (내 콜 이전, 상대 베팅 포함)", self.pot), ("내 유효 콜 금액", self.call),
                             ("스택 (나, 상대 순서)", self.stacks), ("상대 수", self.opponents),
                             ("포지션", self.position)):
            edits.addRow(text, widget)
        layout.addLayout(edits)
        row = QHBoxLayout()
        self.button(row, "마지막 인식값 가져오기", self.copy_recognized)
        self.button(row, "수정값 수동 분석", self.analyze_manual)
        self.button(row, "수정값을 모의 창에 적용", self.update_mock)
        layout.addLayout(row)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        self.setCentralWidget(scroll)
        self.setStyleSheet("""
            QWidget { background:#18212b; color:#e5edf5; font-size:13px; }
            QLineEdit, QSpinBox, QComboBox, QPlainTextEdit { background:#0c151f; padding:5px; }
            QPushButton { background:#254358; padding:7px; border-radius:4px; }
            QPushButton:hover { background:#36617d; }
            QPushButton:disabled { color:#728090; }
        """)
        self.stale_timer = QTimer(self)
        self.stale_timer.timeout.connect(self.check_stale)
        self.stale_timer.start(500)

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
        self.status_label.setText(message)

    def show_mock(self):
        self.mock.show()
        self.mock.raise_()
        self.mock.activateWindow()

    def settings(self, manual=None):
        self.accepted_revision = self.worker.configure(self.interval.value(), self.iterations.value(),
                                                       self.ranges.text(), manual,
                                                       ScreenRecognizer(self.profile) if self.is_live() and manual is None
                                                       and self.profile is not None else None)
        self.manual_mode = manual is not None
        self.last_seen = 0
        self.invalidate()

    def apply_settings(self):
        try:
            self.settings(self.read_manual() if self.manual_mode else None)
        except ValueError as exc:
            self.error(exc)

    def start_capture(self):
        try:
            state, region, image, _, _ = self.source.snapshot()
            native = None
            if self.is_live():
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
        except (ValueError, RuntimeError) as exc:
            self.error(exc)

    def stop_capture(self):
        self.worker.stop()
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
        self.call.setText(str(s.to_call))
        self.stacks.setText(" ".join(map(str, s.stacks)))
        self.opponents.setValue(s.opponents)
        self.position.setCurrentText(s.position)

    def on_observed(self, observation, source_revision):
        if self.worker.stop_event.is_set() or self.manual_mode or source_revision != self.source.snapshot()[-1]:
            return
        self.last_state = observation.state
        self.last_seen = time.monotonic()
        if observation.state is None:
            self.invalidate("인식 실패 / 갱신 필요")
            self.confidence_label.setText("; ".join(observation.errors))
        else:
            s = observation.state
            if self.result_state != s:
                self.invalidate("새 화면 안정화 / 갱신 필요")
            fields = " · ".join(f"{k} {v:.0%}" for k, v in observation.confidence.items())
            self.confidence_label.setText(f"템플릿 일치도 (통계적 확률 아님): {fields}")

    def on_status(self, text):
        if self.worker.stop_event.is_set():
            return
        self.status_label.setText(text)
        if "갱신 필요" in text:
            self.result_state = None
            self.output.clear()

    def on_analyzed(self, s, result, revision, source_revision):
        if (self.worker.stop_event.is_set() or revision != self.accepted_revision
                or source_revision != self.source.snapshot()[-1]):
            return
        self.result_state = s
        self.last_seen = time.monotonic()
        lines = [f"{'수동 입력' if self.manual_mode else ('실제 화면' if self.is_live() else '모의 화면')} · {s.street} · 위치 {s.position} · 상대 {s.opponents}",
                 f"홀 {' '.join(s.hole)} | 보드 {' '.join(s.board) or '(없음)'}",
                 f"팟 {s.pot:g} / 콜 {s.to_call:g} / 스택 {s.stacks}",
                 f"단독 승리 {result.win:.2%} · 무승부 발생 {result.tie:.2%}",
                 f"예상 팟 지분 {result.equity:.2%} (무승부 분배 포함)",
                 f"MC 표준오차 {result.standard_error:.2%} · {result.samples}회 · 범위 {self.ranges.text()}",
                 f"팟 오즈 / 콜 손익분기 지분 {pot_odds(s.pot, s.to_call):.2%}",
                 f"추가 베팅 없는 쇼다운 가정 콜 EV {call_ev(result.equity, s.pot, s.to_call):+.2f}",
                 "폴드 EV 0 (현재 결정 이후, 이전 투자 제외)",
                 ("콜 금액 0 → 체크 가능。" if not s.to_call else "콜 또는 폴드 여부 검토 필요. ") + "상대 모델 부재로 행동 확정 추천 보류."]
        if s.to_call:
            lines.append("콜이 필요한 상태: 체크/신규 베팅 시나리오 적용 불가. 레이즈 합법 최소액/이력 미인식.")
        else:
            lines.append("신규 베팅 비교: 상대 유효 스택 한도 적용, 레이즈 추천 아님")
            for b in bet_scenarios(s.pot, min(s.stacks)):
                lines.append(f"팟 {b.fraction:.0%}: {b.amount:g}칩 / 순수 블러프 손익분기 전체 폴드 {b.pure_bluff_break_even:.1%} / EV 미상")
        lines += ["콜 EV는 사이드 팟·레이크·미래 베팅 미반영. 승률 범위 가정에 민감합니다.",
                  "행동/베팅 이력: 인식 미지원. 포지션은 모의 화면/수동 입력값."]
        if self.is_live() and not self.manual_mode:
            lines.append('상대 수·포지션: 보정 시 수동 가정. 스택도 영역 미지정이면 수동 가정. 실제 값이 바뀌면 다시 보정하세요.')
        self.output.setPlainText("\n".join(lines))
        self.status_label.setText("수동 입력 분석 완료" if self.manual_mode else "분석 갱신 완료")

    def check_stale(self):
        threshold = max(2.0, self.interval.value()/1000 * 3)
        if not self.manual_mode and self.last_seen and time.monotonic() - self.last_seen > threshold:
            self.invalidate("갱신 필요 (최신 화면 없음)")

    def is_live(self):
        return self.mode.currentIndex() == 1

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
                self.mode.setCurrentIndex(1)
                self.profile_label.setText(f'실제 화면 보정 저장됨: {self.profile_path} · 등록 카드/빈칸 {len(self.profile.samples)}종. 새 카드는 추가 보정 필요.')
                self.invalidate('보정 완료. Tesseract를 설치한 뒤 시작을 누르세요.')
            except (ValueError,OSError) as exc:
                self.error(exc)

    def load_profile(self):
        try:
            self.profile = ScreenProfile.load(self.profile_path)
            self.mode.setCurrentIndex(1)
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
        QMessageBox.warning(self, "입력 / 실행 오류", str(exc))

    def closeEvent(self, event):
        self.closing = True
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
            event.accept()
