"""Generated ten-seat/browser-frame fixtures; no user screenshots are stored."""
from PIL import Image,ImageDraw
import cv2
import numpy as np
from src.utils.pokernow_fixture import font,card

SLOTS=((.70,1.02),(.30,1.02),(-.02,.82),(-.12,.48),(-.02,.12),(.30,-.10),(.70,-.10),(1.02,.12),(1.12,.48),(1.02,.82))


def scene(hero=0,occupied=(0,8),bets=None,waiting=False,paused=False,gray=False,full_browser=False,board=('4d','6s','Ah'),hole=('7h','4c')):
    bets=bets or {}
    im=Image.new('RGB',(1920,1080),(38,38,38));d=ImageDraw.Draw(im)
    tx,ty,tw,th=340,220,1240,580
    d.ellipse((tx,ty,tx+tw,ty+th),fill=(83,20,115),outline=(16,16,16),width=14)
    main=0 if waiting else 4000;total=main+sum(bets.values())
    d.text((900,255),str(main),font=font('text',42),fill='white',anchor='lt')
    if bets:d.text((960,228),'total '+str(total),font=font('text',21),fill='white',anchor='lt')
    for i,(sx,sy) in enumerate(SLOTS):
        x=round(tx+sx*tw);y=round(ty+sy*th)
        if i not in occupied:
            d.rectangle((x-115,y-45,x+115,y+45),outline=(68,68,68),width=2)
            d.text((x-103,y-36),str(i+1),font=font('text',21),fill=(88,88,88),anchor='lt')
    if not waiting:
        for i,code in enumerate(board):
            c=card(code,(145,180));im.paste(c,(550+i*165,350),c)
    for i in occupied:
        sx,sy=SLOTS[i];x=round(tx+sx*tw);y=round(ty+sy*th)
        d=ImageDraw.Draw(im)
        actor=i==hero and not paused and not waiting
        d.rounded_rectangle((x-105,y-42,x+105,y+42),radius=9,fill='white' if actor else (52,52,52))
        name='wonybot' if i==hero else f'player{i+1}'
        color='black' if actor else 'white'
        d.text((x-82,y-27),name,font=font('text',23),fill=color,anchor='lt')
        d.text((x-82,y+3),str(48000 if i==hero else 44000+i*1000),font=font('text',26),fill=color,anchor='lt')
        if not waiting:
            # Hole cards sit toward the felt, whatever the player's actual seat.
            hx=round(x+(-185 if sx>.8 else (110 if sx<.2 else 0)))
            hy=round(y+(105 if sy<.3 else (-105 if sy>.8 else 0)))
            for j,angle in enumerate((6,-6)):
                if i==hero:c=card(hole[j],(78,108),angle)
                else:
                    c=Image.new('RGBA',(78,108));cd=ImageDraw.Draw(c)
                    cd.rounded_rectangle((1,1,76,106),radius=4,fill=(25,25,30),outline=(172,172,175) if gray else (192,140,65),width=4)
                    c=c.rotate(angle,expand=True,resample=Image.Resampling.BICUBIC)
                im.paste(c,(hx-75+j*66,hy-55),c)
        d=ImageDraw.Draw(im)
        if i in bets:
            bx=round(tx+(.5+(sx-.5)*.68)*tw);by=round(ty+(.5+(sy-.5)*.68)*th)
            d.rounded_rectangle((bx-43,by-19,bx+43,by+19),radius=18,fill=(210,255,90))
            d.text((bx-29,by-12),str(bets[i]),font=font('text',22),fill='black',anchor='lt')
    d=ImageDraw.Draw(im)
    if waiting:
        d.rounded_rectangle((500,420,1420,550),radius=45,fill='white')
        d.text((760,450),'Waiting for others',font=font('text',30),fill='black',anchor='lt')
    else:
        sx,sy=SLOTS[hero];cx=round(tx+(.5+(sx-.5)*.68)*tw);cy=round(ty+(.5+(sy-.5)*.68)*th)
        if sy>.8:cy-=105
        elif sy<.3:cx=round(x+(130 if sx<.5 else -130));cy=round(y+125)
        d.rounded_rectangle((cx-40,cy-17,cx+40,cy+17),radius=16,fill='white')
        d.text((cx-29,cy-11),'check',font=font('text',22),fill='black',anchor='lt')
        if paused:
            d.text((680,620),'The room owner paused the game.',font=font('text',26),fill=(190,170,200),anchor='lt')
            d.text((1570,620),'OFFLINE',font=font('text',21),fill='white',anchor='lt')
        else:
            d.text((1590,935),'YOUR TURN',font=font('text',24),fill=(235,255,80),anchor='lt')
        for text,x in ((f'CALL {max(bets.values())}' if bets else 'BET',1160),('RAISE' if bets else 'CHECK',1430),('FOLD',1690)):
            d.text((x,985),text,font=font('text',27),fill=(25,60,35) if paused else (40,205,115),anchor='lt')
        if bets:d.text((1560,985),'CHECK',font=font('text',27),fill=(25,55,35),anchor='lt')
    if full_browser:
        outside=Image.new('RGB',(3839,1599),(24,24,24));bd=ImageDraw.Draw(outside)
        bd.rectangle((0,0,3839,95),fill=(43,43,43));bd.text((30,25),'Browser - Poker table | Other tab',font=font('text',26),fill='white')
        bd.rectangle((0,1549,3839,1599),fill=(190,202,215));bd.text((3000,1560),'Desktop taskbar',font=font('text',22),fill=(30,30,30))
        outside.paste(im.resize((2400,1350),Image.Resampling.BICUBIC),(720,110));im=outside
    return cv2.cvtColor(np.asarray(im),cv2.COLOR_RGB2BGR)
