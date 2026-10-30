"""Conditional chip EV, no policy recommendation without an opponent model."""
from dataclasses import dataclass
from math import isfinite


def money(*values):
    if any(not isfinite(v) or v < 0 for v in values):
        raise ValueError("금액은 유한한 음이 아닌 값이어야 합니다.")


def probability(p):
    if not isfinite(p) or not 0 <= p <= 1:
        raise ValueError("확률은 0~1이어야 합니다.")


def pot_odds(pot, call):
    money(pot, call)
    return call / (pot + call) if pot + call else 0.0


def call_ev(equity, pot, call):
    probability(equity)
    money(pot, call)
    return equity * (pot + call) - call


@dataclass(frozen=True)
class BetScenario:
    amount: float
    fraction: float
    pure_bluff_break_even: float
    ev: float | None


def bet_scenarios(pot, stack, all_fold_probability=None, called_equity=None):
    """Fresh heads-up bet only; when called, one opponent matches the bet.

    Without explicit joint all-fold probability AND equity conditioned on calls,
    EV remains unknown. Pot-share against a random hand is NOT called equity.
    """
    money(pot, stack)
    for value in (all_fold_probability, called_equity):
        if value is not None:
            probability(value)
    rows = []
    for fraction in (0.25, 0.5, 0.75, 1.0):
        bet = min(stack, pot * fraction)
        ev = None
        if all_fold_probability is not None and called_equity is not None:
            f, e = all_fold_probability, called_equity
            ev = f * pot + (1-f) * (e * (pot + 2*bet) - bet)
        rows.append(BetScenario(bet, fraction, bet / (pot + bet) if pot+bet else 0, ev))
    return rows
