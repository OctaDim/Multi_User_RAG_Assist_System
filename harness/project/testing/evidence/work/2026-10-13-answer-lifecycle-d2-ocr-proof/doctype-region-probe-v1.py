import sys
sys.path.append('/home/octadim/MyProjects/Multi_User_RAG_Assist_System/backend/.venv/lib/python3.12/site-packages')
from pathlib import Path
from PIL import Image
import numpy as np
import onnxruntime as ort
import json
root=Path('/home/octadim/MyProjects/Multi_User_RAG_Assist_System/harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof')
options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1
session=ort.InferenceSession('/tmp/rag-answer-lifecycle-models/ocr/doctype_classifier.onnx',sess_options=options,providers=['CPUExecutionProvider'])
labels=['chart','diagram','document_handwritten','document_printed','map','photo','screenshot']
printed=Image.open(root/'printed-four-languages-v1.png').convert('RGB')
hand=Image.open(root/'paddle-handwrite-en-original.png').convert('RGB')
samples={'printed_line_english':printed.crop((50,75,1150,150)),'printed_block':printed.crop((40,60,1160,650)),'handwritten_title':hand.crop((130,15,330,80)),'handwritten_signature':hand.crop((330,610,490,685)),'handwritten_title_author':hand.crop((130,15,500,135))}
results=[]
for name,image in samples.items():
 for preprocessing in ['stretch','letterbox']:
  if preprocessing=='stretch':resized=image.resize((320,320))
  else:
   resized=Image.new('RGB',(320,320),'white');thumb=image.copy();thumb.thumbnail((320,320));resized.paste(thumb,((320-thumb.width)//2,(320-thumb.height)//2))
  batch=np.asarray(resized,dtype=np.float32)[None]/255
  scores=session.run(None,{'input_layer_1':batch})[0][0]
  results.append({'region':name,'preprocessing':preprocessing,'scores':dict(zip(labels,map(float,scores))),'predicted':labels[int(np.argmax(scores))]})
summary={'scope':'Manually selected regions, no automated localization; stretch/letterbox characterization, not production acceptance','results':results}
with (root/'doctype-region-characterization-v1.json').open('x') as out:json.dump(summary,out,ensure_ascii=False,indent=2);out.write('\n')
for row in results:print(row['region'],row['preprocessing'],row['predicted'],round(max(row['scores'].values()),4))
