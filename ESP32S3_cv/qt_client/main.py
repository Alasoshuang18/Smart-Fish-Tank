import sys,json,time
from collections import Counter
from statistics import median
from PySide6.QtCore import QTimer,QUrl,Qt
from PySide6.QtGui import QImage,QPixmap,QPainter,QPen
from pathlib import Path
from PySide6.QtWidgets import QApplication,QMainWindow,QLabel,QLineEdit,QPushButton,QFormLayout,QWidget,QSpinBox,QVBoxLayout,QComboBox,QDoubleSpinBox,QSlider
from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest,QNetworkProxyFactory
from pathlib import Path
import math
ROOT=Path(__file__).resolve().parents[1]
GROUPS={'NH':ROOT/'NH','nitrate':ROOT/'nitrate','nitrite':ROOT/'nitrite'}
LEVELS={'NH':(0.0,0.5,1.0,3.0,5.0,10.0,20.0),'nitrate':(0.0,25.0,50.0,100.0,250.0),'nitrite':(0.0,1.0,5.0,10.0)}
LIMITS={k:(v[0],v[-1]) for k,v in LEVELS.items()}
def lab(im):
 c=im.convertToFormat(QImage.Format_RGB888); a=[]
 for y in range(c.height()):
  for x in range(c.width()):
   q=c.pixelColor(x,y); v=[z/255 for z in (q.red(),q.green(),q.blue())]; v=[z/12.92 if z<=.04045 else ((z+.055)/1.055)**2.4 for z in v]; X=(.4124*v[0]+.3576*v[1]+.1804*v[2])/.9505;Y=.2126*v[0]+.7152*v[1]+.0722*v[2];Z=(.0193*v[0]+.1192*v[1]+.9505*v[2])/1.0888; f=lambda z:z**(1/3) if z>.008856 else 7.787*z+16/116; X,Y,Z=f(X),f(Y),f(Z);a.append((116*Y-16,500*(X-Y),200*(Y-Z)))
 return tuple(sum(z[i] for z in a)/len(a) for i in range(3))
def de(a,b):
 L1,a1,b1=a;L2,a2,b2=b;c1=math.hypot(a1,b1);c2=math.hypot(a2,b2);cm=(c1+c2)/2;g=.5*(1-math.sqrt(cm**7/(cm**7+25**7))) if cm else .5;ap1=(1+g)*a1;ap2=(1+g)*a2;cp1=math.hypot(ap1,b1);cp2=math.hypot(ap2,b2);h=lambda x,y:math.degrees(math.atan2(y,x))%360 if x or y else 0;h1,h2=h(ap1,b1),h(ap2,b2);dh=h2-h1
 if cp1*cp2 and abs(dh)>180:dh-=360 if dh>0 else -360
 dl=L2-L1;dc=cp2-cp1;dH=2*math.sqrt(cp1*cp2)*math.sin(math.radians(dh/2));lm=(L1+L2)/2;cpm=(cp1+cp2)/2;hm=(h1+h2+360)/2 if cp1*cp2 and abs(h1-h2)>180 else (h1+h2)/2;t=1-.17*math.cos(math.radians(hm-30))+.24*math.cos(math.radians(2*hm))+.32*math.cos(math.radians(3*hm+6))-.2*math.cos(math.radians(4*hm-63));sl=1+.015*(lm-50)**2/math.sqrt(20+(lm-50)**2);sc=1+.045*cpm;sh=1+.015*cpm*t;rt=-2*math.sqrt(cpm**7/(cpm**7+25**7))*math.sin(math.radians(60*math.exp(-((hm-275)/25)**2)))
 return math.sqrt((dl/sl)**2+(dc/sc)**2+(dH/sh)**2+rt*(dc/sc)*(dH/sh))
