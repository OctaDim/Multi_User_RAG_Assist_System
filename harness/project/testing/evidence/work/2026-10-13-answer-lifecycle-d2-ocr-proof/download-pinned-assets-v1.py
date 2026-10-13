from pathlib import Path
import concurrent.futures,hashlib,json,time,urllib.request
root=Path('/home/octadim/MyProjects/Multi_User_RAG_Assist_System/harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof')
assets=Path('/tmp/rag-answer-lifecycle-models/ocr');assets.mkdir(exist_ok=True)
selected=[('paddleocr',['PaddleOCR-VL-1.5.gguf','PaddleOCR-VL-1.5-mmproj.gguf']),('doctype',['doctype_classifier.onnx'])]
def download(item):
 name,metadata,source=item
 file=source['rfilename'];expected=source['lfs']['sha256'];target=assets/file
 started=time.monotonic();digest=hashlib.sha256();count=0
 url='https://huggingface.co/'+metadata['id']+'/resolve/'+metadata['sha']+'/'+file
 with urllib.request.urlopen(url,timeout=60) as response,target.open('xb') as out:
  while data:=response.read(1024*1024): out.write(data);digest.update(data);count+=len(data)
 assert count==source['size'] and digest.hexdigest()==expected,(file,count,digest.hexdigest())
 result={'repo':metadata['id'],'revision':metadata['sha'],'file':str(target),'bytes':count,'sha256':digest.hexdigest(),'seconds':round(time.monotonic()-started,2)}
 print(json.dumps(result),flush=True)
 return result
items=[]
for name,files in selected:
 metadata=json.loads((root/(name+'-metadata-v1.json')).read_text())
 for source in metadata['siblings']:
  if source['rfilename'] in files: items.append((name,metadata,source))
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor: results=list(executor.map(download,items))
with (root/'downloaded-assets-v1.json').open('x') as out: json.dump(results,out,indent=2);out.write('\n')
