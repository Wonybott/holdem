"""Protocol/validation tests only: no claim of real-model screenshot accuracy."""
from copy import deepcopy
from dataclasses import replace
from threading import Event,Thread
import json
import time
import numpy as np
import pytest
from src.vision.local_ai import LocalAIRecognizer,parse_reading,images_for_model,SCHEMA,PROMPT
from src.vision.stabilizer import Stabilizer
from src.poker.equity import Cancelled


def reading():
    # Manually transcribed facts; this is NOT a response from a running model.
    statuses=['active','active','folded','active','folded','active','folded','active']
    seats=[dict(id=f'p{i}',name=f'player{i}',x=.1+i*.1,y=.5,occupied=True,
                stack=900 if i in (0,3) else 1000,bet={0:100,1:20,3:100,5:10}.get(i),
                status=status,offline=i==1,dealer=i==7) for i,status in enumerate(statuses)]
    return dict(phase='playing',hole=['8s','5s'],board=[],settled_pot=0,total_pot=230,
                call_amount=None,hero_turn=False,hero_id='p0',position='UNKNOWN',seats=seats,uncertain=[])


def response(data):return {'message':{'role':'assistant','content':json.dumps(data)}}


def test_manual_facts_with_three_folds_and_offline_active_seat():
    o=parse_reading(reading())
    assert not o.errors
    assert o.state.hole==('8s','5s')
    assert o.state.opponents==4
    assert o.state.pot==230 and o.state.settled_pot==0
    assert o.state.stacks[0]==900
    assert sum(s.in_hand is False for s in o.state.seats)==3
    assert next(s for s in o.state.seats if s.offline).in_hand is True
    assert o.state.to_call is None


@pytest.mark.parametrize('change',[
    lambda d:d.update(hole=['8s','8s']),
    lambda d:d.update(board=['8s','2d','3c']),
    lambda d:d.update(board=['As','Kd']),
    lambda d:d.update(total_pot=-1),
    lambda d:d.update(total_pot=float('nan')),
    lambda d:d.update(total_pot=True),
    lambda d:d.update(total_pot=0,settled_pot=10),
    lambda d:d.update(hero_turn='true'),
    lambda d:d.update(hero_id='missing'),
    lambda d:d['seats'][1].update(stack=None),
    lambda d:d['seats'][1].update(status='unknown'),
    lambda d:d['seats'][1].update(id='p0'),
    lambda d:d['seats'][1].update(x=4),
    lambda d:d['seats'][1].update(occupied=False,status='active'),
    lambda d:d['seats'][1].update(bet=10000),
])
def test_invalid_model_facts_never_become_equity_input(change):
    data=reading();change(data);o=parse_reading(data)
    assert o.state is None
    assert o.errors


def test_partial_cards_are_retained_when_money_is_unknown():
    data=reading();data['total_pot']=None
    o=parse_reading(data)
    assert o.state is None and o.errors
    assert o.cards.hole==('8s','5s')


def test_paused_overrides_action_and_waiting_has_no_fake_cards():
    data=reading();data.update(phase='paused',hero_turn=True,call_amount=100)
    o=parse_reading(data)
    assert o.state.paused and o.state.hero_turn is None and o.state.to_call is None
    data.update(phase='waiting',hole=None,board=None)
    o=parse_reading(data)
    assert o.state is None and o.cards is None and o.table.phase=='waiting'


def test_prompt_and_payload_use_real_image_without_tesseract(monkeypatch):
    monkeypatch.setattr('src.vision.ocr.TesseractReader.__init__',lambda *_:pytest.fail('OCR should not run'))
    received=[]
    def transport(payload):received.append(payload);return response(reading())
    o=LocalAIRecognizer(transport=transport).analyze(np.zeros((480,640,3),np.uint8))
    assert o.state is not None,o.errors
    assert received[0]['format']==SCHEMA
    assert received[0]['stream'] is False
    assert received[0]['messages'][0]['content']==PROMPT
    assert received[0]['messages'][1]['images'][0].startswith('/9j/')
    assert 'OFFLINE alone does NOT mean folded' in PROMPT


def test_schema_errors_and_non_json_do_not_fall_back_to_cloud():
    for result in ({'error':'missing'}, {'message':{'content':'not JSON'}}):
        r=LocalAIRecognizer(transport=lambda _:result)
        assert r.analyze(np.zeros((480,640,3),np.uint8)).state is None


