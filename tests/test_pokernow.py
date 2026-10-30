"""Self-rendered pixel fixtures plus the actual optional OCR executable.
These tests are not a claim of validation on the attached private screenshot.
"""
from dataclasses import replace
import cv2
import numpy as np
import pytest
from PIL import Image,ImageDraw
from src.models.state import GameState
from src.vision.ocr import Box,Word,TesseractReader
from src.vision.pokernow import PokerNowRecognizer,table_bounds,read_suit,SUITS,number
from src.vision.screen import TesseractNumbers
from src.strategy.guidance import explain_decision
from src.poker.equity import EquityResult,estimate
from src.capture.desktop import AutomaticMonitorCapture
from src.utils.pokernow_fixture import make_scene,font


def has_ocr():
    try:TesseractNumbers();return True
    except ValueError:return False


@pytest.fixture(scope='module')
def automatic():
    if not has_ocr():pytest.skip('optional Tesseract executable unavailable')
    try:font('rank',40)
    except RuntimeError:pytest.skip('synthetic fixture fonts unavailable')
    return PokerNowRecognizer()


@pytest.mark.parametrize('hero_turn,call',[(False,None),(True,0),(True,2000)])
def test_complete_automatic_scene_without_any_profile(automatic,hero_turn,call):
    scene=make_scene(hero_turn=hero_turn,call=call or 0)
    o=automatic.analyze(scene)
    assert o.state is not None,o.errors
    s=o.state
    assert s.hole==('3d','3c')
    assert s.board==('Jc','2c','As','9c','7d')
    assert s.pot==12000
    assert s.stacks==(40510,47490)
    assert s.opponents==1
    assert s.to_call==call
    assert s.hero_turn is hero_turn


@pytest.mark.parametrize('board',[(),('Jc','2c','As'),('Jc','2c','As','9c')])
def test_stage_is_discovered_from_card_layout(automatic,board):
    o=automatic.analyze(make_scene(board=board))
    assert o.state is not None,o.errors
    assert o.state.board==board


@pytest.mark.parametrize('text',list('23456789')+['10','J','Q','K','A'])
def test_all_ranks_have_builtin_ocr_no_samples(automatic,text):
    im=Image.new('L',(150,120));ImageDraw.Draw(im).text((15,8),text,font=font('rank',80),fill=255,anchor='lt')
    mask=np.asarray(im)>127
    ys,xs=np.where(mask);mask=mask[ys.min():ys.max()+1,xs.min():xs.max()+1]
    rank,_=automatic.reader.rank(mask)
    assert rank==('T' if text=='10' else text)


@pytest.mark.parametrize('suit,color',[('s','black'),('h','red'),('d','blue'),('c','green'),('c','black'),('d','red')])
def test_builtin_suits_include_two_and_four_color_decks(suit,color):
    found,score=read_suit(SUITS[suit][0],color)
    assert found==suit
    assert score>.9


def test_color_shape_disagreement_is_unknown():
    assert read_suit(SUITS['d'][0],'green')[0] is None


def test_occluded_card_not_silently_treated_as_shorter_board(automatic):
    scene=make_scene()
    scene[350:529,1320:1455]=255
    o=automatic.analyze(scene)
    assert o.state is None
    assert o.errors


def test_missing_pot_and_missing_enemy_are_not_defaulted(automatic):
    scene=make_scene();scene[230:305,890:1160]=(90,17,65)
    assert automatic.analyze(scene).state is None
    scene=make_scene();scene[637:768,1690:1915]=40
    assert automatic.analyze(scene).state is None


def test_generic_image_is_rejected_before_ocr():
    with pytest.raises(ValueError,match='테이블'):
        table_bounds(np.zeros((800,1200,3),np.uint8))


def test_inactive_preaction_check_does_not_mean_call_zero():
    table=Box(300,100,1200,650);image=np.zeros((1100,2000,3),np.uint8)
    words=[Word(t,.99,Box(x,950,60,25)) for t,x in [('CHECK',1500),('OR',1570),('FOLD',1640)]]
    assert PokerNowRecognizer.read_action(image,words,table,False)[0] is None
    assert PokerNowRecognizer.read_action(image,words,table,True)[0] is None


