"""Bounded local Tesseract calls shared by automatic layout and rank readers."""
from dataclasses import dataclass
import csv
import io
import subprocess
import cv2
import numpy as np
from src.vision.screen import TesseractNumbers


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self): return self.x+self.w/2
    @property
    def cy(self): return self.y+self.h/2
    def crop(self,image):
        return image[max(0,self.y):max(0,self.y+self.h),max(0,self.x):max(0,self.x+self.w)]
    def contains(self,other):
        return self.x<=other.cx<=self.x+self.w and self.y<=other.cy<=self.y+self.h


@dataclass(frozen=True)
class Word:
    text: str
    confidence: float
    box: Box


class TesseractReader:
    def __init__(self, executable=None):
        self.executable=TesseractNumbers(executable).executable
        self.cache={}

    def words(self,image,psm=11,whitelist=None):
        ok,data=cv2.imencode('.png',image)
        if not ok: return []
        cmd=[self.executable,'stdin','stdout','--psm',str(psm),'-l','eng']
        if whitelist: cmd+=['-c',f'tessedit_char_whitelist={whitelist}']
        cmd+=['tsv']
        try:
            r=subprocess.run(cmd,input=data.tobytes(),capture_output=True,timeout=3,
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except subprocess.TimeoutExpired:
            raise ValueError('OCR 시간 초과. 테이블을 크게 표시하고 다른 창이 가리지 않게 해 주세요.')
        if r.returncode: raise ValueError('Tesseract 실행 실패. 영어 eng 데이터 설치를 확인하세요.')
        result=[]
        for row in csv.DictReader(io.StringIO(r.stdout.decode('utf-8')),delimiter='\t'):
            if row.get('text','').strip():
                result.append(Word(row['text'].strip(),max(0,float(row['conf'])/100),
                                   Box(*(int(row[k]) for k in ('left','top','width','height')))))
        return result

    def rank(self,mask):
        key=(mask.shape,mask.tobytes())
        if key in self.cache: return self.cache[key]
        h,w=mask.shape
        if not h or not w: return None,0
        scale=90/h
        ink=cv2.resize(mask.astype(np.uint8)*255,(max(8,round(w*scale)),90),interpolation=cv2.INTER_NEAREST)
        image=cv2.copyMakeBorder(255-ink,25,25,25,25,cv2.BORDER_CONSTANT,value=255)
        votes={}
        result=(None,0)
        for angle in (0,8,-8):
            matrix=cv2.getRotationMatrix2D((image.shape[1]/2,image.shape[0]/2),angle,1)
            rotated=cv2.warpAffine(image,matrix,(image.shape[1],image.shape[0]),borderValue=255)
            current=[]
            for psm in (6,13):
                words=self.words(rotated,psm,'23456789TJQKA10')
                if len(words)!=1:continue
                word=words[0];label='T' if word.text=='10' else word.text
                if len(label)!=1 or label not in '23456789TJQKA' or word.confidence<.75:continue
                current.append((label,word.confidence))
                votes.setdefault(label,[]).append(word.confidence)
            if angle==0 and len(current)==2 and current[0][0]==current[1][0]:
                result=(current[0][0],min(v for _,v in current))
                break
        if result[0] is None:
            accepted=sorted(((len(values),min(values),label) for label,values in votes.items() if len(values)>=2),reverse=True)
            if accepted and (len(accepted)==1 or accepted[0][0]>accepted[1][0]):
                result=(accepted[0][2],accepted[0][1])
        if len(self.cache)>256: self.cache.clear()
        self.cache[key]=result
        return result
