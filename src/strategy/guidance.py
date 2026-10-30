"""Readable conditional decisions, never an unconditional poker policy."""
from dataclasses import dataclass
from src.models.state import GameState
from src.poker.equity import EquityResult
from src.strategy.scenarios import pot_odds, call_ev


@dataclass(frozen=True)
class Guidance:
    action: str
    title: str
    instruction: str
    amount: str
    tone: str
    assumption: str = '추가 베팅 없이 쇼다운하는 가정 · 입력한 상대 범위 기준'


def explain_decision(state: GameState, result: EquityResult) -> Guidance:
    if state.to_call == 0:
        return Guidance('check', '체크 가능',
                        '지금 콜할 금액은 없습니다. 베팅·레이즈 금액은 상대 행동 정보가 없어 정하지 않습니다.',
                        '추가 금액 0칩', 'good')
    threshold = pot_odds(state.pot, state.to_call)
    ev = call_ev(result.equity, state.pot, state.to_call)
    radius = 1.96 * result.standard_error
    comparison = f'내 팟 지분 {result.equity:.1%} / 콜 기준 {threshold:.1%}.'
    if result.equity - radius > threshold:
        return Guidance('call', '콜 검토',
                        f'{comparison} 가정상 콜 EV {ev:+.1f}칩입니다. 미래 베팅·상대 범위에 따라 판단이 달라집니다.',
                        f'콜 {state.to_call:g}칩', 'good')
    if result.equity + radius < threshold:
        return Guidance('fold', '폴드 검토',
                        f'{comparison} 가정상 콜 EV {ev:+.1f}칩으로, 콜 기준에 못 미칩니다.',
                        f'콜 비용 {state.to_call:g}칩', 'caution')
    return Guidance('uncertain', '콜·폴드 판단 보류',
                    f'{comparison} 시뮬레이션 오차 범위가 콜 기준과 겹칩니다. 표본 수와 상대 범위를 확인하세요.',
                    f'필요한 콜 {state.to_call:g}칩', 'neutral')
