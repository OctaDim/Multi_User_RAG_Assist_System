import sys,json,time
sys.path.append('/home/octadim/MyProjects/Multi_User_RAG_Assist_System/backend/.venv/lib/python3.12/site-packages')
import onnxruntime as ort
from pathlib import Path
root=Path('/home/octadim/MyProjects/Multi_User_RAG_Assist_System/harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof')
opts=ort.SessionOptions();opts.intra_op_num_threads=2;opts.inter_op_num_threads=1
start=time.monotonic();s=ort.InferenceSession('/tmp/rag-answer-lifecycle-models/ocr/dfine/model.onnx',sess_options=opts,providers=['CPUExecutionProvider'])
result={'seconds':time.monotonic()-start,'inputs':[(v.name,v.shape,v.type) for v in s.get_inputs()],'outputs':[(v.name,v.shape,v.type) for v in s.get_outputs()]}
with (root/'dfine-runtime-shape-v1.json').open('x') as out:json.dump(result,out,indent=2);out.write('\n')
print(json.dumps(result))
