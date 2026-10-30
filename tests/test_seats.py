from dataclasses import replace
import math
import pytest
from src.models.table import Seat,TableSnapshot
from src.models.state import GameState
from src.vision.seats import TableTracker,seat_position
from src.strategy.scenarios import pot_odds
from src.strategy.guidance import explain_decision
from src.poker.equity import EquityResult,estimate


def actors():
    return [Seat('a',.7,1,occupied=True,stack=48000,in_hand=True,hero=True),
            Seat('b',1,.5,occupied=True,stack=44000,in_hand=True),
            Seat('c',.3,0,occupied=True,stack=50000,in_hand=True)]


def test_empty_occupied_and_folded_are_different():
    tracker=TableTracker()
    empty=Seat('empty',.7,1,number=1,occupied=False)
    first,_=tracker.update([empty],'waiting')
    seated=replace(actors()[0],number=None)
    second,_=tracker.update([seated],'playing','a','Preflop',('7h','4c'))
    assert second[0].slot_id==first[0].slot_id
    assert second[0].number==1
    assert second[0].occupied is True
    folded,_=tracker.update([replace(seated,last_action='fold')],'playing','a','Preflop',('7h','4c'))
    assert folded[0].occupied is True and folded[0].in_hand is False


def test_check_then_other_bet_records_observations_without_making_call_zero():
    tracker=TableTracker();a,b,c=actors()
    first,hero=tracker.update([replace(a,last_action='check'),b,c],'playing','a','Flop',('7h','4c'))
    second,_=tracker.update([replace(a,last_action='check'),replace(b,bet=4000),c],'playing','a','Flop',('7h','4c'))
    assert next(s for s in second if s.hero).bet is None
    assert any(s.bet==4000 for s in second)
    assert len([e for e in tracker.history if e.action=='observed_check'])==1
    assert len([e for e in tracker.history if e.action=='observed_bet_to'])==1
    tracker.update([replace(a,last_action='check'),replace(b,bet=None),c],'playing','a','Flop',('7h','4c'))
    tracker.update([replace(a,last_action='check'),replace(b,bet=4000),c],'playing','a','Flop',('7h','4c'))
    assert len([e for e in tracker.history if e.action=='observed_bet_to'])==1
    assert pot_odds(8000,4000)==pytest.approx(1/3)


def test_fold_persists_and_resets_for_a_new_hand():
    tracker=TableTracker();a,b,c=actors()
    tracker.update([a,b,c],'playing','a','Flop',('7h','4c'))
    tracker.update([a,replace(b,last_action='fold',in_hand=None),c],'playing','a','Flop',('7h','4c'))
    seats,_=tracker.update([a,replace(b,in_hand=None),c],'playing','a','Turn',('7h','4c'))
    assert next(s for s in seats if s.name==b.name and s.x==b.x).in_hand is False
    seats,_=tracker.update([a,b,c],'playing','a','Preflop',('8h','2d'))
    assert all(s.in_hand is True for s in seats)


def test_clockwise_positions_include_folded_dealt_seats():
    seats=[]
    for i in range(6):
        angle=i*2*math.pi/6
        seats.append(Seat(str(i),.5+math.cos(angle)*.6,.5+math.sin(angle)*.6,occupied=True,in_hand=i!=2,dealer=i==0))
    assert seat_position(seats,'0',set('012345'))=='BTN'
    assert seat_position(seats,'1',set('012345'))=='SB'
    assert seat_position(seats,'2',set('012345'))=='BB'
    assert seat_position(seats,'3',set('012345'))=='UTG'
    assert seat_position(seats,'5',set('012345'))=='CO'
    assert seat_position(seats,'1',{'0','1'})=='UNKNOWN'


def test_paused_display_never_recommends_a_check():
    state=GameState(to_call=0,paused=True)
    decision=explain_decision(state,EquityResult(.5,0,.5,1000,.01))
    assert decision.action=='paused'
    assert not decision.amount


def test_ten_players_supported_by_the_deck_and_split_pot():
    state=GameState(('2h','3d'),('As','Ks','Qs','Js','Ts'),stacks=(1000,)*10,opponents=9)
    result=estimate(state,iterations=30,seed=12)
    assert result.tie==1
    assert result.equity==pytest.approx(.1)


def test_seat_identity_survives_small_layout_movement():
    tracker=TableTracker();a,b,c=actors()
    first,hero=tracker.update([a,b,c],'playing','a','Flop',('7h','4c'))
    second,hero2=tracker.update([replace(c,x=c.x+.01),replace(a,y=a.y-.01),b],'playing','a','Flop',('7h','4c'))
    assert hero==hero2
    assert {s.slot_id for s in first}=={s.slot_id for s in second}
