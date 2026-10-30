from dataclasses import replace
import pytest
from src.models.state import GameState
from src.poker.equity import EquityResult
from src.strategy.guidance import explain_decision


def result(equity,error=.01):
    return EquityResult(equity,0,equity,3000,error)


def test_free_check_never_invents_a_raise():
    decision=explain_decision(replace(GameState(),to_call=0),result(.1))
    assert decision.action=='check'
    assert decision.amount=='추가 금액 0칩'
    assert '정하지 않습니다' in decision.instruction


@pytest.mark.parametrize('equity,expected',[(.5,'call'),(.05,'fold'),(20/140,'uncertain')])
def test_showdown_decision_relative_to_real_break_even(equity,expected):
    decision=explain_decision(GameState(),result(equity))
    assert decision.action==expected
    assert '20칩' in decision.amount
    assert '가정' in decision.assumption


def test_mc_error_can_reverse_a_confident_looking_call_into_hold():
    state=GameState()
    assert explain_decision(state,result(.2,.001)).action=='call'
    assert explain_decision(state,result(.2,.1)).action=='uncertain'


def test_amount_is_actual_call_not_pot_fraction_or_stack():
    state=replace(GameState(),pot=100,to_call=25)
    assert explain_decision(state,result(.5)).amount=='콜 25칩'
