"""Monte Carlo with independent uniform ranges conditioned on disjoint cards."""
from dataclasses import dataclass
from itertools import combinations
import random
from threading import Event
from treys import Card, Evaluator
from src.models.state import DECK, RANKS, GameState, validate_cards


class Cancelled(Exception):
    pass


def parse_range(text: str):
    """random, AA, AKs, AKo, AK, or explicit AsKh; comma separated union."""
    text = text.strip()
    if text.lower() == "random":
        return None
    if not text:
        raise ValueError("상대 범위가 비어 있습니다.")
    result = set()
    for token in text.split(","):
        token = token.strip()
        if len(token) == 4:
            pair = validate_cards((token[:2], token[2:]))
            result.add(tuple(sorted(pair)))
            continue
        if len(token) not in (2, 3) or any(r not in RANKS for r in token[:2]):
            raise ValueError(f"잘못된 범위: {token}")
        if len(token) == 3 and (token[2] not in "so" or token[0] == token[1]):
            raise ValueError(f"잘못된 범위: {token}")
        for a, b in combinations(DECK, 2):
            if sorted((a[0], b[0])) != sorted(token[:2]):
                continue
            if len(token) == 3 and ((a[1] == b[1]) != (token[2] == "s")):
                continue
            result.add(tuple(sorted((a, b))))
    if not result:
        raise ValueError("범위에 가능한 조합이 없습니다.")
    return tuple(sorted(result))


@dataclass(frozen=True)
class EquityResult:
    win: float
    tie: float
    equity: float  # Expected pot share, including multiway ties
    samples: int
    standard_error: float


def hand_class(hole, board):
    validate_cards(tuple(hole) + tuple(board))
    if len(hole) != 2 or len(board) not in (3, 4, 5):
        raise ValueError("핸드 평가는 홀 2장과 보드 3~5장이 필요합니다.")
    evaluator = Evaluator()
    score = evaluator.evaluate([Card.new(c) for c in board], [Card.new(c) for c in hole])
    return evaluator.class_to_string(evaluator.get_rank_class(score))


def estimate(state: GameState, ranges=None, iterations=3000, seed=None, cancel: Event | None = None):
    if not isinstance(iterations, int) or not 1 <= iterations <= 200_000:
        raise ValueError("시뮬레이션 횟수는 1~200000입니다.")
    if ranges is None:
        ranges = [None] * state.opponents
    if len(ranges) != state.opponents:
        raise ValueError("상대마다 범위 하나가 필요합니다.")
    known = set(state.hole + state.board)
    available = [c for c in DECK if c not in known]
    pools = []
    for r in ranges:
        if r is None:
            pools.append(None)
            continue
        cleaned = set()
        for pair in r:
            validate_cards(pair)
            if len(pair) != 2:
                raise ValueError("범위 조합은 두 장이어야 합니다.")
            if not known.intersection(pair):
                cleaned.add(tuple(sorted(pair)))
        if not cleaned:
            raise ValueError("알려진 카드와 겹쳐 가능한 상대 범위가 없습니다.")
        pools.append(tuple(sorted(cleaned)))
    rng = random.Random(seed)
    ev = Evaluator()
    encoded = {c: Card.new(c) for c in DECK}
    hero = [encoded[c] for c in state.hole]
    wins = ties = 0
    total = squares = 0.0
    for _ in range(iterations):
        if cancel and cancel.is_set():
            raise Cancelled()
        # Reject the whole assignment; sequentially conditioning each player's
        # range would bias earlier players when later ranges are constrained.
        for attempt in range(10000):
            hands = [rng.sample(available, 2) if pool is None else rng.choice(pool) for pool in pools]
            flat = [c for hand in hands for c in hand]
            if len(flat) == len(set(flat)):
                break
            if attempt % 100 == 0 and cancel and cancel.is_set():
                raise Cancelled()
        else:
            raise ValueError("범위들이 서로 충돌하거나 지나치게 좁습니다. 범위를 넓혀 주세요.")
        remaining = [c for c in available if c not in flat]
        board = [encoded[c] for c in (*state.board, *rng.sample(remaining, 5 - len(state.board))) ]
        score = ev.evaluate(board, hero)
        others = [ev.evaluate(board, [encoded[c] for c in hand]) for hand in hands]
        best = min(score, *others)
        share = 0.0
        if score == best:
            count = 1 + others.count(best)
            share = 1 / count
            wins += count == 1
            ties += count > 1
        total += share
        squares += share * share
    equity = total / iterations
    variance = max(0, squares / iterations - equity * equity)
    return EquityResult(wins / iterations, ties / iterations, equity, iterations,
                        (variance / iterations) ** 0.5)
