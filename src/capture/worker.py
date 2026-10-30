import hashlib
import time
from threading import Event, Lock
from PySide6.QtCore import QThread, Signal
from src.vision.recognizer import MockRecognizer
from src.vision.stabilizer import Stabilizer
from src.poker.equity import Cancelled, estimate, parse_range


class AnalysisWorker(QThread):
    observed = Signal(object, int)
    analyzed = Signal(object, object, int, int)  # state, equity, settings revision
    status = Signal(str)

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.source = source
        self.stop_event = Event()
        self.lock = Lock()
        self.interval = 1.0
        self.iterations = 3000
        self.range_text = "random"
        self.manual = None
        self.recognizer = MockRecognizer()
        self.revision = 0
        self.restart_requested = False
        self.finished.connect(self._restart)

    def configure(self, interval_ms=1000, iterations=3000, range_text="random", manual=None, recognizer=None):
        # Validate synchronously, before invalidating a working calculation.
        texts = range_text.split(";")
        for text in texts:
            parse_range(text)
        with self.lock:
            self.interval = max(.1, min(5.0, interval_ms / 1000))
            self.iterations, self.range_text, self.manual = iterations, range_text, manual
            self.recognizer = recognizer if recognizer is not None else MockRecognizer()
            self.revision += 1
        return self.revision

    def stop(self):
        self.restart_requested = False
        self.stop_event.set()

    def _restart(self):
        if self.restart_requested:
            self.restart_requested = False
            self.launch()

    def launch(self):
        if self.isRunning() and self.stop_event.is_set():
            self.restart_requested = True
        if not self.isRunning():
            self.stop_event.clear()
            self.start()

    def run(self):
        stable = Stabilizer()
        last_key = None
        last_frame_key = None
        cached = None
        equity_cache = {}
        while not self.stop_event.is_set():
            started = time.monotonic()
            with self.lock:
                interval, iterations, range_text, manual, revision, recognizer = (
                    self.interval, self.iterations, self.range_text, self.manual, self.revision, self.recognizer)
            try:
                if manual is None:
                    image, source_revision = self.source.grab()
                    frame_key = (hashlib.sha256(recognizer.signature(image) if hasattr(recognizer, 'signature') else image.tobytes()).digest(), source_revision, revision)
                    if frame_key != last_frame_key or getattr(recognizer,'always_analyze',False):
                        cached = recognizer.analyze(image)
                        frame_key = (hashlib.sha256(recognizer.signature(image) if hasattr(recognizer,'signature') else image.tobytes()).digest(),source_revision,revision)
                        last_frame_key = frame_key
                    self.observed.emit(cached, source_revision)
                    state = stable.update(cached.state)
                    if state is None:
                        last_key = None
                        self.status.emit("인식 실패 / 갱신 필요" if cached.errors else "안정화 중 (2프레임)")
                else:
                    state = manual
                    source_revision = self.source.snapshot()[-1]
                if state is not None:
                    key = (state, revision, source_revision)
                    if key != last_key:
                        self.status.emit("계산 중 / 갱신 필요")
                        texts = range_text.split(";")
                        if len(texts) == 1:
                            texts *= state.opponents
                        if len(texts) != state.opponents:
                            raise ValueError("범위는 하나를 공통 적용하거나 ; 로 상대 수만큼 구분하세요.")
                        equity_key=(state.hole,state.board,state.opponents,tuple(texts),iterations)
                        if equity_key not in equity_cache:
                            result=estimate(state,[parse_range(t) for t in texts],iterations,cancel=self.stop_event)
                            if len(equity_cache)>=16:equity_cache.pop(next(iter(equity_cache)))
                            equity_cache[equity_key]=result
                        result=equity_cache[equity_key]
                        # Pixel sources can change even when settings do not:
                        # verify once more after a long Monte Carlo calculation.
                        current_frame = frame_key if manual is None else None
                        if manual is None:
                            fresh_image, fresh_revision = self.source.grab()
                            current_frame = (hashlib.sha256(recognizer.signature(fresh_image) if hasattr(recognizer, 'signature') else fresh_image.tobytes()).digest(), fresh_revision, revision)
                        pixels_current = manual is not None or current_frame == frame_key
                        if not pixels_current:
                            stable.reset()
                            last_frame_key = None
                            self.status.emit("화면 변경 / 갱신 필요")
                        # A changed source/settings must not publish an old result.
                        if (pixels_current and revision == self.revision
                                and source_revision == self.source.snapshot()[-1]):
                            self.analyzed.emit(state, result, revision, source_revision)
                            last_key = key
                    else:
                        self.status.emit("수동 입력 분석" if manual else "화면 분석 중")
            except Cancelled:
                break
            except Exception as exc:
                stable.reset()
                last_key = last_frame_key = None
                self.status.emit(f"갱신 필요: {exc}")
            # Wait is interruptible. No queued frames, busy loop or overlapping MC jobs.
            self.stop_event.wait(max(.01, interval - (time.monotonic() - started)))