def test_only_loopback_endpoint_is_used(monkeypatch):
    calls=[]
    class Reply:
        status=200
        def read(self,n):return json.dumps(response(reading())).encode()
    class Connection:
        sock=None
        def __init__(self,*args,**kwargs):calls.append((args,kwargs))
        def request(self,*args):calls.append(args)
        def getresponse(self):return Reply()
        def close(self):pass
    monkeypatch.setattr('src.vision.local_ai.http.client.HTTPConnection',Connection)
    o=LocalAIRecognizer().analyze(np.zeros((480,640,3),np.uint8))
    assert o.state is not None
    assert calls[0][0]==('127.0.0.1',11434)
    assert calls[1][:2]==('POST','/api/chat')


def test_cancel_interrupts_pending_local_request(monkeypatch):
    entered=Event();closed=Event();cancel=Event();results=[]
    class Socket:
        def shutdown(self,*_):closed.set()
    class Connection:
        sock=Socket()
        def __init__(self,*args,**kwargs):pass
        def request(self,*args):pass
        def getresponse(self):
            entered.set();assert closed.wait(2);raise OSError('closed')
        def close(self):closed.set()
    monkeypatch.setattr('src.vision.local_ai.http.client.HTTPConnection',Connection)
    r=LocalAIRecognizer();r.set_cancel(cancel)
    def run():
        try:r.analyze(np.zeros((480,640,3),np.uint8))
        except Cancelled:results.append('cancelled')
    t=Thread(target=run);t.start();assert entered.wait(2)
    cancel.set();r.cancel_pending();t.join(1)
    assert not t.is_alive() and results==['cancelled']


def test_coordinate_jitter_does_not_prevent_semantic_stabilization():
    s=parse_reading(reading()).state
    shifted=replace(s,seats=tuple(replace(seat,x=seat.x+.001) for seat in s.seats))
    stable=Stabilizer()
    assert stable.update(s,key=LocalAIRecognizer.state_key(s)) is None
    assert stable.update(shifted,key=LocalAIRecognizer.state_key(shifted))==shifted
    assert stable.update(replace(s,pot=300),key=LocalAIRecognizer.state_key(replace(s,pot=300))) is None


def test_gui_local_setup_needs_neither_key_nor_tesseract(app,monkeypatch):
    from src.gui.window import MainWindow
    monkeypatch.setattr('src.vision.ocr.TesseractReader.__init__',lambda *_:pytest.fail('OCR should not run'))
    w=MainWindow()
    try:
        w.mode.setCurrentIndex(3);w.settings()
        assert isinstance(w.worker.recognizer,LocalAIRecognizer)
        assert w.is_auto() and w.is_local()
        assert w.worker.interval==5
        assert w.local_model.text()=='qwen2.5vl:7b'
    finally:w.close()


def test_local_request_does_not_block_ui_and_unchanged_photo_is_cached(app):
    from src.capture.sources import MockSource
    from src.capture.worker import AnalysisWorker
    from PySide6.QtCore import QEventLoop,QTimer
    calls=[];results=[];ticks=[]
    def transport(payload):
        calls.append(payload);time.sleep(.25);return response(reading())
    w=AnalysisWorker(MockSource());w.configure(100,100,recognizer=LocalAIRecognizer(transport=transport))
    w.analyzed.connect(lambda *args:results.append(args))
    timer=QTimer();timer.setInterval(20);timer.timeout.connect(lambda:ticks.append(time.monotonic()))
    try:
        timer.start();w.launch();deadline=time.monotonic()+5
        while not results and time.monotonic()<deadline:
            loop=QEventLoop();QTimer.singleShot(20,loop.quit);loop.exec()
        assert results and len(ticks)>5
        assert len(calls)==1
    finally:
        timer.stop();w.stop();assert w.wait(3000)


def test_live_changed_pixels_publish_snapshot_without_current_action(app):
    from src.capture.sources import MockSource
    from src.capture.worker import AnalysisWorker
    from PySide6.QtCore import QEventLoop,QTimer
    class Changing(MockSource):
        count=0
        def grab(self):
            image,revision=super().grab();self.count+=1
            if self.count>=3:image[0,0]=[12,34,56]
            return image,revision
    data=reading();data.update(hero_turn=True,call_amount=50)
    r=LocalAIRecognizer(transport=lambda _:response(data))
    w=AnalysisWorker(Changing());w.configure(100,100,recognizer=r);results=[]
    w.analyzed.connect(lambda *args:results.append(args))
    try:
        w.launch();deadline=time.monotonic()+5
        while not results and time.monotonic()<deadline:
            loop=QEventLoop();QTimer.singleShot(20,loop.quit);loop.exec()
        assert results
        state=results[0][0]
        assert state.hole==('8s','5s')
        assert state.hero_turn is None and state.to_call is None
        assert r.completed_capture_time is not None
    finally:w.stop();assert w.wait(3000)


def test_cloud_models_are_not_accepted_even_through_ollama():
    with pytest.raises(ValueError,match='클라우드'):
        LocalAIRecognizer('some-vision-model:cloud')
