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
        self.key = None

    def update(self, state: GameState | None, key=None):
        if state is None:
            self.reset()
            return None
        current_key=state if key is None else key
        if current_key == self.key:
            self.count += 1
        else:
            self.count = 1
        self.candidate,self.key=state,current_key
        return state if self.count >= self.frames else None
