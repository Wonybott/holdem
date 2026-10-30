"""Regenerate the self-owned image fixtures: python -m src.utils.fixtures."""
from dataclasses import replace
from pathlib import Path
import cv2
from PIL import Image
from src.models.state import GameState
from src.vision.mock import render


def generate(directory="assets"):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    default = GameState()
    states = {"mock_preflop.png": replace(default, board=(), to_call=0),
              "mock_flop.png": default,
              "mock_river.png": replace(default, board=("Qs","Jh","2c","3d","4s"), pot=300, to_call=0)}
    for name, state in states.items():
        image = Image.fromarray(cv2.cvtColor(render(state), cv2.COLOR_BGR2RGB))
        image.save(directory/name)


if __name__ == "__main__":
    generate()
