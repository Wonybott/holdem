"""Generated full-browser tests, not tests on the user's private screenshots."""
import pytest
from src.utils.table_scenes import scene
from src.vision.pokernow import PokerNowRecognizer
from src.vision.screen import TesseractNumbers
from src.strategy.scenarios import pot_odds


@pytest.fixture(scope='module')
def reader():
    try:TesseractNumbers()
    except ValueError:pytest.skip('optional Tesseract unavailable')
    return PokerNowRecognizer()


def test_waiting_room_has_seats_without_requiring_hole_cards(reader):
    observation=reader.analyze(scene(waiting=True,occupied=(0,)))
    assert observation.table is not None,observation.errors
    assert observation.table.phase=='waiting'
    assert observation.state is None
    assert not observation.errors
    assert sum(s.occupied is True for s in observation.table.seats)==1
    assert any(s.occupied is False for s in observation.table.seats)
    assert all(s.in_hand is None for s in observation.table.seats)


def test_previous_check_does_not_override_call_or_total_pot(reader):
    observation=reader.analyze(scene(bets={8:4000}))
    assert observation.state is not None,observation.errors
    state=observation.state
    assert state.to_call==4000
    assert state.settled_pot==4000
    assert state.pot==8000
    assert pot_odds(state.pot,state.to_call)==pytest.approx(1/3)
    assert any(s.bet==4000 and not s.hero for s in state.seats)


@pytest.mark.parametrize('hero,occupied',[(3,(3,0,6)),(6,(6,0,3,8))])
def test_arbitrary_seats_in_full_3839x1599_browser(hero,occupied):
    automatic=PokerNowRecognizer()
    picture=scene(hero=hero,occupied=occupied,bets={8:4000} if 8 in occupied else {0:4000},full_browser=True)
    assert picture.shape[:2]==(1599,3839)
    observation=automatic.analyze(picture)
    assert observation.state is not None,observation.errors
    state=observation.state
    assert state.hole==('7h','4c')
    assert state.opponents==len(occupied)-1
    assert state.to_call==4000
    assert state.pot==8000
    assert sum(s.hero for s in state.seats)==1
    assert any(s.bet==4000 and not s.hero for s in state.seats)


def test_paused_browser_with_gray_deck_and_offline_player():
    automatic=PokerNowRecognizer()
    picture=scene(paused=True,gray=True,full_browser=True,board=('As','5h','2s','5s'),hole=('8h','2d'))
    observation=automatic.analyze(picture)
    assert observation.table is not None,observation.errors
    assert observation.table.phase=='paused'
    assert observation.state is not None,observation.errors
    assert observation.state.paused
    assert observation.state.to_call is None
    assert observation.state.hole==('8h','2d')
    assert observation.state.board==('As','5h','2s','5s')
    assert any(s.offline and s.in_hand is True for s in observation.state.seats)


def test_crowded_preflop_pair_is_owned_by_panel_not_rank_centre(reader):
    picture=scene(occupied=(0,1,2,3,4,7,8,9),hole=('6d','Kd'),board=(),
                  bets={4:90,3:20,2:20,1:10},full_browser=True)
    observation=reader.analyze(picture)
    assert observation.state is not None,observation.errors
    assert observation.state.hole==('6d','Kd')
    assert observation.state.opponents==7
    assert observation.state.stacks[0]==48000
    assert next(s for s in observation.state.seats if s.hero).name=='wonybot'


def test_tournament_preflop_zero_pot_and_bright_badges(reader):
    picture=scene(occupied=(0,1,2,3,4,7,8,9),hole=('6d','Kd'),board=(),
                  bets={4:90,3:20,2:20,1:10},full_browser=True,tournament=True)
    observation=reader.analyze(picture)
    assert observation.cards is not None,observation.errors
    assert observation.cards.hole==('6d','Kd')
    assert observation.state is not None,observation.errors
    assert observation.state.board==()
    assert observation.state.settled_pot==0
    assert observation.state.pot==140
    assert observation.state.opponents==7
    assert observation.state.stacks[0]==1000
    assert all(s<=1000 for s in observation.state.stacks)
    assert observation.state.hero_turn is False
    assert observation.state.to_call is None  # Dim CALL 90 is not actionable.
