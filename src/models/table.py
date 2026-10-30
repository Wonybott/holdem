"""Pixel observations of seats; unknown is distinct from empty or zero."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Seat:
    slot_id: str
    x: float
    y: float
    number: int | None = None
    occupied: bool | None = None
    name: str = ''
    stack: float | None = None
    bet: float | None = None
    in_hand: bool | None = None
    hero: bool = False
    dealer: bool = False
    last_action: str = ''
    offline: bool = False
    waiting: bool = False


@dataclass(frozen=True)
class TableSnapshot:
    seats: tuple[Seat,...] = ()
    phase: str = 'unknown'
    hero_id: str | None = None
    settled_pot: float | None = None
    total_pot: float | None = None
    notes: tuple[str,...] = ()
