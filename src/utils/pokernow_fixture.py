"""Self-rendered test scene inspired by the supplied layout, not a site capture."""
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
import cv2
import numpy as np


def font(kind,size):
    paths={
        'rank':['/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf','C:/Windows/Fonts/timesbd.ttf'],
        'suit':['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','C:/Windows/Fonts/seguisym.ttf'],
        'text':['/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf','C:/Windows/Fonts/arialbd.ttf'],
    }
    path=next((p for p in paths[kind] if Path(p).is_file()),None)
    if path is None:raise RuntimeError('Synthetic scene fonts unavailable')
    return ImageFont.truetype(path,size)


COLORS={'c':(15,180,20),'d':(70,65,245),'s':(0,0,0),'h':(220,25,45)}
SUITS={'c':'♣','d':'♦','s':'♠','h':'♥'}


def card(code,size,angle=0):
    w,h=size
    im=Image.new('RGBA',(w,h));d=ImageDraw.Draw(im)
    d.rounded_rectangle((0,0,w-1,h-1),radius=12,fill='white')
    color=COLORS[code[1]]
    d.text((w*.17,h*.13),code[0],font=font('rank',round(h*.39)),fill=color,anchor='lt')
    d.text((w*.35,h*.52),SUITS[code[1]],font=font('suit',round(h*.43)),fill=color,anchor='lt')
    return im.rotate(angle,resample=Image.Resampling.BICUBIC,expand=True) if angle else im


def make_scene(board=('Jc','2c','As','9c','7d'),hole=('3d','3c'),hero_turn=False,call=0):
    im=Image.new('RGB',(2048,1139),(38,38,38));d=ImageDraw.Draw(im)
    d.ellipse((360,140,1705,855),fill=(86,22,117),outline=(20,20,20),width=18)
    d.rounded_rectangle((890,230,1160,302),radius=30,fill=(65,17,90))
    d.text((964,246),'12000',font=font('text',46),fill='white',anchor='lt')
    for i,code in enumerate(board):
        tile=card(code,(167,204));im.paste(tile,(579+i*181,336),tile)
    d=ImageDraw.Draw(im)
    d.rounded_rectangle((1260,797,1460,923),radius=10,fill='white' if hero_turn else (43,43,43))
    d.text((1282,832),'wonybot',font=font('text',27),fill='black' if hero_turn else 'white',anchor='lt')
    d.text((1282,865),'40510',font=font('text',30),fill='black' if hero_turn else 'white',anchor='lt')
    d.rounded_rectangle((1695,637,1911,766),radius=10,fill=(43,43,43) if hero_turn else 'white')
    d.text((1735,673),'player',font=font('text',27),fill='white' if hero_turn else 'black',anchor='lt')
    d.text((1735,708),'47490',font=font('text',30),fill='white' if hero_turn else 'black',anchor='lt')
    for x,angle in ((1520,7),(1610,-7)):
        back=Image.new('RGBA',(112,140));bd=ImageDraw.Draw(back)
        bd.rounded_rectangle((1,1,110,138),radius=5,fill=(30,15,60),outline=(191,135,55),width=5)
        back=back.rotate(angle,expand=True,resample=Image.Resampling.BICUBIC);im.paste(back,(x,630),back)
    for code,x,angle in zip(hole,(1062,1150),(6,-6)):
        tile=card(code,(112,145),angle);im.paste(tile,(x,782),tile)
    d=ImageDraw.Draw(im)
    d.ellipse((1060,725,1125,780),fill=(244,244,244))
    d.text((1083,733),'D',font=font('text',31),fill=(80,110,210),anchor='lt')
    action='CHECK' if call==0 else f'CALL {call}'
    if not hero_turn:
        d.text((1745,925),'CHECK OR FOLD',font=font('text',30),fill=(90,90,90),anchor='lt')
    d.text((1480,1060),'BET',font=font('text',30),fill=(20,58,40) if not hero_turn else (40,210,130),anchor='lt')
    d.text((1685,1060),action,font=font('text',30),fill=(20,58,40) if not hero_turn else (40,210,130),anchor='lt')
    d.text((1900,1060),'FOLD',font=font('text',30),fill=(80,40,25) if not hero_turn else (230,95,65),anchor='lt')
    return cv2.cvtColor(np.asarray(im),cv2.COLOR_RGB2BGR)
