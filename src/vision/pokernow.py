"""Automatic PokerNow-style face-card layout. Pixels only; no saved calibration.

The reader deliberately rejects uncertain cards, ambiguous seats, and hidden
call values. Only a positively detected action state can produce advice.
"""
from dataclasses import dataclass
import hashlib
import re
import cv2
import numpy as np
from src.models.state import GameState
from src.vision.ocr import Box,Word,TesseractReader
from src.vision.recognizer import Observation
from src.vision.screen import TesseractNumbers
from src.vision.suit_templates import MASKS


def trim(mask):
    ys,xs=np.where(mask)
    if not len(xs): return None
    return mask[ys.min():ys.max()+1,xs.min():xs.max()+1]


def normalized(mask):
    mask=trim(mask)
    if mask is None:return np.zeros((40,32),bool)
    return cv2.resize(mask.astype(np.uint8),(32,40),interpolation=cv2.INTER_NEAREST)>0


SUITS={k:[np.unpackbits(np.frombuffer(bytes.fromhex(v),np.uint8)).reshape(40,32)>0 for v in values]
       for k,values in MASKS.items()}


def read_suit(mask,color):
    scores={}
    for suit,templates in SUITS.items():
        best=0
        for angle in (0,-6,6,-12,12):
            h,w=mask.shape
            padded=np.pad(mask,((h//3,h//3),(w//3,w//3))).astype(np.uint8)
            ph,pw=padded.shape
            rotated=cv2.warpAffine(padded,cv2.getRotationMatrix2D((pw/2,ph/2),angle,1),(pw,ph))>0
            value=normalized(rotated)
            for template in templates:
                union=(value|template).sum()
                if union: best=max(best,float((value&template).sum()/union))
        scores[suit]=best
    ranked=sorted(((v,k) for k,v in scores.items()),reverse=True)
    confidence,suit=ranked[0]
    # Hue is an independent check. Black/red two-color decks are also allowed.
    allowed={'green':'c','blue':'d','red':'hd','black':'sc'}.get(color,'')
    if confidence<.66 or confidence-ranked[1][0]<.055 or suit not in allowed:
        return None,confidence
    return suit,confidence


def ink_color(image,mask):
    pixels=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)[mask]
    if len(pixels)<8:return None
    vivid=pixels[(pixels[:,1]>90)&(pixels[:,2]>70)]
    if len(vivid)>len(pixels)*.35:
        hue=float(np.median(vivid[:,0]))
        if 30<=hue<=90:return 'green'
        if 90<hue<=145:return 'blue'
        if hue<=15 or hue>=165:return 'red'
        return None
    if float(np.median(pixels[:,2]))<125:return 'black'
    return None


@dataclass(frozen=True)
class Face:
    card: str
    box: Box
    confidence: float
    group: Box


def table_bounds(image):
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    mask=cv2.inRange(hsv,(0,65,25),(179,255,245))
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((9,9),np.uint8))
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    h,w=image.shape[:2]
    possible=[]
    for c in contours:
        x,y,bw,bh=cv2.boundingRect(c)
        if cv2.contourArea(c)>.10*w*h and bw>1.3*bh and bw>.4*w:
            possible.append((cv2.contourArea(c),Box(x,y,bw,bh)))
    if not possible:raise ValueError('PokerNow 테이블을 찾지 못했습니다. 브라우저 테이블이 크게 보이도록 하세요.')
    return max(possible,key=lambda v:v[0])[1]


def card_groups(image,table):
    white=cv2.inRange(image,(210,210,210),(255,255,255))
    contours,_=cv2.findContours(white,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    result=[]
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        if not (.10*table.h<h<.48*table.h and .28<w/h<4.5):continue
        if cv2.contourArea(contour)<.35*w*h:continue
        if not (table.x-.2*table.w<x<table.x+1.2*table.w and table.y-.2*table.h<y<table.y+1.3*table.h):continue
        mask=np.zeros(image.shape[:2],np.uint8);cv2.drawContours(mask,[contour],-1,255,-1)
        result.append((Box(x,y,w,h),mask[y:y+h,x:x+w]))
    return result


def find_faces(image,table,reader):
    faces=[]; unreadable=[]
    for group,inside in card_groups(image,table):
        tile=group.crop(image)
        hsv=cv2.cvtColor(tile,cv2.COLOR_BGR2HSV)
        inside=cv2.erode(inside,np.ones((5,5),np.uint8))>0
        ink=inside&((hsv[:,:,2]<135)|((hsv[:,:,1]>85)&(hsv[:,:,2]<250)))
        count,labels,stats,_=cv2.connectedComponentsWithStats(ink.astype(np.uint8))
        components=[]
        for i in range(1,count):
            x,y,w,h,area=stats[i]
            if h<group.h*.12 or area<group.h*group.h*.007:continue
            components.append((Box(int(x),int(y),int(w),int(h)),labels==i))
        for suit_box,suit_mask in components:
            if not (suit_box.cy>group.h*.51 and suit_box.h>group.h*.18):continue
            color=ink_color(tile,suit_mask)
            suit,score=read_suit(suit_mask,color)
            if suit is None:continue
            ranks=[(box,mask) for box,mask in components
                   if box.cy<group.h*.55 and box.h<group.h*.53
                   and -.12*group.h<suit_box.cx-box.cx<.48*group.h
                   and ink_color(tile,mask)==color]
            if not ranks:
                unreadable.append(group);continue
            # Merge the two glyphs in '10', but keep adjacent overlapped cards apart.
            ranks.sort(key=lambda v:abs(v[0].cx-(suit_box.cx-.18*group.h)))
            chosen=ranks[0]
            merged=chosen[1].copy()
            for box,mask in ranks[1:]:
                a=chosen[0]
                if abs(box.cy-a.cy)<.15*group.h and abs(box.cx-a.cx)<.35*group.h:
                    merged|=mask
            glyph=trim(merged)
            if glyph is None:continue
            rank,rank_score=reader.rank(glyph)
            if rank is None:
                unreadable.append(group);continue
            box=chosen[0]
            faces.append(Face(rank+suit,Box(group.x+box.x,group.y+box.y,box.w,box.h),min(score,rank_score),group))
    return faces,unreadable


def arrange_faces(faces,table):
    hero=[c for c in faces if c.box.cy>table.y+.76*table.h
          and table.x+.23*table.w<c.box.cx<table.x+.80*table.w]
    if len(hero)!=2:raise ValueError('내 홀 카드 2장을 자동 판독하지 못했습니다. 카드가 가려지지 않게 해 주세요.')
    hero.sort(key=lambda c:c.box.x)
    board=[c for c in faces if table.y+.16*table.h<c.box.cy<table.y+.64*table.h
           and table.x+.13*table.w<c.box.cx<table.x+.87*table.w]
    if len(board) not in (0,3,4,5):raise ValueError('공통 카드 일부를 읽지 못했습니다. 화면이 선명하게 보이도록 하세요.')
    board.sort(key=lambda c:c.box.x)
    if board and max(c.box.cy for c in board)-min(c.box.cy for c in board)>table.h*.08:
        raise ValueError('공통 카드 행을 확정하지 못했습니다.')
    return hero,board


def number(text):
    if not re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?',text):return None
    return float(text.replace(',',''))


def back_boxes(image,table):
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    gold=cv2.inRange(hsv,(8,90,65),(38,255,255))
    gold=cv2.morphologyEx(gold,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    contours,_=cv2.findContours(gold,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    boxes=[]
    for c in contours:
        x,y,w,h=cv2.boundingRect(c)
        if .10*table.h<h<.35*table.h and .25<w/h<2.2:
            boxes.append(Box(x,y,w,h))
    return boxes


def nickname_line(image,box):
    """Detect text above a stack without needing Korean language OCR data."""
    roi=Box(box.x-3,box.y-round(2.2*box.h),max(box.w,4*box.h)+6,round(2.05*box.h)).crop(image)
    if not roi.size:return False
    hsv=cv2.cvtColor(roi,cv2.COLOR_BGR2HSV)
    if float(np.median(hsv[:,:,1]))>70:return False
    gray=cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY)
    mask=(gray<140) if float(np.median(gray))>160 else (gray>170)
    count,_,stats,_=cv2.connectedComponentsWithStats(mask.astype(np.uint8))
    glyphs=[s for s in stats[1:] if box.h*.3<=s[3]<=box.h*1.7 and s[4]>=box.h*.5 and s[2]<roi.shape[1]*.8]
    return len(glyphs)>=3


class PokerNowRecognizer:
    always_analyze=True

    def __init__(self,reader=None,numbers=None):
        self.reader=reader if reader is not None else TesseractReader()
        self.numbers=numbers if numbers is not None else TesseractNumbers()
        self.boxes=[]
        self.table=None
        self.number_cache={}
        self.dealer_cache={}

    @staticmethod
    def frame(image):
        if image is None or image.ndim!=3 or image.shape[2]!=3:raise ValueError('화면 이미지가 올바르지 않습니다.')
        h,w=image.shape[:2]
        if w<700 or h<450:raise ValueError('테이블이 너무 작습니다. 브라우저를 확대하세요.')
        return cv2.resize(image,(1920,round(h*1920/w)),interpolation=cv2.INTER_AREA) if w>1920 else image

    def signature(self,image):
        frame=self.frame(image)
        if not self.boxes:return frame.tobytes()
        geometry=repr(sorted((b.x,b.y,b.w,b.h) for b,_ in card_groups(frame,self.table))
                      +sorted((b.x,b.y,b.w,b.h) for b in back_boxes(frame,self.table))).encode() if self.table else b''
        return repr(frame.shape).encode()+geometry+b''.join(b.crop(frame).tobytes() for b in self.boxes)

    def amount(self,image,box):
        # Whitespace for OCR, bounded to the actual screenshot.
        h,w=image.shape[:2]
        padded=Box(max(0,box.x-3),max(0,box.y-3),min(box.w+6,w-max(0,box.x-3)),min(box.h+6,h-max(0,box.y-3)))
        crop=padded.crop(image);key=(crop.shape,hashlib.sha256(crop.tobytes()).digest())
        if key not in self.number_cache:
            if len(self.number_cache)>100:self.number_cache.clear()
            self.number_cache[key]=self.numbers.read(crop)
        return self.number_cache[key]

    def dealer(self,image,table):
        white=cv2.inRange(image,(210,210,210),(255,255,255))
        contours,_=cv2.findContours(white,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        result=[]
        for c in contours:
            x,y,w,h=cv2.boundingRect(c)
            if not (.045*table.h<h<.12*table.h and .7<w/h<1.5 and cv2.contourArea(c)>.6*w*h):continue
            box=Box(x,y,w,h);tile=box.crop(image)
            key=(tile.shape,tile.tobytes())
            if key not in self.dealer_cache:
                hsv=cv2.cvtColor(tile,cv2.COLOR_BGR2HSV)
                blue=(hsv[:,:,0]>90)&(hsv[:,:,0]<145)&(hsv[:,:,1]>80)&(hsv[:,:,2]>70)
                glyph=trim(blue)
                value=None
                if glyph is not None and glyph.shape[0]>h*.3:
                    ink=cv2.resize(glyph.astype(np.uint8)*255,None,fx=3,fy=3,interpolation=cv2.INTER_NEAREST)
                    text=cv2.copyMakeBorder(255-ink,20,20,20,20,cv2.BORDER_CONSTANT,value=255)
                    readings=[self.reader.words(text,psm,'D') for psm in (6,13)]
                    if all(len(r)==1 and r[0].text=='D' and r[0].confidence>=.8 for r in readings):
                        value=min(r[0].confidence for r in readings)
                if len(self.dealer_cache)>32:self.dealer_cache.clear()
                self.dealer_cache[key]=value
            confidence=self.dealer_cache[key]
            if confidence is not None:result.append(Word('D',confidence,box))
        return result

    def analyze(self,image):
        result=Observation()
        try:
            image=self.frame(image)
            table=table_bounds(image)
            faces,unreadable=find_faces(image,table,self.reader)
            hero,board=arrange_faces(faces,table)
            geometric_board=[g for g,_ in card_groups(image,table)
                             if table.y+.15*table.h<g.cy<table.y+.65*table.h
                             and table.x+.13*table.w<g.cx<table.x+.87*table.w
                             and .6<g.w/g.h<1.15]
            if len(geometric_board)!=len(board):
                raise ValueError('보드의 카드 수와 판독 결과가 다릅니다. 일부 카드를 읽지 못했습니다.')
            # Any unresolved suit/rank within the board or hero area invalidates it.
            relevant=[b for b in unreadable if (table.y+.12*table.h<b.cy<table.y+.65*table.h)
                      or (b.cy>table.y+.76*table.h and table.x+.23*table.w<b.cx<table.x+.80*table.w)]
            if relevant:raise ValueError('카드 일부의 숫자 또는 무늬가 불확실합니다.')
            words=self.reader.words(image)
            numeric=[w for w in words if number(w.text) is not None and w.confidence>=.85]
            pots=[w for w in numeric if table.x+.33*table.w<w.box.cx<table.x+.67*table.w
                  and table.y+.04*table.h<w.box.cy<table.y+.28*table.h]
            if len(pots)!=1:raise ValueError('팟 숫자를 자동으로 확정하지 못했습니다.')
            pot,pot_conf=self.amount(image,pots[0].box)
            if pot is None or pot!=number(pots[0].text):raise ValueError('팟 OCR 인식 실패 또는 판독 불일치')
            backs=back_boxes(image,table)
            front=[c.group for c in faces]
            seats=[]
            for token in numeric:
                b=token.box
                on_card=any(abs(c.box.cx-b.cx)<c.group.h*.65
                            and c.box.y-c.group.h*.05<b.cy<c.box.y+c.group.h*.8 for c in faces)
                if token is pots[0] or on_card:continue
                if not (table.y-.12*table.h<b.cy<table.y+1.22*table.h):continue
                if b.h<table.h*.022:continue
                # Require a card group beside the stack to avoid HUD/bet numbers.
                near=[c for c in front+backs if abs(c.cy-b.cy)<table.h*.22
                      and -table.h*.1<b.cx-c.cx<table.h*.65]
                if not near:continue
                # A name line above is a second independent seat cue. It may be
                # low-confidence when an English OCR encounters a Korean name.
                names=[w for w in words if number(w.text) is None and len(w.text)>=2
                       and 0<b.y-w.box.cy<table.h*.09 and abs(w.box.cx-b.cx)<table.h*.24]
                if not names and not nickname_line(image,b):continue
                stack,confidence=self.amount(image,b)
                if stack is None or stack!=number(token.text):raise ValueError('플레이어 스택 OCR 인식 실패 또는 판독 불일치')
                seats.append((token,stack,confidence))
            # Deduplicate nearby fragments rather than counting text twice.
            seats.sort(key=lambda v:(v[0].box.y,v[0].box.x))
            for a,b in zip(seats,seats[1:]):
                if abs(a[0].box.cy-b[0].box.cy)<table.h*.025 and abs(a[0].box.cx-b[0].box.cx)<table.h*.12:
                    raise ValueError('플레이어 스택이 중복/분할 인식됐습니다.')
            if not 2<=len(seats)<=9:raise ValueError('상대 수와 스택을 확정하지 못했습니다. 플레이어 영역을 가리지 마세요.')
            hero_x=sum(c.box.cx for c in hero)/2;hero_y=sum(c.box.cy for c in hero)/2
            distances=[abs(s[0].box.cy-hero_y)+abs(s[0].box.cx-hero_x)*.25 for s in seats]
            hero_index=int(np.argmin(distances))
            if distances[hero_index]>table.h*.26:raise ValueError('내 스택 위치를 확정하지 못했습니다.')
            my_seat=seats[hero_index]
            ordered=[my_seat]+[s for i,s in enumerate(seats) if i!=hero_index]
            # In the supplied theme, the current player panel is light and the
            # others dark. Read actual background around the stack, not the glyph.
            light=[]
            for i,(token,_,_) in enumerate(ordered):
                b=token.box
                panel=Box(b.x-5,b.y-5,b.w+10,b.h+10).crop(image)
                hsv=cv2.cvtColor(panel,cv2.COLOR_BGR2HSV)
                light.append(float(((hsv[:,:,2]>210)&(hsv[:,:,1]<45)).mean())>.55)
            hero_turn=True if light[0] and sum(light)==1 else (False if not light[0] and sum(light)==1 else None)
            call,call_conf,action_box=self.read_action(image,words,table,hero_turn,self.amount)
            dealer=self.dealer(image,table)
            position='UNKNOWN'
            for d in dealer:
                locations=[(abs(d.box.cx-s[0].box.cx)*.5+abs(d.box.cy-s[0].box.cy),i) for i,s in enumerate(ordered)]
                distance,index=min(locations)
                if distance<table.h*.4:
                    if index==0:position='BTN'
                    elif len(ordered)==2:position='BB'
            result.state=GameState(tuple(c.card for c in hero),tuple(c.card for c in board),pot,call,
                                   tuple(s[1] for s in ordered),len(ordered)-1,position,hero_turn=hero_turn)
            result.confidence={**{f'card{i}':c.confidence for i,c in enumerate(hero+board)},
                               'pot':pot_conf,**{f'stack{i}':s[2] for i,s in enumerate(ordered)}}
            if call is not None:result.confidence['to_call']=call_conf
            self.table=table
            number_boxes=[pots[0].box]+[s[0].box for s in ordered]
            expanded=[Box(b.x-4,b.y-4,b.w*2+8,b.h+8) for b in number_boxes]
            self.boxes=list({c.group for c in faces})+expanded
            # Include all action controls and seat brightness; exclude clocks/chat.
            self.boxes+=[Box(s[0].box.x-5,s[0].box.y-5,s[0].box.w+10,s[0].box.h+10) for s in ordered]
            if action_box:self.boxes.append(Box(action_box.x-6,action_box.y-4,action_box.w*2+12,action_box.h+8))
            self.boxes += [d.box for d in dealer]
        except (ValueError,TypeError,cv2.error) as exc:
            self.boxes=[]
            self.table=None
            result.errors.append(f'자동 인식 실패: {exc}')
        return result

    @staticmethod
    def read_action(image,words,table,hero_turn,amount_reader=None):
        if hero_turn is not True:return None,0,None
        candidates=[w for w in words if w.text.upper() in ('CHECK','CALL','FOLD')
                    and w.box.cy>table.y+.92*table.h and w.box.cx>table.x+.45*table.w]
        if not candidates:return None,0,None
        bottom=max(w.box.cy for w in candidates)
        row=[w for w in words if abs(w.box.cy-bottom)<table.h*.06 and w.box.cx>table.x+.4*table.w]
        labels={w.text.upper() for w in row if w.confidence>=.85}
        if 'OR' in labels or 'FOLD' not in labels or not labels.intersection({'BET','RAISE','CALL','ALL-IN'}):return None,0,None
        checks=[w for w in row if w.text.upper()=='CHECK' and w.confidence>=.85]
        calls=[w for w in row if w.text.upper()=='CALL' and w.confidence>=.85]
        if checks and not calls:return 0.0,checks[0].confidence,checks[0].box
        if len(calls)==1:
            amounts=[w for w in row if number(w.text.strip('()')) is not None
                     and abs(w.box.cx-calls[0].box.cx)<table.h*.22]
            if len(amounts)==1 and amount_reader is not None:
                value,confidence=amount_reader(image,amounts[0].box)
                if value==number(amounts[0].text.strip('()')):
                    return value,min(calls[0].confidence,confidence),amounts[0].box
        return None,0,None
