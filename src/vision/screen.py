"""User-calibrated pixel-only recognition. No site/API/DOM access."""
import base64
from dataclasses import asdict, dataclass, field
import csv
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import cv2
import numpy as np
from src.capture.sources import Region
from src.models.state import GameState, DECK
from src.vision.recognizer import Observation

CARD_FIELDS = tuple(f'card{i}' for i in range(7))


def encode_sample(image):
    if image is None or image.size == 0:
        raise ValueError('빈 카드 샘플입니다.')
    image = cv2.resize(image, (96, 128), interpolation=cv2.INTER_AREA)
    ok, data = cv2.imencode('.png', image)
    if not ok:
        raise ValueError('카드 샘플 저장 실패')
    return base64.b64encode(data).decode('ascii')


def decode_sample(value):
    if len(value) > 150000:
        raise ValueError('카드 샘플이 너무 큽니다.')
    image = cv2.imdecode(np.frombuffer(base64.b64decode(value, validate=True), np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape != (128, 96, 3):
        raise ValueError('잘못된 카드 샘플입니다.')
    return image


@dataclass
class ScreenProfile:
    monitor: int
    bounds: dict
    table: Region
    fields: dict[str, Region]
    samples: dict[str, list[str]]
    opponents: int = 1
    stacks: tuple[float, ...] = (1000, 1000)
    position: str = 'UNKNOWN'
    version: int = 1

    def validate(self):
        if self.version != 1 or not 1 <= self.monitor <= 16:
            raise ValueError('지원하지 않는 화면 설정입니다.')
        if set(self.bounds) != {'left','top','width','height'} or any(type(v) is not int for v in self.bounds.values()):
            raise ValueError('모니터 좌표가 올바르지 않습니다.')
        if self.bounds['width'] < 1 or self.bounds['height'] < 1:
            raise ValueError('모니터 크기가 올바르지 않습니다.')
        required = {*CARD_FIELDS, 'pot', 'to_call'}
        if not required.issubset(self.fields):
            raise ValueError('홀 카드 2개, 보드 5개, 팟, 콜 영역을 모두 지정하세요.')
        if not self.samples:
            raise ValueError('정답 카드 샘플을 하나 이상 등록하세요.')
        for label, images in self.samples.items():
            if label not in DECK and label not in {f'empty:{c}' for c in CARD_FIELDS[2:]}:
                raise ValueError(f'잘못된 카드 이름: {label}')
            if not 1 <= len(images) <= 20:
                raise ValueError('카드별 샘플 수는 1~20개입니다.')
            for image in images:
                decode_sample(image)
        # Validate static assumptions without inventing a captured hand.
        GameState(('As','Kh'), (), stacks=tuple(self.stacks), opponents=self.opponents,
                  position=self.position, to_call=0)

    def save(self, path):
        self.validate()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(asdict(self), ensure_ascii=False, indent=2)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(text, encoding='utf-8')
        temporary.replace(path)

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.stat().st_size > 10_000_000:
            raise ValueError('설정 파일이 너무 큽니다.')
        data = json.loads(path.read_text(encoding='utf-8'))
        data['table'] = Region(**data['table'])
        data['fields'] = {k: Region(**v) for k,v in data['fields'].items()}
        data['stacks'] = tuple(data['stacks'])
        profile = cls(**data)
        profile.validate()
        return profile


class TesseractNumbers:
    """Optional local executable, bounded runtime, TSV confidence; no downloads."""
    def __init__(self, executable=None):
        self.executable = executable or shutil.which('tesseract')
        if not self.executable:
            default = Path('C:/Program Files/Tesseract-OCR/tesseract.exe')
            if default.is_file():
                self.executable = str(default)
        if not self.executable:
            raise ValueError('숫자 OCR에 Tesseract가 필요합니다. docs/START_HERE_KO.md를 참고하세요.')

    def read(self, image):
        if image is None or image.size == 0:
            return None, 0.0
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if gray.shape[0]<60:
            scale=60/gray.shape[0]
            gray=cv2.resize(gray,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
        if float(np.median(gray)) < 127:
            gray = 255-gray
        outputs=[]
        for scale in (1,2):
            if getattr(self,'cancel',None) is not None and self.cancel.is_set():
                from src.poker.equity import Cancelled
                raise Cancelled()
            variant=cv2.resize(gray,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
            variant=cv2.copyMakeBorder(variant,12,12,12,12,cv2.BORDER_CONSTANT,value=255)
            value,confidence=self._read_variant(variant)
            if value is None:
                return None,confidence
            outputs.append((value,confidence))
        confidence=min(c for _,c in outputs)
        if outputs[0][0] != outputs[1][0]:
            return None,confidence
        return outputs[0][0],confidence

    def _read_variant(self, gray):
        ok, data = cv2.imencode('.png', gray)
        if not ok:
            return None, 0.0
        command = [self.executable, 'stdin', 'stdout', '--psm', '7', '-l', 'eng',
                   '-c', 'tessedit_char_whitelist=0123456789.,', 'tsv']
        try:
            result = subprocess.run(command, input=data.tobytes(), capture_output=True, timeout=2,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired:
            return None, 0.0
        if result.returncode:
            raise ValueError('Tesseract 실행 실패: eng 언어 데이터/설치를 확인하세요.')
        tokens = [row for row in csv.DictReader(io.StringIO(result.stdout.decode('utf-8')), delimiter='\t')
                  if row.get('text','').strip()]
        if len(tokens) != 1:
            return None, 0.0
        token = tokens[0]['text'].strip()
        confidence = max(0, float(tokens[0]['conf']) / 100)
        valid = re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?', token)
        if not valid or confidence < .85:
            return None, confidence
        return float(token.replace(',','')), confidence


def fingerprint(image):
    normalized = cv2.resize(image, (96,128), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(normalized, cv2.COLOR_BGR2GRAY)
    # Tight crops around rank+suit are recommended. Ignore the outer crop border.
    edges = cv2.Canny(gray, 70, 150)
    edges[:3] = edges[-3:] = 0
    edges[:,:3] = edges[:,-3:] = 0
    return edges > 0


class ScreenRecognizer:
    def __init__(self, profile, numbers=None):
        profile.validate()
        self.profile = profile
        self.numbers = numbers if numbers is not None else TesseractNumbers()
        self.templates = {label: [fingerprint(decode_sample(v)) for v in values]
                          for label, values in profile.samples.items()}

    def card(self, image, field):
        feature = fingerprint(image)
        scores = {}
        for label, templates in self.templates.items():
            if label.startswith('empty:') and label != f'empty:{field}':
                continue
            values=[]
            for sample in templates:
                denominator = int(feature.sum()+sample.sum())
                # Blank slots need a color/layout match, not just lack of edges.
                if denominator == 0:
                    values.append(0.0)
                else:
                    values.append(2*float((feature & sample).sum())/denominator)
            if label.startswith('empty:'):
                from src.vision.recognizer import similarity
                values = [similarity(cv2.resize(image,(96,128)), decode_sample(v))
                          for v in self.profile.samples[label]]
            scores[label] = max(values)
        ranked = sorted(((score,label) for label,score in scores.items()), reverse=True)
        if not ranked:
            return None,0.0
        score,label = ranked[0]
        runner = max((v for k,v in scores.items() if k != label), default=0)
        if score < .96 or score-runner < .025:
            return None,score
        return ('--' if label.startswith('empty:') else label),score

    def signature(self, image):
        # Ignore clocks, avatars and chat outside the calibrated data fields.
        return b''.join(self.profile.fields[key].crop(image).tobytes()
                        for key in sorted(self.profile.fields))

    def analyze(self, image):
        result = Observation()
        try:
            cards=[]
            for field in CARD_FIELDS:
                tile = self.profile.fields[field].crop(image)
                value,confidence = self.card(tile,field)
                cards.append(value)
                result.confidence[field] = confidence
                if value is None:
                    result.errors.append(f'{field}: 카드 인식 실패. 현재 카드 샘플을 보정 설정에 추가하세요.')
            values={}
            for field, region in self.profile.fields.items():
                if field in CARD_FIELDS:
                    continue
                value,confidence = self.numbers.read(region.crop(image))
                result.confidence[field] = confidence
                values[field] = value
                if value is None:
                    result.errors.append(f'{field}: 숫자 OCR 인식 실패')
            if result.errors:
                return result
            board=cards[2:]
            count=next((i for i,c in enumerate(board) if c=='--'),5)
            if any(c!='--' for c in board[count:]):
                raise ValueError('보드 중간이 비어 있습니다.')
            stacks=tuple(values.get(f'stack{i}', fallback) for i,fallback in enumerate(self.profile.stacks))
            result.state = GameState(tuple(cards[:2]),tuple(board[:count]), values['pot'],values['to_call'],
                                     stacks,self.profile.opponents,self.profile.position)
        except (ValueError,TypeError,cv2.error) as exc:
            result.errors.append(f'인식 실패: {exc}')
        return result
