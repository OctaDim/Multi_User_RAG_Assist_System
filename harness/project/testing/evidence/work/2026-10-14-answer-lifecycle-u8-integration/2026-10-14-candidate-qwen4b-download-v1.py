from pathlib import Path
import hashlib,json,urllib.request
rev='e87f176479d0855a907a41277aca2f8ee7a09523';base='https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/'+rev+'/'
folder=Path('/tmp/rag-u8-worker-qwen4b-ocr-candidate');folder.mkdir(exist_ok=True);records=[]
for name,size,digest in [('Qwen3.5-4B-Q4_K_M.gguf',2740937888,'00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4'),('mmproj-F16.gguf',672423616,'cd88edcf8d031894960bb0c9c5b9b7e1fea6ebee02b9f7ce925a00d12891f864')]:
 p=folder/name
 with urllib.request.urlopen(base+name,timeout=60) as r,p.open('xb') as f:
  while chunk:=r.read(4*1024*1024):f.write(chunk)
 actual=hashlib.file_digest(p.open('rb'),'sha256').hexdigest();assert p.stat().st_size==size and actual==digest
 record={'url':base+name,'revision':rev,'path':str(p),'bytes':size,'sha256':actual,'purpose':'unadopted isolated OCR candidate; selected generator2B/E5/limits unchanged'};records.append(record);print(json.dumps(record),flush=True)
p=Path('/home/octadim/MyProjects/Multi_User_RAG_Assist_System/harness/project/testing/evidence/work/2026-10-14-answer-lifecycle-u8-integration/2026-10-14-qwen4b-ocr-assets-v1.json');assert not p.exists();p.write_text(json.dumps(records,indent=2)+'\n')
