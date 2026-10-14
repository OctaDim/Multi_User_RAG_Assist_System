from pathlib import Path
from io import BytesIO
import base64,hashlib,json,os,time
from PIL import Image
from llama_cpp import Llama
from llama_cpp.llama_chat_format import MTMDChatHandler
from app.ocr import render_pdf_page,parse_spotting
root=Path('/home/octadim/MyProjects/Multi_User_RAG_Assist_System');e=root/'harness/project/testing/evidence/work/2026-10-14-answer-lifecycle-u8-integration';fixtures=root/'backend/tests/fixtures/answer_lifecycle'
assert hashlib.file_digest(open('/tmp/rag-u8-worker-qwen4b-ocr-candidate/Qwen3.5-4B-Q4_K_M.gguf','rb'),'sha256').hexdigest()=='00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4'
handler=MTMDChatHandler('/tmp/rag-u8-worker-qwen4b-ocr-candidate/mmproj-F16.gguf',use_gpu=False,verbose=True)
model=Llama(model_path='/tmp/rag-u8-worker-qwen4b-ocr-candidate/Qwen3.5-4B-Q4_K_M.gguf',chat_handler=handler,n_ctx=4096,n_threads=4,n_threads_batch=8,n_gpu_layers=0,n_batch=128,n_ubatch=128,flash_attn=True,verbose=False)
images=[('ru',Image.open(fixtures/'handwritten-ru-august.png').convert('RGB'),['август']),('be',render_pdf_page(fixtures/'handwritten-be-kupala.pdf',1),['Беларусы','крыўду','людзьмі']),('de',Image.open(fixtures/'handwritten-de-row5.jpg').convert('RGB'),['Die Seerose blüht auf dem Teich']),('en',Image.open(root/'harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof/real-handwritten-title-author-input-v1.png').convert('RGB'),['Dreams','Langston Hughes'])]
page=render_pdf_page(fixtures/'handwritten-be-kupala.pdf',1)
previous=next(row for row in json.loads((e/'2026-10-14-cyrillic-ocr-probe-results-v1.json').read_text()) if row['language']=='be' and row['profile']=='official-upscale')
lines=parse_spotting(previous['raw_special'],page.width,page.height)
for index,gt in [(2,['Беларусы']),(5,['Сваю','крыўду']),(8,['На','свет','цэлы']),(11,['людзьмі','звацца'])]:
 x0,y0,x1,y1=lines[index]['bbox'];crop=page.crop((max(0,int(x0)-8),max(0,int(y0)-8),min(page.width,int(x1)+8),min(page.height,int(y1)+8)))
 images.append(('be-line-'+str(index),crop,gt))
records=[]
try:
 for language,image,gt in images:
  content=BytesIO();image.save(content,format='PNG');start=time.monotonic()
  prompt='Transcribe exactly the text visible in this image. The supported languages are Russian, Belarusian, English and German. Preserve the original language, alphabet, spelling and line breaks, including Cyrillic і, ў, ё and Latin ä, ö, ü, ß when present. Return only the transcription. Do not translate, modernize, correct or explain the text.'
  result=handler(llama=model,messages=[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(content.getvalue()).decode()}},{'type':'text','text':prompt}]}],enable_thinking=False,temperature=0,max_tokens=0)
  text=result['choices'][0]['message']['content'];record={'language':language,'original_size':image.size,'prompt':prompt,'thinking':False,'text':text,'usage':result['usage'],'finish':result['choices'][0]['finish_reason'],'seconds':time.monotonic()-start,'independent_gt':gt,'missing':[v for v in gt if v.casefold() not in text.casefold()]};records.append(record);print(json.dumps(record,ensure_ascii=False),flush=True)
finally:
 model.close();p=e/'2026-10-14-qwen4b-ocr-multilingual-results-v3.json';assert not p.exists();p.write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n');print('Native candidate closed:',model._ctx.ctx is None,flush=True)
