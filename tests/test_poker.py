from dataclasses import replace
from threading import Event
import pytest
from src.models.state import DECK, GameState
from src.poker.equity import hand_class, parse_range, estimate, Cancelled
from src.strategy.scenarios import pot_odds, call_ev, bet_scenarios


def test_standard_deck():
    assert len(DECK) == len(set(DECK)) == 52


@pytest.mark.parametrize('hole,board,expected', [
    (("As", "Ks"), ("Qs", "Js", "Ts", "2h", "3d"), "Royal Flush"),
    (("As", "2h"), ("3d", "4c", "5s", "Kh", "Qd"), "Straight"),
    (("As", "9s"), ("2s", "5s", "Js", "Kh", "Qd"), "Flush"),
])
def test_hand_classes(hole, board, expected):
    assert hand_class(hole, board) == expected


def test_nuts_win():
    s = GameState(("As", "Ks"), ("Qs", "Js", "Ts", "2h", "3d"))
    r = estimate(s, iterations=150, seed=12)
    assert (r.win, r.tie, r.equity) == (1, 0, 1)


@pytest.mark.parametrize('opponents', [1, 2, 8])
def test_board_royal_split(opponents):
    s = GameState(("2h", "3d"), ("As", "Ks", "Qs", "Js", "Ts"),
                  stacks=(1000,) * (opponents+1), opponents=opponents)
    r = estimate(s, iterations=80, seed=12)
    assert r.win == 0 and r.tie == 1
    assert r.equity == pytest.approx(1/(opponents+1))


def test_preflop_equity_reproducible():
    s = GameState(("As", "Ah"), (), stacks=(1000,1000), opponents=1)
    a = estimate(s, iterations=1500, seed=14)
    assert a == estimate(s, iterations=1500, seed=14)
    assert .78 < a.win < .91
    assert a.win <= a.equity <= a.win + a.tie
    assert a.standard_error > 0


@pytest.mark.parametrize('changes', [
    {'hole': ("As", "As")}, {'board': ("As", "Jh", "2c")}, {'board': ("2c",)},
    {'opponents': 9}, {'pot': float('nan')}, {'to_call': -1}, {'stacks': (1,2)},
    {'to_call': 1001}, {'hole': ("10s", "Kh")},
])
def test_invalid_state(changes):
    with pytest.raises(ValueError):
        replace(GameState(), **changes)


def test_ranges_and_blockers():
    assert len(parse_range('AA')) == 6
    assert len(parse_range('AKs')) == 4
    assert len(parse_range('AKo')) == 12
    assert len(parse_range('AK')) == 16
    assert parse_range('random') is None
    with pytest.raises(ValueError):
        parse_range('AKx')
    with pytest.raises(ValueError):
        estimate(GameState(), [parse_range('AsKh')]*2, iterations=1)
    with pytest.raises(ValueError):
        estimate(GameState(), [parse_range('2s3s')]*2, iterations=1)


def test_fixed_villain_loss():
    s = GameState(("2h", "3d"), ("Qs", "Js", "Ts", "2c", "3h"), stacks=(1000,1000), opponents=1)
    r = estimate(s, [parse_range('AsKs')], iterations=50)
    assert r.win == r.tie == r.equity == 0


def test_cancel():
    e=Event(); e.set()
    with pytest.raises(Cancelled):
        estimate(GameState(), cancel=e)


def test_pot_odds_and_call_ev():
    assert pot_odds(100,25) == .2
    assert pot_odds(0,0) == 0
    assert call_ev(.2,100,25) == 0
    assert call_ev(.5,100,25) == 37.5
    with pytest.raises(ValueError):
        pot_odds(-1,10)


def test_bet_scenarios_require_explicit_model():
    rows=bet_scenarios(100,60)
    assert [r.amount for r in rows] == [25,50,60,60]
    assert all(r.ev is None for r in rows)
    assert rows[1].pure_bluff_break_even == pytest.approx(1/3)
    assert bet_scenarios(100,100,1,.5)[0].ev == 100
    assert bet_scenarios(100,100,0,0)[0].ev == -25
