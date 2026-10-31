"""Automatic PokerNow-style face-card layout. Pixels only; no saved calibration.

The reader deliberately rejects uncertain cards, ambiguous seats, and hidden
call values. Only a positively detected action state can produce advice.
"""
from dataclasses import dataclass,replace
from math import hypot
import hashlib
import re
import cv2
import numpy as np
from src.models.state import GameState
from src.models.table import Seat,TableSnapshot
from src.vision.seats import TableTracker,empty_rectangles,betting_pills,relative,ring_radius,polar,angle_distance,seat_position
from src.vision.ocr import Box,Word,TesseractReader
from src.vision.recognizer import Observation,CardReading
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
        if cv2.contourArea(c)>.025*w*h and bw>1.3*bh and bw>.20*w:
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
        if not (table.x-.4*table.w<x<table.x+1.4*table.w and table.y-.45*table.h<y<table.y+1.5*table.h):continue
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


def arrange_faces(faces,table,hero_anchor=None):
    # Board cards form a row of 3..5 separate, upright faces inside the felt.
    # No hero-at-the-bottom assumption is used.
    central=[c for c in faces if .6<c.group.w/c.group.h<1.15
             and ring_radius(*relative(c.group,table))<.82]
    rows=[]
    for card in central:
        row=[c for c in central if abs(c.group.cy-card.group.cy)<table.h*.07]
        if len({c.group for c in row})==len(row) and 3<=len(row)<=5:
            ordered=sorted(row,key=lambda c:c.group.cx)
            gaps=[b.group.cx-a.group.cx for a,b in zip(ordered,ordered[1:])]
            if gaps and max(gaps)<min(gaps)*1.35:rows.append(ordered)
    board=max(rows,key=len) if rows else []
    if len(central)>=3 and not board:raise ValueError('공통 카드 일부를 읽지 못했습니다.')
    remaining=[c for c in faces if c not in board]
    pairs=[]
    for i,a in enumerate(remaining):
        for b in remaining[i+1:]:
            if abs(a.box.cy-b.box.cy)<table.h*.10 and abs(a.box.cx-b.box.cx)<table.h*.32:
                pairs.append(sorted([a,b],key=lambda c:c.box.x))
    if hero_anchor is not None:
        pairs.sort(key=lambda pair:sum(hypot(c.box.cx-hero_anchor[0],c.box.cy-hero_anchor[1]) for c in pair))
        if not pairs:raise ValueError('지정한 내 닉네임 주변에서 홀 카드 2장을 찾지 못했습니다.')
        hero=pairs[0]
    elif len(pairs)==1:hero=pairs[0]
    else:raise ValueError('내 홀 카드 2장을 확정하지 못했습니다. 공개 카드가 여러 쌍이면 내 닉네임을 입력하세요.')
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
            tile=image[y:y+h,x:x+w]
            if float(np.median(cv2.cvtColor(tile,cv2.COLOR_BGR2HSV)[:,:,2]))<125:boxes.append(Box(x,y,w,h))
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    edges=cv2.Canny(gray,35,90)
    contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        polygon=cv2.approxPolyDP(c,.025*cv2.arcLength(c,True),True)
        if len(polygon)!=4:continue
        x,y,w,h=cv2.boundingRect(polygon)
        if not (.10*table.h<h<.35*table.h and .45<w/h<.95):continue
        outline=np.zeros((h,w),np.uint8)
        local=polygon-np.array([[[x,y]]])
        cv2.polylines(outline,[local],True,255,3)
        tile_hsv=hsv[y:y+h,x:x+w]
        neutral=(tile_hsv[:,:,1]<65)&(tile_hsv[:,:,2]>125)
        gold_edge=(tile_hsv[:,:,0]>=8)&(tile_hsv[:,:,0]<=38)&(tile_hsv[:,:,1]>90)&(tile_hsv[:,:,2]>65)
        if float(neutral[outline>0].mean())<.30 and float(gold_edge[outline>0].mean())<.40:continue
        box=Box(x,y,w,h)
        rx,ry=relative(box,table)
        if not .72<ring_radius(rx,ry)<1.6:continue
        tile=box.crop(image)
        if float(np.median(cv2.cvtColor(tile,cv2.COLOR_BGR2HSV)[:,:,2]))>125:continue
        if not any(hypot(b.cx-box.cx,b.cy-box.cy)<h*.3 for b in boxes):boxes.append(box)
    return boxes


