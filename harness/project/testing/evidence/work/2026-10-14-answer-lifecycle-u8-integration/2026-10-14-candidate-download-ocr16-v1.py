import urllib.request,hashlib,json,time
from pathlib import Path
revision='511b09642bb324401f15f97cc23bc67e8f0a291d';base='https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF/resolve/'+revision+'/'
folder=Path('/tmp/rag-u8-worker-ocr16-candidate');folder.mkdir(exist_ok=True)
records=[]
for name,size,digest in [('PaddleOCR-VL-1.6-GGUF.gguf',935769056,'86097afcada5bcda920740f83a23f75617c326e2ccc418eeb53087c88cfc034c'),('PaddleOCR-VL-1.6-GGUF-mmproj.gguf',881770560,'fde2dfa1030a45fe32fb6e77d09a42efbad6ceac8d7707328b4588528620894a')]:
 path=folder/name
 if not path.exists():
  with urllib.request.urlopen(base+name,timeout=60) as response,path.open('xb') as output:
   while chunk:=response.read(4*1024*1024):output.write(chunk)
 actual=hashlib.file_digest(path.open('rb'),'sha256').hexdigest();assert path.stat().st_size==size and actual==digest,(name,actual)
 record={'url':base+name,'revision':revision,'path':str(path),'bytes':size,'sha256':actual,'status':'candidate only; unchanged original assets, no adoption/accuracy claim'};records.append(record);print(json.dumps(record),flush=True)
p=Path('/home/octadim/MyProjects/Multi_User_RAG_Assist_System/harness/project/testing/evidence/work/2026-10-14-answer-lifecycle-u8-integration/2026-10-14-ocr16-candidate-assets-v1.json');assert not p.exists();p.write_text(json.dumps(records,indent=2)+'\n')
