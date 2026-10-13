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
samples={name:Image.open(root/name).convert('RGB') for name in ['printed-four-languages-v1.png','paddle-handwrite-en-original.png']}
results=[]
for name,image in samples.items():
 for mode,divisor in [('pixels_0_255',1),('pixels_0_1',255)]:
  batch=np.asarray(image.resize((320,320)),dtype=np.float32)[None]/divisor
  scores=session.run(None,{'input_layer_1':batch})[0][0]
  results.append({'image':name,'preprocessing':mode,'scores':dict(zip(labels,map(float,scores))),'predicted':labels[int(np.argmax(scores))]})
summary={'scope':'Input scaling characterization on two images only, not region detection or calibrated accuracy','results':results}
with (root/'doctype-characterization-v1.json').open('x') as out:json.dump(summary,out,ensure_ascii=False,indent=2);out.write('\n')
print(json.dumps(summary,indent=2))
