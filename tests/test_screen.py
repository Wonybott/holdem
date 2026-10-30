from dataclasses import replace
from pathlib import Path
import shutil
import cv2
import numpy as np
import pytest
from src.models.state import GameState
from src.capture.sources import Region, MockSource
from src.capture.desktop import DesktopRegionCapture
from src.vision.mock import render,CARD_SLOTS,CARD_W,CARD_H
from src.vision.screen import (ScreenProfile,ScreenRecognizer,TesseractNumbers,encode_sample,
                               CARD_FIELDS)
from src.gui.calibration import CalibrationDialog


def profile_for(state=GameState()):
    image=render(state)
    fields={}
    samples={}
    for i,(x,y) in enumerate(CARD_SLOTS):
        key=f'card{i}'
        fields[key]=Region(x/960,y/640,CARD_W/960,CARD_H/640)
        cards=(*state.hole,*state.board)
        label=cards[i] if i<len(cards) else f'empty:{key}'
        samples[label]=[encode_sample(fields[key].crop(image))]
    fields.update(pot=Region(180/960,250/640,240/960,28/640),
                  to_call=Region(180/960,290/640,240/960,28/640))
    return ScreenProfile(1,{'left':0,'top':0,'width':960,'height':640},Region(),fields,samples,
                         state.opponents,state.stacks,state.position)


class Numbers:
    def __init__(self):
        self.calls=0
    def read(self,image):
        self.calls+=1
        return (120 if self.calls%2 else 20),.99


def test_calibrated_pixel_recognition():
    profile=profile_for()
    result=ScreenRecognizer(profile,Numbers()).analyze(render())
    assert result.state==GameState(),result.errors
    assert min(result.confidence.values())>=.99


def test_unknown_real_card_does_not_reuse_old_card():
    profile=profile_for()
    state=replace(GameState(),hole=('9d','Kh'))
    result=ScreenRecognizer(profile,Numbers()).analyze(render(state))
    assert result.state is None
    assert any('card0' in e for e in result.errors)


def test_low_confidence_numbers_invalidate_entire_state():
    class Uncertain:
        def read(self,image):
            return None,.2
    result=ScreenRecognizer(profile_for(),Uncertain()).analyze(render())
    assert result.state is None
    assert any('OCR' in e for e in result.errors)


def test_profile_round_trip_and_invalid_layout(tmp_path):
    p=profile_for()
    file=tmp_path/'profile.json'
    p.save(file)
    loaded=ScreenProfile.load(file)
    assert loaded==p
    loaded.fields.pop('pot')
    with pytest.raises(ValueError,match='영역'):
        loaded.validate()


def test_pixel_capture_only_selected_physical_area():
    p=profile_for()
    p.table=Region(.1,.2,.5,.5)
    rectangles=[]
    class Session:
        monitors=[{},p.bounds]
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def grab(self,rectangle):
            rectangles.append(rectangle)
            return np.zeros((rectangle['height'],rectangle['width'],4),np.uint8)
    image=DesktopRegionCapture(p,Session).grab()
    assert image.shape==(320,480,3)
    assert rectangles==[{'left':96,'top':128,'width':480,'height':320}]
    p.bounds=dict(p.bounds,width=1920)
    with pytest.raises(RuntimeError,match='변경'):
        DesktopRegionCapture(p,Session).grab()


def test_calibration_uses_exact_selection_and_explicit_label(app):
    d=CalibrationDialog(render(),profile_for().bounds,1,GameState())
    try:
        d.select(Region())
        assert d.table_ready
        d.field.setCurrentIndex(1)
        d.label.setCurrentIndex(d.label.findData('As'))
        x,y=CARD_SLOTS[0]
        d.select(Region(x/960,y/640,CARD_W/960,CARD_H/640))
        assert 'As' in d.profile.samples
        assert 'card0' in d.profile.fields
    finally:
        d.close()


@pytest.mark.skipif(not shutil.which('tesseract'),reason='optional Tesseract not installed')
def test_real_tesseract_number():
    image=np.full((80,300,3),255,np.uint8)
    cv2.putText(image,'1234.50',(10,55),cv2.FONT_HERSHEY_DUPLEX,1.5,(0,0,0),2)
    value,confidence=TesseractNumbers().read(image)
    assert value==1234.5
    assert confidence>=.85


def test_default_period_one_second():
    from src.capture.worker import AnalysisWorker
    worker=AnalysisWorker(MockSource())
    assert worker.interval==1
    worker.configure()
    assert worker.interval==1


def test_numeric_disagreement_is_unknown():
    class Disagree(TesseractNumbers):
        def __init__(self): self.calls=0
        def _read_variant(self,image):
            self.calls+=1
            return (1234.5 if self.calls==1 else 1254.5),.99
    value,confidence=Disagree().read(np.zeros((40,100,3),np.uint8))
    assert value is None


def test_unrelated_clock_pixels_do_not_invalidate_screen_state():
    r=ScreenRecognizer(profile_for(),Numbers())
    a=render(); b=a.copy(); b[600:620,20:100]=255
    assert r.signature(a)==r.signature(b)
    b[115:145,45:65]=128
    assert r.signature(a)!=r.signature(b)


def test_repeated_worker_with_calibrated_screen(app):
    from src.capture.worker import AnalysisWorker
    from PySide6.QtCore import QEventLoop, QTimer
    import time
    def until(app, predicate):
        deadline=time.monotonic()+8
        while not predicate() and time.monotonic()<deadline:
            loop=QEventLoop(); QTimer.singleShot(10,loop.quit); loop.exec()
        assert predicate()
    source=MockSource()
    worker=AnalysisWorker(source)
    results=[]
    worker.configure(100,100,recognizer=ScreenRecognizer(profile_for(),Numbers()))
    worker.analyzed.connect(lambda *args:results.append(args))
    try:
        worker.launch()
        until(app,lambda:bool(results))
        assert results[0][0]==GameState()
    finally:
        worker.stop(); assert worker.wait(3000)
