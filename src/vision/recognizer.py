from dataclasses import dataclass, field
from typing import Protocol
import cv2
import numpy as np
from src.models.state import GameState
from src.vision.mock import (WIDTH, HEIGHT, CARD_SLOTS, CARD_H, CARD_W, CARD_TEMPLATES,
                             FIELDS, CELL_H, CELL_W, CELLS, GLYPH_TEMPLATES, header)


class OptionalOCR(Protocol):
    """Extension point only: an OCR backend must return unknown on uncertainty."""
    def read(self, image: np.ndarray) -> tuple[str | None, float]: ...


@dataclass
class Observation:
    state: GameState | None = None
    confidence: dict[str, float] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def similarity(a, b):
    return 1 - float(np.abs(a.astype(np.float32) - b.astype(np.float32)).mean()) / 255


def classify(tile, templates, margin=.025):
    # Compare glyph pixels, not the largely identical card background.
    # Area resampling supports fractional DPI without mistaking background
    # agreement for high recognition confidence.
    def score(template):
        a, b = tile.astype(np.float32), template.astype(np.float32)
        if tile.shape[0] == CARD_H:
            a, b = a[20:62, 4:66], b[20:62, 4:66]
            mask = (a.min(axis=2) < 180) | (b.min(axis=2) < 180)
        else:
            mask = (a.max(axis=2) > 30) | (b.max(axis=2) > 30)
        if not mask.any():
            return 1.0
        return 1 - float(np.abs(a-b)[mask].mean()) / 255
    scores = sorted(((score(t), name) for name, t in templates.items()), reverse=True)
    score, name = scores[0]
    # Both absolute match quality and distance from the runner-up matter.
    if score < .82 or score - scores[1][0] < margin:
        return None, score
    return name, score


class MockRecognizer:
    """Only the project's own fixture is supported. Never generic live-site vision."""
    def analyze(self, image):
        result = Observation()
        try:
            if image is None or image.ndim != 3 or image.shape[2] != 3:
                raise ValueError("유효한 BGR 이미지가 아닙니다.")
            mask = cv2.inRange(image, (140, 20, 140), (220, 90, 220))
            points = cv2.findNonZero(mask)
            if points is None:
                raise ValueError("자체 모의 화면 표식이 없습니다.")
            x, y, w, h = cv2.boundingRect(points)
            if w < 480 or h < 320:
                raise ValueError("모의 화면 전체가 필요합니다. 캡처 영역을 재설정하세요.")
            crop = image[y:y+h, x:x+w]
            candidates = [cv2.resize(crop, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA)]
            if w >= WIDTH and h >= HEIGHT:
                # Invert both common nearest-neighbor conventions. Qt and
                # OpenCV can place fractional-DPI pixel boundaries differently.
                for offset in ("end", "center"):
                    if offset == "end":
                        xs = np.ceil((np.arange(WIDTH)+1)*w/WIDTH).astype(int)-1
                        ys = np.ceil((np.arange(HEIGHT)+1)*h/HEIGHT).astype(int)-1
                    else:
                        xs = ((np.arange(WIDTH)+.5)*w/WIDTH).astype(int)
                        ys = ((np.arange(HEIGHT)+.5)*h/HEIGHT).astype(int)
                    candidates.append(crop[ys[:, None], xs[None, :]])
            frame = max(candidates, key=lambda f: similarity(f[8:50, 8:952], header()))
            if similarity(frame[8:50, 8:952], header()) < .98:
                raise ValueError("모의 화면 인증 표식 인식 실패")
            cards = []
            for i, (x, y) in enumerate(CARD_SLOTS):
                value, score = classify(frame[y:y+CARD_H, x:x+CARD_W], CARD_TEMPLATES)
                result.confidence[f"card{i}"] = score
                if value is None:
                    result.errors.append(f"카드 {i+1}: 인식 실패")
                cards.append(value)
            values = {}
            for key, (x, y) in FIELDS.items():
                chars, confidence = [], 1.0
                for j in range(CELLS):
                    c, score = classify(frame[y:y+CELL_H, x+j*CELL_W:x+(j+1)*CELL_W], GLYPH_TEMPLATES, margin=.025)
                    confidence = min(confidence, score)
                    chars.append(c or "?")
                text = "".join(chars).strip()
                result.confidence[key] = confidence
                if "?" in text:
                    result.errors.append(f"{key}: 인식 실패")
                values[key] = text
            if result.errors:
                return result
            if "--" in cards[:2]:
                raise ValueError("홀 카드 인식 실패")
            board = cards[2:]
            count = next((i for i, c in enumerate(board) if c == "--"), 5)
            if any(c != "--" for c in board[count:]):
                raise ValueError("보드 슬롯 사이에 빈 카드가 있습니다.")
            opponents = int(values["opponents"])
            if not 1 <= opponents <= 8:
                raise ValueError("상대 수 인식 실패")
            result.state = GameState(tuple(cards[:2]), tuple(board[:count]), float(values["pot"]),
                                     float(values["to_call"]),
                                     tuple(float(values[f"stack{i}"]) for i in range(opponents+1)),
                                     opponents, values["position"])
        except (ValueError, TypeError, cv2.error) as exc:
            result.errors.append(f"인식 실패: {exc}")
        return result