def auto_lab(im):
 c=im.convertToFormat(QImage.Format_RGB888); vals=[]; total=max(1,c.width()*c.height()); highlights=0; gray=[]
 for y in range(c.height()):
  for x in range(c.width()):
   q=c.pixelColor(x,y); r,g,b=q.red(),q.green(),q.blue(); mx=max(r,g,b); mn=min(r,g,b); gray.append((r+g+b)/3)
   if mx >= 245 and (mx-mn) <= 18: highlights += 1
   if 35 < mx < 245 and mx-mn >= 32: vals.append(rgb_lab_pixel(r,g,b))
 valid_ratio=len(vals)/total; highlight_ratio=highlights/total
 if len(vals) < max(10, int(total*0.03)):
  # 没有足够彩色像素时，仍使用整块 ROI 的 Lab 颜色继续匹配。
  fallback=lab(im)
  return fallback, len(vals), highlight_ratio, valid_ratio, 0.0
 # 简单邻域梯度作为清晰度指标。
 sharpness=0.0; count=0
 for i in range(1,len(gray)):
  sharpness += abs(gray[i]-gray[i-1]); count += 1
 sharpness=sharpness/max(1,count)
 return tuple(median(v[i] for v in vals) for i in range(3)),len(vals),highlight_ratio,valid_ratio,sharpness

def rgb_lab_pixel(r,g,b):
 v=[z/255 for z in (r,g,b)]; v=[z/12.92 if z<=.04045 else ((z+.055)/1.055)**2.4 for z in v]
 X=(.4124*v[0]+.3576*v[1]+.1804*v[2])/.9505;Y=.2126*v[0]+.7152*v[1]+.0722*v[2];Z=(.0193*v[0]+.1192*v[1]+.9505*v[2])/1.0888; f=lambda z:z**(1/3) if z>.008856 else 7.787*z+16/116; X,Y,Z=f(X),f(Y),f(Z)
 return (116*Y-16,500*(X-Y),200*(Y-Z))

def lab_center(im, fraction=0.5):
 im=im.convertToFormat(QImage.Format_RGB888)
 dx=int(im.width()*(1-fraction)/2); dy=int(im.height()*(1-fraction)/2)
 return lab(im.copy(dx,dy,max(1,int(im.width()*fraction)),max(1,int(im.height()*fraction))))

def refs():
 o={}
 for k,d in GROUPS.items():
  rows=[]
  for p in d.glob('*.*'):
   try:
    im=QImage(str(p)); robust=auto_lab(im)[0]; rows.append((float(p.stem), robust if robust is not None else lab_center(im)))
   except (ValueError,OSError): pass
  allowed=set(LEVELS[k]); rows=[z for z in rows if z[0] in allowed]
  o[k]=sorted(rows,key=lambda z:z[0])
 return o

