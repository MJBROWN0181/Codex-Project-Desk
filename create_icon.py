"""Create the small geometric Project desk mark and Windows icon sizes."""
from pathlib import Path
from PIL import Image, ImageDraw

assets=Path(__file__).resolve().parent/'assets'
assets.mkdir(exist_ok=True)
svg='''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect x="16" y="16" width="480" height="480" rx="108" fill="#19384e"/>
<rect x="106" y="88" width="282" height="306" rx="26" fill="#527cac"/>
<rect x="82" y="112" width="282" height="306" rx="26" fill="#245bc4"/>
<rect x="58" y="136" width="282" height="306" rx="26" fill="#f6f9ff"/>
<rect x="91" y="174" width="180" height="22" rx="11" fill="#19384e"/>
<rect x="91" y="222" width="22" height="22" rx="6" fill="#245bc4"/>
<rect x="131" y="226" width="142" height="14" rx="7" fill="#8ba4be"/>
<rect x="91" y="269" width="22" height="22" rx="6" fill="#245bc4"/>
<rect x="131" y="273" width="117" height="14" rx="7" fill="#8ba4be"/>
<circle cx="363" cy="362" r="103" fill="#19384e"/>
<circle cx="363" cy="362" r="88" fill="#39b6a4"/>
<path d="M312 362h96m-38-38 38 38-38 38" fill="none" stroke="#19384e" stroke-width="23" stroke-linecap="round" stroke-linejoin="round"/>
</svg>'''
(assets/'project-desk.svg').write_text(svg,encoding='utf-8')
# Render the same geometric mark with Pillow at 2x for clean Windows downscales.
scale=2
im=Image.new('RGBA',(1024,1024),(0,0,0,0)); draw=ImageDraw.Draw(im)
def rect(box,radius,color):
    draw.rounded_rectangle(tuple(v*scale for v in box),radius*scale,fill=color)
def circle(box,color):
    draw.ellipse(tuple(v*scale for v in box),fill=color)
rect((16,16,496,496),108,'#19384e')
rect((106,88,388,394),26,'#527cac')
rect((82,112,364,418),26,'#245bc4')
rect((58,136,340,442),26,'#f6f9ff')
rect((91,174,271,196),11,'#19384e')
for y,width in ((222,142),(269,117)):
    rect((91,y,113,y+22),6,'#245bc4'); rect((131,y+4,131+width,y+18),7,'#8ba4be')
circle((260,259,466,465),'#19384e'); circle((275,274,451,450),'#39b6a4')
draw.line([(312*scale,362*scale),(408*scale,362*scale)],fill='#19384e',width=23*scale)
draw.line([(370*scale,324*scale),(408*scale,362*scale),(370*scale,400*scale)],fill='#19384e',width=23*scale,joint='curve')
for x,y in ((312,362),(370,324),(370,400)):
    draw.ellipse(((x-11.5)*scale,(y-11.5)*scale,(x+11.5)*scale,(y+11.5)*scale),fill='#19384e')
im=im.resize((512,512),Image.Resampling.LANCZOS)
im.save(assets/'project-desk.png')
im.save(assets/'project-desk.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print('Created assets/project-desk.svg, project-desk.png, project-desk.ico')
