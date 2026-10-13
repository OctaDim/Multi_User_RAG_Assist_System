import sys,json,time,resource
sys.path.append('/home/octadim/MyProjects/Multi_User_RAG_Assist_System/backend/.venv/lib/python3.12/site-packages')
from pathlib import Path
from PIL import Image
import numpy as np
import onnxruntime as ort
root=Path('/home/octadim/MyProjects/Multi_User_RAG_Assist_System/harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof')
assets=Path('/tmp/rag-answer-lifecycle-models/ocr/dfine')
labels=json.loads((assets/'config.json').read_text())['id2label']
opts=ort.SessionOptions();opts.intra_op_num_threads=2;opts.inter_op_num_threads=1
s=ort.InferenceSession(str(assets/'model.onnx'),sess_options=opts,providers=['CPUExecutionProvider'])
printed=Image.open(root/'printed-four-languages-v1.png').convert('RGB')
hand=Image.open(root/'paddle-handwrite-en-original.png').convert('RGB')
mixed=printed.copy();title=hand.crop((130,15,500,135));title=title.resize((740,240));mixed.paste(title,(90,780));mixed.save(root/'mixed-real-title-fixture-v1.png')
results=[]
for name,image in [('printed',printed),('handwritten',hand),('mixed',mixed)]:
 array=np.asarray(image.resize((640,640),Image.Resampling.BILINEAR),dtype=np.float32)/255
 array=np.ascontiguousarray(array.transpose(2,0,1)[None])
 start=time.monotonic();logits,boxes=s.run(None,{'pixel_values':array})
 scores=1/(1+np.exp(-logits[0]));flat=scores.flatten();indices=np.argsort(flat)[::-1][:300]
 detected=[]
 for index in indices:
  if flat[index]<.5:continue
  query,label=divmod(int(index),7);cx,cy,w,h=boxes[0,query]
  detected.append({'label':labels[str(label)],'score':float(flat[index]),'bbox':[float((cx-w/2)*image.width),float((cy-h/2)*image.height),float((cx+w/2)*image.width),float((cy+h/2)*image.height)]})
 row={'input':name,'seconds':time.monotonic()-start,'regions':detected};results.append(row);print(json.dumps(row),flush=True)
summary={'scope':'D-FINE CPU page-region candidate, threshold .5 from author example; no OCR or production publisher acceptance','maxrss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'results':results}
with (root/'dfine-regions-characterization-v1.json').open('x') as out:json.dump(summary,out,indent=2);out.write('\n')
