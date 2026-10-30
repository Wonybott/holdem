"""A deliberately independent visual fixture, not a PokerNow skin."""
import cv2
import numpy as np
from src.models.state import DECK, POSITIONS, GameState

WIDTH, HEIGHT = 960, 640
CARD_W, CARD_H = 70, 90
CARD_SLOTS = [(40, 110), (120, 110)] + [(300 + i*80, 110) for i in range(5)]
FIELDS = {"pot": (180, 250), "to_call": (180, 290), "opponents": (180, 330),
          "position": (180, 370), **{f"stack{i}": (650, 250+i*36) for i in range(10)}}
GLYPHS = " 0123456789.BTNUSMPKOWCG"
CELL_W, CELL_H, CELLS = 20, 28, 12


def glyph(char):
    tile = np.zeros((CELL_H, CELL_W, 3), np.uint8)
    cv2.putText(tile, char, (2, 21), cv2.FONT_HERSHEY_SIMPLEX, .65, (255, 255, 255), 1, cv2.LINE_8)
    return tile


def card_tile(card):
    tile = np.full((CARD_H, CARD_W, 3), 245, np.uint8)
    cv2.rectangle(tile, (0, 0), (CARD_W-1, CARD_H-1), (50, 50, 50), 2)
    color = (30, 30, 190) if card != "--" and card[1] in "hd" else (25, 25, 25)
    cv2.putText(tile, card, (6, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2, cv2.LINE_8)
    return tile


def header():
    tile = np.zeros((42, 944, 3), np.uint8)
    cv2.putText(tile, "HVA MOCK ONLY / V1", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, .9,
                (100, 240, 240), 2, cv2.LINE_8)
    return tile


def render(state=GameState()):
    image = np.full((HEIGHT, WIDTH, 3), (35, 65, 35), np.uint8)
    cv2.rectangle(image, (0, 0), (WIDTH-1, HEIGHT-1), (180, 50, 180), 4)
    image[8:50, 8:952] = header()
    for label, x in (("HERO", 40), ("BOARD", 300)):
        cv2.putText(image, label, (x, 90), 0, .6, (220, 220, 220), 1)
    for (x, y), card in zip(CARD_SLOTS, (*state.hole, *state.board, *(["--"] * (5-len(state.board))))):
        image[y:y+CARD_H, x:x+CARD_W] = card_tile(card)
    values = {"pot": state.pot, "to_call": state.to_call, "opponents": state.opponents,
              "position": state.position, **{f"stack{i}": s for i, s in enumerate(state.stacks)}}
    for key, (x, y) in FIELDS.items():
        cv2.putText(image, key.upper(), (x-140, y+20), 0, .5, (220, 220, 220), 1)
        value = values.get(key, "")
        text = str(int(value)) if isinstance(value, (int, float)) and value == int(value) else str(value)
        if len(text) > CELLS or any(c not in GLYPHS for c in text):
            raise ValueError("모의 화면의 숫자는 12글자 이내여야 합니다.")
        for j, char in enumerate(text.ljust(CELLS)):
            image[y:y+CELL_H, x+j*CELL_W:x+(j+1)*CELL_W] = glyph(char)
    return image


CARD_TEMPLATES = {c: card_tile(c) for c in (*DECK, "--")}
GLYPH_TEMPLATES = {c: glyph(c) for c in set(GLYPHS)}