def card_owner(group, players, table):
    """Use the gap to a name/stack panel, not a rank glyph's centre.

    A tilted pair can be above or to the left of its panel. In crowded
    tables the rank centre may be closer to a different player's centre.
    """
    candidates=[]
    for seat,stack,_ in players:
        panel=Box(stack.x,round(stack.y-stack.h*1.7),stack.w,round(stack.h*2.7))
        dx=max(panel.x-group.x-group.w,group.x-panel.x-panel.w,0)/table.w
        dy=max(panel.y-group.y-group.h,group.y-panel.y-panel.h,0)/table.h
        gap=hypot(dx,dy)
        centre=hypot((group.cx-panel.cx)/table.w,(group.cy-panel.cy)/table.h)
        candidates.append((gap+.08*centre,centre,seat.slot_id))
    candidates.sort()
    if not candidates or candidates[0][0]>.18 or candidates[0][1]>.42:return None
    if len(candidates)>1 and candidates[1][0]-candidates[0][0]<.018:return None
    return candidates[0][2]


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

    def __init__(self,reader=None,numbers=None,hero_name=""):
        self.reader=reader if reader is not None else TesseractReader()
        self.numbers=numbers if numbers is not None else TesseractNumbers()
        self.boxes=[]
        self.table=None
        self.number_cache={}
        self.dealer_cache={}
        self.tracker=TableTracker()
        self.hero_name=hero_name.strip().casefold()
        self.context_cache={}
        self.slot_cache={}
        self.pill_cache={}

    def set_cancel(self,event):
        self.reader.cancel=event
        self.numbers.cancel=event

    @staticmethod
    def frame(image):
        if image is None or image.ndim!=3 or image.shape[2]!=3:raise ValueError('화면 이미지가 올바르지 않습니다.')
        h,w=image.shape[:2]
        if w<480 or h<260:raise ValueError('테이블이 너무 작습니다. 브라우저를 확대하세요.')
        # Locate on a cheap preview, then crop the original pixels, including
        # the surrounding seats and controls. Browser/desktop margins are not
        # treated as game coordinates and do not shrink the OCR input.
        ratio=min(1,1920/w)
        preview=cv2.resize(image,(round(w*ratio),round(h*ratio)),interpolation=cv2.INTER_AREA) if ratio<1 else image
        try:
            t=table_bounds(preview)
            x=max(0,round((t.x-t.w*.35)/ratio));right=min(w,round((t.x+t.w*1.35)/ratio))
            y=max(0,round((t.y-t.h*.35)/ratio));bottom=min(h,round((t.y+t.h*1.55)/ratio))
            image=image[y:bottom,x:right]
        except ValueError:pass
        h,w=image.shape[:2]
        return cv2.resize(image,(1920,round(h*1920/w)),interpolation=cv2.INTER_AREA if w>1920 else cv2.INTER_CUBIC) if w!=1920 else image

    def signature(self,image):
        frame=self.frame(image)
        if not self.boxes:return frame.tobytes()
        geometry=repr(sorted((b.x,b.y,b.w,b.h) for b,_ in card_groups(frame,self.table))
                      +sorted((b.x,b.y,b.w,b.h) for b in back_boxes(frame,self.table))).encode() if self.table else b''
        return repr(frame.shape).encode()+geometry+b''.join(b.crop(frame).tobytes() for b in self.boxes)

    def amount(self,image,box,expected=None):
        h,w=image.shape[:2]
        values=[]
        for pad in (3,8,12):
            padded=Box(max(0,box.x-pad),max(0,box.y-pad),min(box.w+2*pad,w-max(0,box.x-pad)),min(box.h+2*pad,h-max(0,box.y-pad)))
            crop=padded.crop(image);key=(crop.shape,hashlib.sha256(crop.tobytes()).digest())
            if key not in self.number_cache:
                if len(self.number_cache)>160:self.number_cache.clear()
                self.number_cache[key]=self.numbers.read(crop)
            value,score=self.number_cache[key]
            if value is not None:
                if expected is not None and value==expected:return value,score
                values.append((value,score))
        if expected is not None:return None,0
        return max(values,key=lambda pair:pair[1]) if values and len({v for v,_ in values})==1 else (None,0)

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
                    readings=[self.reader.words(text,psm,'D') for psm in (6,13,10)]
                    valid=[r[0].confidence for r in readings if len(r)==1 and r[0].text=='D' and r[0].confidence>=.8]
                    if len(valid)>=2:value=min(valid)
                if len(self.dealer_cache)>32:self.dealer_cache.clear()
                self.dealer_cache[key]=value
            confidence=self.dealer_cache[key]
            if confidence is not None:result.append(Word('D',confidence,box))
        return result

    def slot_number(self,image,box):
        roi=Box(box.x+5,box.y+4,round(box.w*.28),round(box.h*.40)).crop(image)
        if not roi.size:return None
        key=(roi.shape,hashlib.sha256(roi.tobytes()).digest())
        if key in self.slot_cache:return self.slot_cache[key]
        gray=cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY)
        gray=cv2.normalize(gray,None,0,255,cv2.NORM_MINMAX)
        _,binary=cv2.threshold(gray,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
        if np.median(gray)>127:binary=255-binary
        count,_,stats,_=cv2.connectedComponentsWithStats(binary)
        glyphs=[s for s in stats[1:] if s[3]>roi.shape[0]*.20 and s[3]<roi.shape[0]*.95 and s[2]<roi.shape[1]*.65 and s[0]>1 and s[1]>0]
        result=None
        if glyphs:
            x=min(s[0] for s in glyphs);y=min(s[1] for s in glyphs)
            right=max(s[0]+s[2] for s in glyphs);bottom=max(s[1]+s[3] for s in glyphs)
            glyph=255-binary[y:bottom,x:right]
            glyph=cv2.copyMakeBorder(glyph,6,6,6,6,cv2.BORDER_CONSTANT,value=255)
            value,score=self.numbers.read(cv2.cvtColor(glyph,cv2.COLOR_GRAY2BGR))
            if value is not None and value.is_integer() and 1<=value<=10:result=int(value)
        if len(self.slot_cache)>80:self.slot_cache.clear()
        self.slot_cache[key]=result
        return result

    @staticmethod
    def numeric_suffix(image,word,digits):
        tile=word.box.crop(image)
        gray=cv2.cvtColor(tile,cv2.COLOR_BGR2GRAY)
        _,binary=cv2.threshold(gray,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
        if np.median(gray)>140:binary=255-binary
        count,_,stats,_=cv2.connectedComponentsWithStats(binary)
        glyphs=[s for s in stats[1:] if s[3]>.4*word.box.h and s[4]>2]
        glyphs.sort(key=lambda s:s[0])
        if len(glyphs)<digits:return None
        glyphs=glyphs[-digits:]
        x=min(s[0] for s in glyphs);y=min(s[1] for s in glyphs)
        right=max(s[0]+s[2] for s in glyphs);bottom=max(s[1]+s[3] for s in glyphs)
        return Box(word.box.x+int(x),word.box.y+int(y),int(right-x),int(bottom-y))

    def bright_pot_rows(self,image,table):
        mask=(np.min(image,axis=2)>185).astype(np.uint8)
        count,_,stats,_=cv2.connectedComponentsWithStats(mask)
        glyphs=[]
        for x,y,w,h,area in stats[1:]:
            if not (.016*table.h<h<.15*table.h and area>8):continue
            if not (table.x+.25*table.w<x+w/2<table.x+.76*table.w and table.y-.12*table.h<y+h/2<table.y+.29*table.h):continue
            glyphs.append(Box(int(x),int(y),int(w),int(h)))
        rows=[]
        for b in sorted(glyphs,key=lambda b:b.cy):
            same=next((row for row in rows if abs(row[0].cy-b.cy)<max(row[0].h,b.h)*.45 and max(row[0].h,b.h)<min(row[0].h,b.h)*1.8),None)
            if same is None:rows.append([b])
            else:same.append(b)
        result=[]
        self.pot_row_boxes=[]
        for row in rows:
            row.sort(key=lambda b:b.x)
            groups=[]
            for b in row:
                if not groups or b.x-(groups[-1][-1].x+groups[-1][-1].w)>b.h*1.7:groups.append([b])
                else:groups[-1].append(b)
            for group in groups:
                x=min(b.x for b in group);y=min(b.y for b in group);right=max(b.x+b.w for b in group);bottom=max(b.y+b.h for b in group)
                self.pot_row_boxes.append(Box(x,y,right-x,bottom-y))
                box=Box(max(0,x-10),max(0,y-10),right-x+20,bottom-y+20);crop=box.crop(image)
                key=('potrow',crop.shape,hashlib.sha256(crop.tobytes()).digest())
                if key not in self.context_cache:self.context_cache[key]=self.reader.words(crop,7)
                for word in self.context_cache[key]:
                    b=word.box
                    result.append(Word(word.text,word.confidence,Box(box.x+b.x,box.y+b.y,b.w,b.h)))
        return result

    def contextual_words(self,image,table,words):
        regions=[(Box(round(table.x+table.w*.23),round(table.y-table.h*.10),round(table.w*.54),round(table.h*.43)),6),
                 (Box(round(table.x+table.w*.18),round(table.y+table.h*.57),round(table.w*.64),round(table.h*.37)),6)]
        regions += [(b,6) for b in empty_rectangles(image,table)]
        regions += [(b,7) for b in betting_pills(image,table)]
        merged=list(words)
        for word in self.bright_pot_rows(image,table):
            duplicate=next((i for i,w in enumerate(merged) if w.text==word.text and hypot(w.box.cx-word.box.cx,w.box.cy-word.box.cy)<max(5,word.box.h*.6)),None)
            if duplicate is None:merged.append(word)
            elif word.confidence>merged[duplicate].confidence:merged[duplicate]=word
        for box,psm in regions:
            x=max(0,box.x);y=max(0,box.y);crop=Box(x,y,box.w,box.h).crop(image)
            if not crop.size:continue
            key=(crop.shape,psm,hashlib.sha256(crop.tobytes()).digest())
            if key not in self.context_cache:
                if len(self.context_cache)>80:self.context_cache.clear()
                self.context_cache[key]=self.reader.words(crop,psm)
            for word in self.context_cache[key]:
                b=word.box;global_word=Word(word.text,word.confidence,Box(x+b.x,y+b.y,b.w,b.h))
                duplicate=next((i for i,w in enumerate(merged) if w.text==word.text and hypot(w.box.cx-global_word.box.cx,w.box.cy-global_word.box.cy)<max(5,b.h*.6)),None)
                if duplicate is None:merged.append(global_word)
                elif merged[duplicate].confidence<word.confidence:merged[duplicate]=global_word
        return merged

    def pots(self,image,words,table,faces=()):
        area=[w for w in words if table.x+.23*table.w<w.box.cx<table.x+.77*table.w
              and table.y-.10*table.h<w.box.cy<table.y+.31*table.h]
        groups=[g for g,_ in card_groups(image,table)]
        numeric=[w for w in area if number(w.text) is not None and w.confidence>=.85 and not any(g.contains(w.box) for g in groups)]
        # A lone preflop pot '0' is frequently emitted as 'O' or omitted by
        # English OCR. Independently read detected bright digit rows using the
        # numeric two-view reader; never substitute a missing pot with zero.
        for box in getattr(self,'pot_row_boxes',[]):
            if not (table.y+.035*table.h<box.cy<table.y+.31*table.h):continue
            if any(g.contains(box) for g in groups):continue
            if any(abs(w.box.cx-box.cx)<box.h and abs(w.box.cy-box.cy)<box.h*.5 for w in numeric):continue
            value,score=self.amount(image,box)
            if value is not None and score>=.85:
                numeric.append(Word(format(value,'g'),score,box))
        primary_options=[]
        for w in numeric:
            if w.box.cy<table.y+.035*table.h:continue
            pad=max(8,round(w.box.h*.7))
            patch=Box(w.box.x-pad,w.box.y-pad,w.box.w+2*pad,w.box.h+2*pad).crop(image)
            value=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)[:,:,2]
            # Test surrounding background, not a tightly cropped white '0'.
            border=np.concatenate((value[:3].ravel(),value[-3:].ravel(),value[:,:3].ravel(),value[:,-3:].ravel()))
            if np.median(border)>180:continue
            primary_options.append(w)
        if not primary_options:raise ValueError('팟 숫자를 확정하지 못했습니다.')
        primary=max(primary_options,key=lambda w:w.box.h)
        settled,confidence=self.amount(image,primary.box,number(primary.text))
        if settled is None or settled!=number(primary.text):raise ValueError('중앙 팟 OCR 불일치')
        total=None;used=[primary.box]
        labels=[w for w in area if w.text.lower().rstrip(':')=='total']
        totals=[]
        for label in labels:
            for w in numeric:
                if w is primary:continue
                if abs(w.box.cy-label.box.cy)<label.box.h*1.5 and 0<=w.box.x-label.box.x<label.box.w+table.w*.12:
                    value,score=self.amount(image,w.box,number(w.text))
                    if value is not None and value<settled:raise ValueError('총 팟이 중앙 팟보다 작아 판독을 보류합니다.')
                    if value==number(w.text) and value>=settled:
                        totals.append(value);used.append(w.box);confidence=min(confidence,score)
        for w in area:
            match=re.fullmatch(r'total[: ]*([\d,]+(?:\.\d+)?)',w.text,re.IGNORECASE)
            if match:
                value=number(match[1]);box=self.numeric_suffix(image,w,len(match[1].replace(',','').replace('.','')))
                if box and value is not None:
                    confirmed,score=self.amount(image,box,value)
                    if confirmed==value and value>=settled:totals.append(value);used.append(box);confidence=min(confidence,score)
        if len(set(totals))>1:raise ValueError('총 팟 표시가 서로 다릅니다.')
        if totals:total=totals[0]
        return settled,total,confidence,used

    def players(self,image,words,table,faces,pot_boxes):
        numeric=[w for w in words if number(w.text) is not None and w.confidence>=.85]
        players=[]
        for token in numeric:
            b=token.box
            if any(p.contains(b) for p in pot_boxes):continue
            if any(abs(c.box.cx-b.cx)<c.group.h*.65 and c.box.y-c.group.h*.05<b.cy<c.box.y+c.group.h*.8 for c in faces):continue
            x,y=relative(b,table)
            if (x>1 or x<0) and y<.05:continue  # Table header blinds are not a player stack.
            if not .72<ring_radius(x,y)<1.70 or b.h<table.h*.017:continue
            tile=b.crop(image)
            if not tile.size:continue
            # Colored trophy/counter/bet badges are not player stacks.
            surround=Box(b.x-4,b.y-3,b.w+8,b.h+6).crop(image)
            hsv=cv2.cvtColor(surround,cv2.COLOR_BGR2HSV)
            if float(np.median(hsv[:,:,1]))>75:continue
            names=[w for w in words if number(w.text) is None and len(w.text)>=2
                   and 0<b.y-w.box.cy<table.h*.09 and abs(w.box.cx-b.cx)<table.h*.24]
            if not names and not nickname_line(image,b):continue
            stack,score=self.amount(image,b,number(token.text))
            if stack is None or stack!=number(token.text):continue
            name=min(names,key=lambda w:abs(w.box.cx-b.cx)+abs(w.box.cy-b.y)).text if names else ''
            if any(hypot(x-p[0].x,y-p[0].y)<.07 for p in players):continue
            seat=Seat(f'tmp{len(players)}',x,y,occupied=True,name=name,stack=stack)
            players.append((seat,b,score))
        return players

    def pill_amount(self,image,pill):
        tile=pill.crop(image);key=(tile.shape,hashlib.sha256(tile.tobytes()).digest())
        if key in self.pill_cache:return self.pill_cache[key]
        hsv=cv2.cvtColor(tile,cv2.COLOR_BGR2HSV)
        background=cv2.inRange(hsv,(25,90,130),(85,255,255))
        contours,_=cv2.findContours(background,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        value=None;score=0
        if contours:
            inside=np.zeros(background.shape,np.uint8);cv2.drawContours(inside,[max(contours,key=cv2.contourArea)],-1,255,-1)
            inside=cv2.erode(inside,np.ones((5,5),np.uint8))>0
            ink=(cv2.cvtColor(tile,cv2.COLOR_BGR2GRAY)<120)&inside
            glyph=trim(ink)
            if glyph is not None:
                clean=cv2.copyMakeBorder(255-glyph.astype(np.uint8)*255,10,10,10,10,cv2.BORDER_CONSTANT,value=255)
                value,score=self.numbers.read(cv2.cvtColor(clean,cv2.COLOR_GRAY2BGR))
                words=self.reader.words(clean,7)
                if len(words)!=1 or number(words[0].text)!=value:value=None
        if len(self.pill_cache)>80:self.pill_cache.clear()
        self.pill_cache[key]=(value,score)
        return value,score

    def layout(self,image,words,table,faces,pot_boxes):
        players=self.players(image,words,table,faces,pot_boxes)
        slots=[]
        for box in empty_rectangles(image,table):
            x,y=relative(box,table)
            n=None if any(box.contains(b) for _,b,_ in players) else self.slot_number(image,box)
            slots.append(Seat(f'empty{len(slots)}',x,y,number=n,occupied=False if n is not None else None))
        for seat,_,_ in players:
            matches=sorted((hypot(seat.x-s.x,seat.y-s.y),i) for i,s in enumerate(slots) if s.occupied is not True)
            if matches and matches[0][0]<.22:
                i=matches[0][1];slots[i]=replace(seat,slot_id=slots[i].slot_id,number=slots[i].number)
            else:slots.append(seat)
        # Identical OCR numbers on different outlines are not trusted as site IDs.
        counts={n:sum(s.number==n for s in slots) for n in {s.number for s in slots if s.number is not None}}
        slots=[replace(s,number=None) if s.number is not None and counts[s.number]>1 else s for s in slots]
        occupied=[s for s in slots if s.occupied is True]
        # Rebind panel boxes to the unique slot IDs before card association.
        panel_players=[(next(s for s in occupied if hypot(s.x-p.x,s.y-p.y)<.001),b,c) for p,b,c in players]
        def assign(box):return card_owner(box,panel_players,table)
        active=set();card_owners=[]
        self.unassigned_outer=0
        for box in list({c.group for c in faces})+back_boxes(image,table):
            identifier=assign(box)
            if identifier:active.add(identifier);card_owners.append((box,identifier))
            elif ring_radius(*relative(box,table))>.82:self.unassigned_outer+=1
        angles={s.slot_id:polar(s.x,s.y) for s in occupied}
        def angular(box):
            angle=polar(*relative(box,table))
            values=sorted((angle_distance(angle,a),key) for key,a in angles.items())
            return values[0][1] if values and values[0][0]<.50 and (len(values)==1 or values[1][0]-values[0][0]>.10) else None
        bets={};pills=betting_pills(image,table);unread=0
        for pill in pills:
            values=[w for w in words if pill.contains(w.box) and number(w.text) is not None and w.confidence>=.85]
            amounts={number(w.text) for w in values}
            if len(amounts)!=1:
                value,score=self.pill_amount(image,pill);identifier=angular(pill)
                if value is None or identifier is None:unread+=1;continue
                if identifier in bets:unread+=1;continue
                bets[identifier]=value;active.add(identifier);continue
            expected=next(iter(amounts));value=None
            for word in sorted(values,key=lambda w:w.confidence,reverse=True):
                value,score=self.amount(image,word.box,expected)
                if value==expected:break
            identifier=angular(pill)
            if value!=expected or identifier is None:unread+=1;continue
            if identifier in bets:unread+=1;continue
            bets[identifier]=value;active.add(identifier)
        actions={}
        for w in words:
            label=w.text.lower()
            if label not in ('check','fold','call','bet','raise') or w.confidence<.75:continue
            if ring_radius(*relative(w.box,table))>.97:continue
            near=sorted((hypot((w.box.cx-b.cx)/table.w,(w.box.cy-b.cy)/table.h),owner) for b,owner in card_owners)
            identifier=near[0][1] if near and near[0][0]<.30 and (len(near)==1 or near[1][1]==near[0][1] or near[1][0]-near[0][0]>.03) else angular(w.box)
            if identifier:actions[identifier]=label
        offline={angular(w.box) for w in words if w.text.upper()=='OFFLINE' and w.confidence>=.75}
        dealer=None
        for token in self.dealer(image,table):
            identifier=angular(token.box)
            if identifier:dealer=identifier
        waiting_ids=set()
        for word in words:
            if word.text.upper()!='WAITING' or word.confidence<.8:continue
            x,y=relative(word.box,table)
            near=sorted((hypot(s.x-x,s.y-y),s.slot_id) for s in occupied)
            if near and near[0][0]<.16 and ring_radius(x,y)>.85:waiting_ids.add(near[0][1])
        slots=tuple(replace(s,bet=bets.get(s.slot_id),in_hand=(False if s.slot_id in waiting_ids or actions.get(s.slot_id)=='fold' else (True if s.slot_id in active else None)),
                            last_action=actions.get(s.slot_id,''),dealer=s.slot_id==dealer,offline=s.slot_id in offline,waiting=s.slot_id in waiting_ids) for s in slots)
        return slots,players,pills,unread


    def analyze(self,image):
        result=Observation()
        try:
            image=self.frame(image);table=table_bounds(image)
            words=self.contextual_words(image,table,self.reader.words(image))
            paused=any('paused' in w.text.lower() and ring_radius(*relative(w.box,table))<1 for w in words)
            waiting_words=[w for w in words if w.text.lower()=='waiting' and ring_radius(*relative(w.box,table))<.9]
            waiting=any(any(t.text.lower() in ('others','for') and abs(t.box.cy-w.box.cy)<w.box.h*2 and abs(t.box.cx-w.box.cx)<table.w*.5 for t in words) for w in waiting_words)
            faces,unreadable=find_faces(image,table,self.reader) if not waiting else ([],[])
            # Keep independently confirmed cards visible if a pot/seat later fails.
            if not waiting and not self.hero_name:
                try:
                    preliminary,community=arrange_faces(faces,table)
                    geometric=[g for g,_ in card_groups(image,table) if .6<g.w/g.h<1.15 and ring_radius(*relative(g,table))<.82 and g not in {c.group for c in preliminary}]
                    if len(geometric)==len(community):
                        result.cards=CardReading(tuple(c.card for c in preliminary),tuple(c.card for c in community))
                except ValueError:pass
            try:settled,explicit_total,pot_conf,pot_boxes=self.pots(image,words,table,faces)
            except ValueError:
                if not waiting:raise
                settled=explicit_total=None;pot_conf=0;pot_boxes=[]
            seats,players,pills,unread_bets=self.layout(image,words,table,faces,pot_boxes)
            seats,_=self.tracker.identify(seats)
            result.table=TableSnapshot(seats,'paused' if paused else 'observing',None,settled,explicit_total if explicit_total is not None else (settled if not pills else None))
            if waiting:
                seats,hero_id=self.tracker.update(seats,'waiting')
                self.hero_point=None
                result.table=TableSnapshot(seats,'waiting',hero_id,settled,explicit_total if explicit_total is not None else settled)
                self.table=table;self.boxes=pot_boxes+[b for _,b,_ in players]
                return result
            anchor=None
            if self.hero_name:
                matches=[p for p in players if p[0].name.casefold()==self.hero_name]
                if len(matches)!=1:raise ValueError('내 닉네임을 찾지 못했습니다. 닉네임 입력 또는 화면 가림을 확인하세요.')
                anchor=(matches[0][1].cx,matches[0][1].cy)
            elif getattr(self,'hero_point',None) is not None:
                x,y=self.hero_point;anchor=(table.x+x*table.w,table.y+y*table.h)
            hero,board=arrange_faces(faces,table,anchor)
            geometric=[g for g,_ in card_groups(image,table) if .6<g.w/g.h<1.15 and ring_radius(*relative(g,table))<.82 and g not in {c.group for c in hero}]
            if len(geometric)!=len(board):raise ValueError('공통 카드의 수와 판독 결과가 다릅니다.')
            result.cards=CardReading(tuple(c.card for c in hero),tuple(c.card for c in board))
            panel_players=[(next(s for s in seats if s.occupied is True and hypot(s.x-p.x,s.y-p.y)<.001),b,c) for p,b,c in players]
            owners={card_owner(c.group,panel_players,table) for c in hero}
            if len(owners)!=1 or None in owners:raise ValueError('내 카드와 좌석 연결이 불확실합니다.')
            hero_id=owners.pop()
            seats=tuple(replace(s,hero=s.slot_id==hero_id,in_hand=True if s.slot_id==hero_id else s.in_hand) for s in seats)
            street={0:'Preflop',3:'Flop',4:'Turn',5:'River'}[len(board)]
            seats,hero_id=self.tracker.update(seats,'paused' if paused else 'playing',hero_id,street,tuple(c.card for c in hero))
            total=explicit_total if explicit_total is not None else (settled if not pills else None)
            notes=tuple(['총 팟 표시 확인 필요'] if total is None else [])
            result.table=TableSnapshot(seats,'paused' if paused else 'playing',hero_id,settled,total,notes)
            if self.unassigned_outer:raise ValueError('카드가 보이지만 좌석·스택을 연결하지 못한 플레이어가 있습니다.')
            if total is None:raise ValueError('현재 베팅과 별도인 total 총 팟 표시를 읽지 못해 EV를 보류합니다.')
            if any(s.occupied is True and s.slot_id!=hero_id and s.in_hand is None for s in seats):raise ValueError('일부 좌석의 핸드 참여 여부가 불확실합니다. 빈 자리나 접은 사람을 상대 수로 가정하지 않습니다.')
            active=[s for s in seats if s.occupied is True and s.in_hand is True]
            mine=next(s for s in active if s.slot_id==hero_id)
            active=[mine]+[s for s in active if s.slot_id!=hero_id]
            if not 2<=len(active)<=10:raise ValueError('남은 상대가 없거나 현재 참여자 수를 확정하지 못했습니다.')
            light=[]
            for seat in active:
                b=next(b for raw,b,_ in players if hypot(raw.x-seat.x,raw.y-seat.y)<.22)
                panel=Box(b.x-5,b.y-5,b.w+10,b.h+10).crop(image);hsv=cv2.cvtColor(panel,cv2.COLOR_BGR2HSV)
                light.append(float(((hsv[:,:,2]>210)&(hsv[:,:,1]<45)).mean())>.55)
            turn=True if light[0] and sum(light)==1 else (False if not light[0] and sum(light)==1 else None)
            yours=[w for w in words if w.text.upper()=='YOUR' and w.confidence>=.8]
            if any(any(t.text.upper()=='TURN' and abs(t.box.cy-y.box.cy)<y.box.h for t in words) for y in yours):turn=True
            if paused:turn=None
            call,call_conf,action_box=self.read_action(image,words,table,turn,self.amount)
            position=seat_position(seats,hero_id,self.tracker.dealt)
            result.state=GameState(tuple(c.card for c in hero),tuple(c.card for c in board),total,call,
                                   tuple(s.stack for s in active),len(active)-1,position,
                                   tuple(self.tracker.history),turn,seats,settled,paused)
            result.confidence={**{f'card{i}':c.confidence for i,c in enumerate(hero+board)},'pot':pot_conf,
                               **{f'stack{i}':v[2] for i,v in enumerate(players)}}
            if call is not None:result.confidence['to_call']=call_conf
            self.hero_point=(mine.x,mine.y)
            self.table=table;self.boxes=list({c.group for c in faces})+pot_boxes+[b for _,b,_ in players]+pills
            self.boxes += [Box(b.x-4,b.y-4,b.w*2+8,b.h+8) for _,b,_ in players]
            self.boxes.append(Box(round(table.x+table.w*.18),round(table.y+table.h*.57),round(table.w*.64),round(table.h*.37)))
            if action_box:self.boxes.append(Box(action_box.x-6,action_box.y-4,action_box.w*2+12,action_box.h+8))
        except (ValueError,TypeError,StopIteration,cv2.error) as exc:
            self.boxes=[];self.table=None
            result.errors.append(f'자동 인식 실패: {exc}')
        return result

    @staticmethod
    def enabled(image,word):
        tile=word.box.crop(image)
        if not tile.size:return False
        hsv=cv2.cvtColor(tile,cv2.COLOR_BGR2HSV)
        bright=((hsv[:,:,1]>55)&(hsv[:,:,2]>105))
        if float(np.median(hsv[:,:,2]))<120:bright|=(hsv[:,:,2]>185)
        return float(bright.mean())>.08

    @staticmethod
    def read_action(image,words,table,hero_turn,amount_reader=None):
        if hero_turn is not True:return None,0,None
        candidates=[w for w in words if re.match(r'^(CHECK|CALL|FOLD)(?:[ (\d]|$)',w.text.upper())
                    and w.box.cy>table.y+.88*table.h and w.box.cx>table.x+.35*table.w]
        if not candidates:return None,0,None
        bottom=max(w.box.cy for w in candidates)
        row=[w for w in words if abs(w.box.cy-bottom)<table.h*.06 and w.box.cx>table.x+.30*table.w]
        labels={re.sub(r'[^A-Z].*','',w.text.upper()) for w in row if w.confidence>=.85 and PokerNowRecognizer.enabled(image,w)}
        if any(w.text.upper()=='OR' for w in row) or 'FOLD' not in labels or not labels.intersection({'BET','RAISE','CALL','ALL'}):return None,0,None
        calls=[w for w in row if w.text.upper().startswith('CALL') and w.confidence>=.85 and PokerNowRecognizer.enabled(image,w)]
        checks=[w for w in row if w.text.upper()=='CHECK' and w.confidence>=.85 and PokerNowRecognizer.enabled(image,w)]
        if calls:
            if len(calls)!=1:return None,0,None
            word=calls[0];joined=re.fullmatch(r'CALL[ (]*([\d,]+(?:\.\d+)?)[ )]*',word.text.upper())
            if joined:
                expected=number(joined[1]);box=PokerNowRecognizer.numeric_suffix(image,word,len(re.sub(r'\D','',joined[1])))
                if box is None:return None,0,None
            else:
                amounts=[w for w in row if number(w.text.strip('()')) is not None and abs(w.box.cx-word.box.cx)<table.h*.22]
                if len(amounts)!=1:return None,0,None
                expected=number(amounts[0].text.strip('()'));box=amounts[0].box
            if amount_reader is None:return None,0,None
            value,confidence=amount_reader(image,box,expected)
            return (value,min(word.confidence,confidence),box) if value==expected else (None,0,None)
        if checks:return 0.0,checks[0].confidence,checks[0].box
        return None,0,None