def test_call_requires_numeric_confirmation():
    table=Box(300,100,1200,650);image=np.zeros((1100,2000,3),np.uint8)
    words=[Word(t,.99,Box(x,1000,60,25)) for t,x in [('CALL',1500),('2000',1570),('FOLD',1800)]]
    assert PokerNowRecognizer.read_action(image,words,table,True,lambda *_:(2001,.99))[0] is None
    assert PokerNowRecognizer.read_action(image,words,table,True,lambda *_:(2000,.99))[0]==2000


def test_unknown_call_and_other_turn_still_allow_equity_but_no_advice():
    state=GameState(to_call=None,hero_turn=False)
    r=estimate(state,iterations=50,seed=12)
    assert 0<=r.equity<=1
    guidance=explain_decision(state,r)
    assert guidance.action=='wait'
    assert guidance.amount==''
    assert explain_decision(replace(state,hero_turn=True),r).action=='unknown'
    assert explain_decision(replace(state,hero_turn=None),r).action=='unknown'


def test_auto_capture_needs_no_region_and_accepts_resolution_changes():
    class Session:
        monitors=[{},dict(left=0,top=0,width=800,height=600)]
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def grab(self,box):return np.zeros((box['height'],box['width'],4),np.uint8)
    capture=AutomaticMonitorCapture(1,Session)
    assert capture.grab().shape==(600,800,3)
    Session.monitors[1]=dict(left=0,top=0,width=1024,height=768)
    assert capture.grab().shape==(768,1024,3)


def test_global_number_parsing_never_guesses_abbreviations():
    assert number('12,000')==12000
    assert number('12k') is None
    assert number('0:14') is None


def test_generated_scene_at_reported_resolution_needs_no_calibration(automatic):
    scene=cv2.resize(make_scene(),(2477,1378),interpolation=cv2.INTER_CUBIC)
    observation=automatic.analyze(scene)
    assert observation.state is not None,observation.errors
    assert observation.state.hole==('3d','3c')
    assert observation.state.board==('Jc','2c','As','9c','7d')
    assert observation.state.pot==12000


def test_names_need_not_be_read_by_english_ocr(automatic):
    class WithoutNames:
        def rank(self,mask):return automatic.reader.rank(mask)
        def words(self,image,*args):
            return [w for w in automatic.reader.words(image,*args) if w.text not in ('player','wonybot')]
    result=PokerNowRecognizer(WithoutNames(),automatic.numbers).analyze(make_scene())
    assert result.state is not None,result.errors
    assert result.state.stacks==(40510,47490)


def test_live_worker_updates_turn_without_manual_regions(app,automatic):
    import time
    from PySide6.QtCore import QEventLoop,QTimer
    from src.capture.sources import MockSource
    from src.capture.worker import AnalysisWorker
    def wait_for(predicate):
        deadline=time.monotonic()+15
        while not predicate() and time.monotonic()<deadline:
            loop=QEventLoop();QTimer.singleShot(15,loop.quit);loop.exec()
        assert predicate()
    source=MockSource();source.configure(file_image=make_scene())
    worker=AnalysisWorker(source);outputs=[]
    worker.configure(100,100,recognizer=automatic)
    worker.analyzed.connect(lambda *args:outputs.append(args))
    try:
        worker.launch();wait_for(lambda:bool(outputs))
        assert outputs[-1][0].hero_turn is False
        assert outputs[-1][0].to_call is None
        first_equity=outputs[-1][1]
        source.configure(file_image=make_scene(hero_turn=True))
        wait_for(lambda:len(outputs)>=2)
        assert outputs[-1][0].hero_turn is True
        assert outputs[-1][0].to_call==0
        assert outputs[-1][1]==first_equity
    finally:
        worker.stop();assert worker.wait(5000)
