from dataclasses import replace
import cv2
import numpy as np
import pytest
from src.models.state import GameState, DECK
from src.vision.mock import render, CARD_SLOTS
from src.vision.recognizer import MockRecognizer
from src.vision.stabilizer import Stabilizer
from src.capture.sources import load_image, Region, MockSource


@pytest.mark.parametrize('count', [0,3,4,5])
def test_read_full_state(count):
    s=GameState(("As","Kh"), ("Qs","Jh","2c","3d","4s")[:count],
                pot=1024.5, to_call=2.5, stacks=(999.5,2000,3000), position='UNKNOWN')
    o=MockRecognizer().analyze(render(s))
    assert not o.errors
    assert o.state == s
    assert min(o.confidence.values()) > .99


def test_all_cards_and_positions():
    for i in range(0,52,2):
        s=GameState(tuple(DECK[i:i+2]), (), stacks=(100,200), opponents=1)
        o=MockRecognizer().analyze(render(s))
        assert o.state == s, o.errors


def test_fixture_file():
    assert MockRecognizer().analyze(load_image('assets/mock_flop.png')).state == GameState()


@pytest.mark.parametrize('image', [None, np.zeros((640,960,3),np.uint8), np.zeros((4,4),np.uint8)])
def test_unknown_fails(image):
    o=MockRecognizer().analyze(image)
    assert o.state is None and o.errors


def test_uncertain_card_does_not_guess():
    image=render()
    x,y=CARD_SLOTS[0]
    image[y:y+90,x:x+70]=128
    o=MockRecognizer().analyze(image)
    assert o.state is None
    assert any('카드' in e for e in o.errors)


def test_resize_and_letterbox():
    image=cv2.resize(render(), (1920,1280), interpolation=cv2.INTER_NEAREST)
    image=cv2.copyMakeBorder(image,20,20,30,30,cv2.BORDER_CONSTANT)
    assert MockRecognizer().analyze(image).state == GameState()


def test_crop_failure_and_restore():
    source=MockSource()
    source.configure(region=Region(.1,.1,.7,.7))
    assert MockRecognizer().analyze(source.grab()[0]).state is None
    source.configure(region=Region())
    assert MockRecognizer().analyze(source.grab()[0]).state == GameState()


def test_stabilize_and_invalidate():
    f=Stabilizer()
    s=GameState()
    assert f.update(s) is None
    assert f.update(s)==s
    assert f.update(None) is None
    assert f.update(s) is None
    changed=replace(s,pot=300)
    assert f.update(changed) is None
    assert f.update(changed)==changed


@pytest.mark.parametrize('scale', [1.25,1.5,1.75,2.0])
def test_fractional_dpi(scale):
    frame=cv2.resize(render(),None,fx=scale,fy=scale,interpolation=cv2.INTER_NEAREST)
    assert MockRecognizer().analyze(frame).state == GameState()


@pytest.mark.parametrize('position', ['UNKNOWN','BTN','SB','BB','UTG','MP','CO'])
def test_position(position):
    s=replace(GameState(),position=position)
    assert MockRecognizer().analyze(render(s)).state == s


def test_uncertain_amount_invalidates_state():
    frame=render()
    frame[250:278,180:200]=128
    o=MockRecognizer().analyze(frame)
    assert o.state is None
    assert any('pot' in e for e in o.errors)
