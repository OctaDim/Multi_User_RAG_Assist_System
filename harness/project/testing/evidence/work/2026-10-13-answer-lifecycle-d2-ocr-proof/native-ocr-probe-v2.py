import sys
sys.path.append('/home/octadim/MyProjects/Multi_User_RAG_Assist_System/backend/.venv/lib/python3.12/site-packages')
from pathlib import Path
import base64,json,time,resource
from llama_cpp import Llama
from llama_cpp.llama_chat_format import MTMDChatHandler
root=Path('/home/octadim/MyProjects/Multi_User_RAG_Assist_System/harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof')
assets=Path('/tmp/rag-answer-lifecycle-models/ocr')
started=time.monotonic()
handler=MTMDChatHandler(str(assets/'PaddleOCR-VL-1.5-mmproj.gguf'),use_gpu=False,verbose=True)
model=Llama(model_path=str(assets/'PaddleOCR-VL-1.5.gguf'),chat_handler=handler,n_ctx=4096,n_threads=4,n_threads_batch=8,n_gpu_layers=0,n_batch=128,n_ubatch=128,verbose=True)
try:
 image=base64.b64encode((root/'printed-four-languages-v1.png').read_bytes()).decode()
 result=model.create_chat_completion(messages=[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,'+image}},{'type':'text','text':'OCR:'}]}],temperature=0,max_tokens=0)
 summary={'input':'printed-four-languages-v1.png','result':result,'seconds':time.monotonic()-started,'maxrss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'runtime':'llama-cpp-python 0.3.36 MTMD CPU','scope':'Compatibility/printed-language proof only; not whole publisher or handwriting gate'}
 with (root/'native-ocr-result-v2.json').open('x') as out: json.dump(summary,out,ensure_ascii=False,indent=2);out.write('\n')
 print(json.dumps(summary,ensure_ascii=False),flush=True)

finally:
 model.close()
