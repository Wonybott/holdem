"""Geometry/identity tracking independent of where the hero sits."""
from dataclasses import replace
from math import atan2,hypot,pi
import cv2
import numpy as np
from src.models.table import Seat,TableSnapshot
from src.models.state import Action
from src.vision.ocr import Box


def polar(x,y):return atan2((y-.5)*2,(x-.5)*2)

def angle_distance(a,b):return abs((a-b+pi)%(2*pi)-pi)

def relative(box,table):return ((box.cx-table.x)/table.w,(box.cy-table.y)/table.h)

def ring_radius(x,y):return hypot((x-.5)*2,(y-.5)*2)


def empty_rectangles(image,table):
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    contrast=cv2.createCLAHE(3,(8,8)).apply(gray)
    edges=cv2.Canny(contrast,8,25)
    contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    found=[]
    for c in contours:
        x,y,w,h=cv2.boundingRect(c)
        if not (.13*table.w<w<.42*table.w and .10*table.h<h<.40*table.h):continue
        box=Box(x,y,w,h);rx,ry=relative(box,table)
        if not .90<ring_radius(rx,ry)<1.65:continue
        perimeter=cv2.arcLength(c,True)
        poly=cv2.approxPolyDP(c,.025*perimeter,True)
        if len(poly)!=4:continue
        border=edges[y:y+h,x:x+w]>0
        coverage=(border[:4].any(axis=0).mean(),border[-4:].any(axis=0).mean(),border[:,:4].any(axis=1).mean(),border[:,-4:].any(axis=1).mean())
        if min(coverage)<.65:continue
        if any(hypot(box.cx-b.cx,box.cy-b.cy)<min(w,h)*.3 for b in found):continue
        found.append(box)
    lines=cv2.HoughLinesP(edges,1,np.pi/180,30,minLineLength=max(25,round(table.h*.07)),maxLineGap=12)
    if lines is not None:
        horizontal=[(min(a,c),round((b+d)/2),max(a,c)) for a,b,c,d in lines[:,0] if abs(b-d)<=3 and .13*table.w<abs(c-a)<.42*table.w]
        vertical=[(round((a+c)/2),min(b,d),max(b,d)) for a,b,c,d in lines[:,0] if abs(a-c)<=3]
        for left,top,right in horizontal:
            for l,bottom,r in horizontal:
                if not (.10*table.h<bottom-top<.40*table.h and abs(l-left)<8 and abs(r-right)<8):continue
                if not all(any(abs(x-edge)<7 and y1<=top+10 and y2>=bottom-10 for x,y1,y2 in vertical) for edge in (left,right)):continue
                box=Box(left,top,right-left,bottom-top);rx,ry=relative(box,table)
                if .90<ring_radius(rx,ry)<1.65 and not any(hypot(box.cx-b.cx,box.cy-b.cy)<box.h*.35 for b in found):found.append(box)
    return found


def match_slot(centers,point,limit=.24):
    values=sorted((hypot(x-point[0],y-point[1]),i) for i,(x,y) in enumerate(centers))
    if not values or values[0][0]>limit:return None
    if len(values)>1 and values[1][0]-values[0][0]<.025:return None
    return values[0][1]


def betting_pills(image,table):
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    mask=cv2.inRange(hsv,(25,95,135),(85,255,255))
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    result=[]
    for c in contours:
        x,y,w,h=cv2.boundingRect(c)
        if not (.025*table.h<h<.16*table.h and 1.3<w/h<5):continue
        box=Box(x,y,w,h);rx,ry=relative(box,table)
        if .52<ring_radius(rx,ry)<1.0 and cv2.contourArea(c)>.55*w*h:result.append(box)
    return result


