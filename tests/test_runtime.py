import time
from dataclasses import replace
from PySide6.QtCore import QEventLoop, QTimer
from src.capture.sources import MockSource
from src.capture.worker import AnalysisWorker
from src.gui.window import MainWindow


def until(app, predicate, timeout=8000):
    deadline=time.monotonic()+timeout/1000
    while not predicate() and time.monotonic()<deadline:
        loop=QEventLoop()
        QTimer.singleShot(10,loop.quit)
        loop.exec()
    assert predicate(), 'timed out'


def test_capture_stop_restart_and_change(app):
    source=MockSource()
    w=AnalysisWorker(source)
    outputs=[]
    w.analyzed.connect(lambda *args: outputs.append(args))
    w.configure(100,150)
    try:
        w.launch()
        until(app,lambda: len(outputs)==1)
        w.stop()
        until(app,lambda: not w.isRunning())
        count=len(outputs)
        source.configure(state=replace(source.state,pot=300))
        w.launch()
        until(app,lambda: len(outputs)>count)
        assert outputs[-1][0].pot == 300
    finally:
        w.stop(); assert w.wait(3000)


def test_retry_failed_capture(app):
    class Flaky(MockSource):
        attempts=0
        def grab(self):
            self.attempts+=1
            if self.attempts<3:
                raise RuntimeError('transient failure')
            return super().grab()
    s=Flaky(); w=AnalysisWorker(s); results=[]; statuses=[]
    w.analyzed.connect(lambda *args: results.append(args))
    w.status.connect(statuses.append)
    w.configure(100,100)
    try:
        w.launch()
        until(app,lambda: bool(results))
        assert s.attempts>=4
        assert any('transient failure' in t for t in statuses)
    finally:
        w.stop(); assert w.wait(3000)


def test_gui_responsive_during_real_mc_and_manual(app):
    window=MainWindow()
    ticks=[]
    timer=QTimer(); timer.setInterval(15); timer.timeout.connect(lambda:ticks.append(time.monotonic()))
    window.iterations.setValue(50000)
    window.show()
    try:
        timer.start()
        window.analyze_manual()
        until(app,lambda: '예상 팟 지분' in window.output.toPlainText(),timeout=15000)
        assert len(ticks)>=5
        assert max(b-a for a,b in zip(ticks,ticks[1:]))<.5
        assert '수동 입력' in window.output.toPlainText()
        window.stop_capture()
        assert not window.output.toPlainText()
        until(app,lambda:not window.worker.isRunning())
        window.iterations.setValue(100)
        window.start_capture()
        until(app,lambda:window.result_state is not None,timeout=15000)
        assert not window.manual_mode
    finally:
        timer.stop(); window.worker.stop(); window.worker.wait(3000); window.close()


def test_gui_rejects_old_result(app):
    window=MainWindow()
    try:
        from src.poker.equity import estimate
        s=window.source.state
        result=estimate(s,iterations=10,seed=1)
        old=window.source.revision
        window.source.configure(state=replace(s,pot=200))
        window.on_analyzed(s,result,window.accepted_revision,old)
        assert not window.output.toPlainText()
    finally:
        window.close()


def test_immediate_restart_request(app):
    w=AnalysisWorker(MockSource()); results=[]
    w.analyzed.connect(lambda *args:results.append(args))
    w.configure(100,100)
    try:
        w.launch()
        until(app,lambda: bool(results))
        w.stop(); w.launch()
        until(app,lambda:len(results)>=2)
    finally:
        w.stop(); assert w.wait(3000)


def test_clickthrough_scheduled_recovery_and_stale(app):
    window=MainWindow()
    try:
        from PySide6.QtCore import Qt
        window.passthrough.setChecked(True)
        assert window.pass_timer.isActive()
        assert window.windowFlags() & Qt.WindowType.WindowTransparentForInput
        window.pass_timer.timeout.emit()
        assert not window.passthrough.isChecked()
        assert not window.windowFlags() & Qt.WindowType.WindowTransparentForInput
        window.last_seen=time.monotonic()-20
        window.output.setPlainText('outdated')
        window.check_stale()
        assert not window.output.toPlainText()
        assert '갱신 필요' in window.status_label.text()
    finally:
        window.close()


def test_changed_pixels_during_mc_never_publish_old_result(app):
    from src.vision.mock import render
    class MovingImage(MockSource):
        attempts=0
        def grab(self):
            self.attempts+=1
            state=self.state if self.attempts<=2 else replace(self.state,pot=777)
            return render(state),self.revision
    w=AnalysisWorker(MovingImage()); results=[]
    w.configure(100,100)
    w.analyzed.connect(lambda *args:results.append(args))
    try:
        w.launch()
        until(app,lambda:bool(results))
        assert all(r[0].pot==777 for r in results)
    finally:
        w.stop(); assert w.wait(3000)
