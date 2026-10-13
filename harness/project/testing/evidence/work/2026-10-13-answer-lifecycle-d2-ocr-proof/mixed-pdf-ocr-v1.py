import sys
sys.path.append('/home/octadim/MyProjects/Multi_User_RAG_Assist_System/backend/.venv/lib/python3.12/site-packages')
from pathlib import Path
from PIL import Image,ImageDraw
import pypdfium2 as pdfium
import base64,json,time,resource,hashlib,math
from llama_cpp import Llama
from llama_cpp.llama_chat_format import MTMDChatHandler
root=Path('/home/octadim/MyProjects/Multi_User_RAG_Assist_System/harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof')
assets=Path('/tmp/rag-answer-lifecycle-models/ocr')
image=Image.open(root/'mixed-real-title-fixture-v1.png').convert('RGB');pdfpath=root/'mixed-real-title-fixture-v1.pdf';assert not pdfpath.exists();image.save(pdfpath,resolution=100,quality=100)
with pdfium.PdfDocument(pdfpath) as document:
 page=document[0];bitmap=page.render(scale=1200/page.get_width());raster=bitmap.to_pil().convert('RGB');bitmap.close();page.close()
raster.save(root/'mixed-pdf-rendered-v1.png')
masked=raster.copy();draw=ImageDraw.Draw(masked)
regions=json.loads((root/'dfine-regions-characterization-v1.json').read_text())['results'][-1]['regions']
masked_bounds=[]
for region in regions:
 if region['label']!='handwritten':continue
 x0,y0,x1,y1=region['bbox'];bounds=(max(0,math.floor(x0)-12),max(0,math.floor(y0)-12),min(raster.width,math.ceil(x1)+12),min(raster.height,math.ceil(y1)+12));draw.rectangle(bounds,fill='white');masked_bounds.append(bounds)
masked.save(root/'mixed-pdf-printed-only-input-v1.png')
source=Image.open(root/'paddle-handwrite-en-original.png').convert('RGB');source.crop((130,15,500,135)).save(root/'real-handwritten-title-author-input-v1.png')
started=time.monotonic();handler=MTMDChatHandler(str(assets/'PaddleOCR-VL-1.5-mmproj.gguf'),use_gpu=False,verbose=True)
model=Llama(model_path=str(assets/'PaddleOCR-VL-1.5.gguf'),chat_handler=handler,n_ctx=4096,n_threads=4,n_threads_batch=8,n_gpu_layers=0,n_batch=128,n_ubatch=128,verbose=True)
results=[]
try:
 for name,scope in [('real-handwritten-title-author-input-v1.png','Permitted real handwritten title/author OCR, not four-language handwriting accuracy'),('mixed-pdf-printed-only-input-v1.png','Only detector-masked PDF raster is passed to OCR; handwriting is not recognized')]:
  start=time.monotonic();encoded=base64.b64encode((root/name).read_bytes()).decode()
  result=model.create_chat_completion(messages=[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,'+encoded}},{'type':'text','text':'OCR:'}]}],temperature=0,max_tokens=0)
  row={'input':name,'sha256':hashlib.sha256((root/name).read_bytes()).hexdigest(),'scope':scope,'result':result,'seconds':time.monotonic()-start};results.append(row)
  with (root/(name.replace('-input-v1.png','-ocr-result-v1.json'))).open('x') as out:json.dump(row,out,ensure_ascii=False,indent=2);out.write('\n')
  print(json.dumps({'input':name,'finish_reason':result['choices'][0]['finish_reason'],'seconds':row['seconds']}),flush=True)
finally:model.close()
summary={'scope':'Candidate real handwritten crop and permitted mixed PDF raster recognition; no production publisher/G4 acceptance','pdf_sha256':hashlib.sha256(pdfpath.read_bytes()).hexdigest(),'masked_bounds':masked_bounds,'total_seconds':time.monotonic()-started,'maxrss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'inputs':[row['input'] for row in results]}
with (root/'mixed-pdf-native-summary-v1.json').open('x') as out:json.dump(summary,out,ensure_ascii=False,indent=2);out.write('\n')
print(json.dumps(summary),flush=True)
