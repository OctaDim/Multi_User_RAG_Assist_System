from pathlib import Path
import urllib.request,json,hashlib,time
r=Path('/home/octadim/MyProjects/Multi_User_RAG_Assist_System/harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof')
metadata=json.loads((r/'dfine-onnx-metadata-v1.json').read_text());revision=metadata['sha']
destination=Path('/tmp/rag-answer-lifecycle-models/ocr/dfine');destination.mkdir(exist_ok=True)
records=[]
for name in ['config.json','preprocessor_config.json','onnx/model.onnx']:
 row=next(p for p in metadata['siblings'] if p['rfilename']==name)
 target=destination/Path(name).name
 assert not target.exists(),str(target)
 url='https://huggingface.co/onnx-community/dfine-egret-x-rukopys-ONNX/resolve/'+revision+'/'+name
 started=time.monotonic();digest=hashlib.sha256();size=0
 with urllib.request.urlopen(url,timeout=120) as response,target.open('xb') as out:
  while chunk:=response.read(1024*1024):out.write(chunk);digest.update(chunk);size+=len(chunk)
 assert size==row['size'],name
 if 'lfs' in row:assert digest.hexdigest()==row['lfs']['sha256'],name
 records.append({'name':name,'revision':revision,'sha256':digest.hexdigest(),'bytes':size,'seconds':time.monotonic()-started,'url':url})
 print(records[-1],flush=True)
with (r/'dfine-downloaded-assets-v1.json').open('x') as out:json.dump(records,out,indent=2);out.write('\n')