class Win(QMainWindow):
 def __init__(self):
  super().__init__(); self.setWindowTitle('ESP32-S3 试纸实时检测'); self.resize(1140,1250); self.n=QNetworkAccessManager(self); self.url=QLineEdit('http://192.168.4.1'); self.refs=refs(); self.img=QLabel('视频流连接中'); self.img.setMinimumSize(1080,1000); self.img.setMaximumSize(1080,1000); self.img.setScaledContents(False); self.img.setAlignment(Qt.AlignCenter); self.img.setStyleSheet('background: #202020'); self.result=QLabel('当前检测：氨氮\n氨氮含量：--（范围 0~20）\n硝酸盐含量：--（范围 0~250）\n亚硝酸盐含量：--（范围 0~10）\n白灰黑校正：未启用（需要基准块坐标）'); self.result.setWordWrap(True); self.result.setMinimumHeight(125); self.result.setStyleSheet('font-size: 18px; padding: 8px; background: #eeeeee; color: #222222'); self.th=QDoubleSpinBox(); self.th.setRange(.1,100); self.exposure=QSlider(Qt.Horizontal); self.exposure.setRange(-3,3); self.exposure.setValue(0); self.exposure.valueChanged.connect(lambda v:self.exposure_label.setText(f'{v:+d}')); self.exposure_label=QLabel('0'); self.th.setValue(6); self.th.setSuffix(' ΔE'); self.frames=[]; self.stream=None; self.buf=bytearray(); self.group_index=0; self.last_analysis=0.0; self.reply=None; self.reconnect_timer=QTimer(self); self.reconnect_timer.setSingleShot(True); self.reconnect_timer.timeout.connect(self.start_stream); self.roi_x=100; self.roi_y=70; self.roi_w=20; self.roi_h=20; self.http_ready=False; self.chunked=False; self.values={'NH':'--（范围 0~20）','nitrate':'--（范围 0~250）','nitrite':'--（范围 0~10）'}; self.window_samples={'NH':[],'nitrate':[],'nitrite':[]}; self.detect_timer=QTimer(self); self.detect_timer.timeout.connect(self.next_group); self.detect_timer.start(3000); self.detecting=True; self.rounds=0
  self.start_button=QPushButton('暂停检测'); self.start_button.clicked.connect(self.toggle_detection); self.rx=QSpinBox(); self.rx.setRange(0,2000); self.rx.setValue(self.roi_x); self.ry=QSpinBox(); self.ry.setRange(0,2000); self.ry.setValue(self.roi_y); self.rw=QSpinBox(); self.rw.setRange(1,2000); self.rw.setValue(self.roi_w); self.rh=QSpinBox(); self.rh.setRange(1,2000); self.rh.setValue(self.roi_h); b=QPushButton('保存并下发参数'); b.clicked.connect(self.send); connect=QPushButton('连接视频流'); connect.clicked.connect(self.start_stream); f=QFormLayout(); f.addRow('设备地址',self.url); f.addRow('稳定 ΔE 阈值',self.th); f.addRow('曝光补偿 (-3 ~ +3)',self.exposure); f.addRow('当前曝光',self.exposure_label); f.addRow(self.start_button); f.addRow('固定色块 X / Y',self.rx); f.addRow('',self.ry); f.addRow('检测孔宽 / 高（像素）',self.rw); f.addRow('',self.rh); f.addRow(connect); f.addRow(b); w=QWidget(); l=QVBoxLayout(w); l.addLayout(f); l.addWidget(self.result); l.addWidget(self.img); self.setCentralWidget(w); QTimer.singleShot(100,self.start_stream)
 def start_stream(self):
  if self.reply is not None:
   return
  self.buf.clear(); self.http_ready=False; self.chunked=False; self.result.setStyleSheet('color: #aa6600'); self.result.setText('正在连接视频流：/stream')
  req=QNetworkRequest(QUrl(self.url.text().rstrip('/')+'/stream')); req.setAttribute(QNetworkRequest.CacheLoadControlAttribute,QNetworkRequest.AlwaysNetwork); req.setRawHeader(b'Cache-Control',b'no-cache'); req.setRawHeader(b'Accept',b'multipart/x-mixed-replace')
  self.reply=self.n.get(req); self.reply.readyRead.connect(self.read_stream); self.reply.finished.connect(self.stream_finished); self.reply.errorOccurred.connect(lambda e:self.stream_error(self.reply.errorString() if self.reply else ''))
  print('HTTP 视频流请求:',req.url().toString())
 def stream_finished(self):
  reply=self.reply; self.reply=None
  if reply is not None:
   err=reply.errorString()
   if reply.error()!=0 and err!='Operation canceled': self.result.setText('视频流错误：'+err)
   reply.deleteLater()
  if not self.reconnect_timer.isActive(): self.reconnect_timer.start(1000)
 def stream_error(self,msg):
  if msg and msg!='Operation canceled': self.result.setText('视频流错误：'+msg); print('视频流错误:',msg)
 def read_stream(self):
  if not self.reply:return
  # QNetworkReply 已经剥离 HTTP 头并处理传输层 chunked，只解析返回体中的 JPEG。
  self.buf.extend(bytes(self.reply.readAll()))
  latest=None
  while True:
   soi=self.buf.find(b'\xff\xd8')
   if soi<0:
    if len(self.buf)>2:self.buf=self.buf[-2:]
    break
   if soi>0:del self.buf[:soi]
   eoi=self.buf.find(b'\xff\xd9',2)
   if eoi<0:break
   latest=bytes(self.buf[:eoi+2]); del self.buf[:eoi+2]
  if latest is not None:self.process_frame(latest)
 def toggle_detection(self):
  if self.detecting:
   self.detecting=False; self.detect_timer.stop(); self.start_button.setText('开始检测'); self.result.setText('数据已暂停，请点击“开始检测”继续\n' + self.result.text())
  else:
   self.detecting=True; self.refs=refs(); self.group_index=0; self.rounds=0; self.window_samples={'NH':[],'nitrate':[],'nitrite':[]}; self.values={'NH':'--（范围 0~20）','nitrate':'--（范围 0~250）','nitrite':'--（范围 0~10）'}; self.detect_timer.start(3000); self.start_button.setText('暂停检测'); self.result.setText('开始新一轮检测：氨氮\n氨氮含量：--（范围 0~20）\n硝酸盐含量：--（范围 0~250）\n亚硝酸盐含量：--（范围 0~10）')

 def next_group(self):
  if not self.detecting:return
  # 结束当前 3 秒窗口：用多数档位和中位 CIEDE2000 固化一次结果。
  group=['NH','nitrate','nitrite'][self.group_index]; samples=self.window_samples[group]
  if samples:
   counts=Counter(x[0] for x in samples); best=counts.most_common(1)[0][0]; best=max(LIMITS[group][0],min(LIMITS[group][1],best)); chosen=[x[1] for x in samples if x[0]==best]; d=median(chosen); lo,hi=LIMITS[group]; self.values[group]=f'{best:g}（范围 {lo:g}~{hi:g}，CIEDE2000 {d:.2f}）'; self.save_results()
  self.window_samples[group]=[]; self.group_index=(self.group_index+1)%3; self.rounds+=1
  names=['氨氮','硝酸盐','亚硝酸盐']; self.result.setText(f'即将检测：{names[self.group_index]}（请保持色块在绿色框内）\n氨氮含量：{self.values["NH"]}\n硝酸盐含量：{self.values["nitrate"]}\n亚硝酸盐含量：{self.values["nitrite"]}')
 def process_frame(self,data):
  im=QImage.fromData(data).convertToFormat(QImage.Format_RGB888)
  if im.isNull():return
  self.roi_x,self.roi_y,self.roi_w,self.roi_h=self.rx.value(),self.ry.value(),self.rw.value(),self.rh.value(); roi=im.copy(self.roi_x,self.roi_y,self.roi_w,self.roi_h)
  preview=QPixmap.fromImage(im).scaled(self.img.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation); painter=QPainter(preview); painter.setPen(QPen(Qt.green,4)); sx=preview.width()/max(1,im.width()); sy=preview.height()/max(1,im.height()); painter.drawRect(int(self.roi_x*sx),int(self.roi_y*sy),int(self.roi_w*sx),int(self.roi_h*sy)); painter.drawText(int(self.roi_x*sx)+5,int(self.roi_y*sy)+25,['氨氮','硝酸盐','亚硝酸盐'][self.group_index]); painter.end(); self.img.setPixmap(preview); self.result.setStyleSheet('color: green')
  if not self.detecting:return
  now=time.monotonic()
  if now-self.last_analysis < 0.30: return
  self.last_analysis=now
  q,count,highlight_ratio,valid_ratio,sharpness=auto_lab(roi); group=['NH','nitrate','nitrite'][self.group_index]; title=['氨氮含量','硝酸盐含量','亚硝酸盐含量'][self.group_index]
  if q is None:
   q=lab(roi)
  # 相机 Lab 与该项目每个标准图片的 Lab 逐项计算 CIEDE2000。
  scores=sorted((de(q,reference_lab), concentration) for concentration,reference_lab in self.refs[group]); d,c=scores[0]
  c=max(LIMITS[group][0],min(LIMITS[group][1],c)); self.window_samples[group].append((c,d)); self.window_samples[group]=self.window_samples[group][-20:]; self.values[group]=f'{c:g}（范围 {LIMITS[group][0]:g}~{LIMITS[group][1]:g}，CIEDE2000 {d:.2f}）'
  self.result.setText(f'当前检测：{title}\n氨氮含量：{self.values["NH"]}\n硝酸盐含量：{self.values["nitrate"]}\n亚硝酸盐含量：{self.values["nitrite"]}\n白灰黑校正：未启用（需要基准块坐标）')
 def save_results(self):
  try:
   Path(__file__).with_name('last_results.json').write_text(json.dumps({'time':time.strftime('%Y-%m-%d %H:%M:%S'),'NH':self.values['NH'],'nitrate':self.values['nitrate'],'nitrite':self.values['nitrite']},ensure_ascii=False,indent=2),encoding='utf-8')
  except OSError: pass
 def send(self):
  data=json.dumps({'roi_x':self.roi_x,'roi_y':self.roi_y,'roi_w':self.roi_w,'roi_h':self.roi_h,'threshold':self.th.value(),'ae_level':self.exposure.value()}).encode(); req=QNetworkRequest(QUrl(self.url.text().rstrip('/')+'/api/config')); req.setHeader(QNetworkRequest.ContentTypeHeader,'application/json'); self.n.post(req,data)
app=QApplication(sys.argv); print('Qt 客户端文件:', Path(__file__).resolve()); QNetworkProxyFactory.setUseSystemConfiguration(False); w=Win(); w.show(); sys.exit(app.exec())
