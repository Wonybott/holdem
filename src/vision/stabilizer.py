from src.models.state import GameState


class Stabilizer:
    """Require consecutive *current* observations, including identical images.

    Missing/uncertain input immediately invalidates the visible state; old values
    must never quietly replace an unreadable field.
    """
    def __init__(self, frames=2):
        self.frames = frames
        self.reset()

    def reset(self):
        self.candidate = None
        self.count = 0

    def update(self, state: GameState | None):
        if state is None:
            self.reset()
            return None
        if state == self.candidate:
            self.count += 1
        else:
            self.candidate, self.count = state, 1
        return state if self.count >= self.frames else None
