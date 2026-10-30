"""Validated immutable domain objects. Money is in arbitrary table chip units."""
from dataclasses import dataclass
from math import isfinite

RANKS = "23456789TJQKA"
SUITS = "shdc"
DECK = tuple(r + s for r in RANKS for s in SUITS)
POSITIONS = ("UNKNOWN", "BTN", "SB", "BB", "UTG", "MP", "CO")


def validate_cards(cards):
    cards = tuple(cards)
    if any(c not in DECK for c in cards):
        raise ValueError("카드는 As, Th 형식으로 입력하세요 (T=10, s/h/d/c).")
    if len(set(cards)) != len(cards):
        raise ValueError("중복 카드는 입력할 수 없습니다.")
    return cards


@dataclass(frozen=True)
class Action:
    player: str
    street: str
    action: str
    amount: float = 0


@dataclass(frozen=True)
class GameState:
    hole: tuple[str, ...] = ("As", "Kh")
    board: tuple[str, ...] = ("Qs", "Jh", "2c")
    pot: float = 120
    to_call: float = 20
    stacks: tuple[float, ...] = (1000, 1000, 1000)
    opponents: int = 2
    position: str = "BTN"
    history: tuple[Action, ...] = ()

    def __post_init__(self):
        validate_cards(self.hole + self.board)
        if len(self.hole) != 2 or len(self.board) not in (0, 3, 4, 5):
            raise ValueError("홀 카드 2장, 보드는 0/3/4/5장이어야 합니다.")
        if not isinstance(self.opponents, int) or not 1 <= self.opponents <= 8:
            raise ValueError("상대 수는 1~8명이어야 합니다.")
        if len(self.stacks) != self.opponents + 1:
            raise ValueError("스택은 나, 상대 순으로 상대 수+1개 입력하세요.")
        if any(not isfinite(x) or x < 0 for x in (self.pot, self.to_call, *self.stacks)):
            raise ValueError("팟/콜/스택은 유한한 0 이상의 숫자여야 합니다.")
        if self.to_call > self.stacks[0]:
            raise ValueError("콜은 내 유효 콜 금액 이하여야 합니다. 사이드 팟은 미지원입니다.")
        if self.position not in POSITIONS:
            raise ValueError("지원하지 않는 포지션입니다.")

    @property
    def street(self):
        return {0: "Preflop", 3: "Flop", 4: "Turn", 5: "River"}[len(self.board)]