def seat_position(seats,hero_id,dealt):
    occupied=[s for s in seats if s.occupied is True]
    hero=next((s for s in occupied if s.slot_id==hero_id),None)
    dealer=next((s for s in occupied if s.dealer),None)
    if hero is None or dealer is None:return 'UNKNOWN'
    if dealer.slot_id==hero_id:return 'BTN'
    if len(occupied)==2 and all(s.slot_id in dealt for s in occupied):return 'BB'
    if any(s.slot_id not in dealt for s in occupied):return 'UNKNOWN'
    ring=sorted(occupied,key=lambda s:polar(s.x,s.y))
    offset=(ring.index(hero)-ring.index(dealer))%len(ring)
    if offset==1:return 'SB'
    if offset==2:return 'BB'
    if offset==len(ring)-1:return 'CO'
    if offset==3:return 'UTG'
    return 'MP'


class TableTracker:
    def __init__(self):
        self.previous=()
        self.counter=0
        self.history=[]
        self.dealt=set()
        self.folds=set()
        self.last_visible={}
        self.hand=None
        self.street=None
        self.bubbles={}
        self.known_bets={}
        self.dealer=None

    def identify(self,seats,hero_id=None):
        # Match by actual number when readable, otherwise stable table-relative
        # geometry. Never invent site seat numbers from clockwise ordering.
        used=set();mapped=[];id_map={}
        for s in seats:
            same=[p for p in self.previous if p.slot_id not in used and s.number is not None and p.number==s.number]
            if not same:
                close=sorted((hypot(p.x-s.x,p.y-s.y),p.slot_id,p) for p in self.previous if p.slot_id not in used)
                same=[close[0][2]] if close and close[0][0]<.18 else []
            if same:identifier=same[0].slot_id
            else:self.counter+=1;identifier=f'S{self.counter:02d}'
            used.add(identifier);id_map[s.slot_id]=identifier
            mapped.append(replace(s,slot_id=identifier,number=s.number if s.number is not None else (same[0].number if same else None)))
        hero_id=id_map.get(hero_id,hero_id)
        self.previous=tuple(mapped)
        return self.previous,hero_id

    def update(self,seats,phase,hero_id=None,street=None,hole=None):
        mapped,hero_id=self.identify(seats,hero_id)
        hand=(tuple(sorted(hole)),hero_id) if hole else None
        new_hand=phase=='waiting' or (hand is not None and self.hand is not None and hand!=self.hand)
        if self.street and street and {'Preflop':0,'Flop':3,'Turn':4,'River':5}[street]<{'Preflop':0,'Flop':3,'Turn':4,'River':5}[self.street]:new_hand=True
        dealer=next((s.slot_id for s in mapped if s.dealer),None)
        if dealer and self.dealer and dealer!=self.dealer and street=='Preflop':new_hand=True
        if dealer:self.dealer=dealer
        if new_hand:self.history=[];self.dealt=set();self.folds=set();self.last_visible={};self.bubbles={};self.known_bets={}
        if street!=self.street:self.last_visible={}
        if hand:self.hand=hand
        if street:self.street=street
        tracked=[]
        for s in mapped:
            if s.in_hand is True:self.dealt.add(s.slot_id)
            if s.last_action=='fold':self.dealt.add(s.slot_id);self.folds.add(s.slot_id)
            if s.slot_id in self.folds:s=replace(s,in_hand=False)
            if phase=='waiting':s=replace(s,in_hand=None,bet=None,last_action='')
            current=(s.bet,s.last_action)
            old=self.last_visible.get(s.slot_id)
            if phase not in ('waiting','paused'):
                old_bubble=self.bubbles.get(s.slot_id)
                if s.last_action and s.last_action!=old_bubble:
                    self.history.append(Action(s.slot_id,(street if old_bubble is not None and old is not None else 'UNKNOWN') or 'UNKNOWN','observed_'+s.last_action,s.bet or 0))
                bet_key=(s.slot_id,street)
                if s.bet is not None and s.bet>0 and s.bet!=self.known_bets.get(bet_key):
                    self.history.append(Action(s.slot_id,street or 'UNKNOWN','observed_bet_to',s.bet))
                    self.known_bets[bet_key]=s.bet
            self.bubbles[s.slot_id]=s.last_action
            self.last_visible[s.slot_id]=current
            tracked.append(s)
        self.history=self.history[-80:]
        self.previous=tuple(tracked)
        return tuple(tracked),hero_id
