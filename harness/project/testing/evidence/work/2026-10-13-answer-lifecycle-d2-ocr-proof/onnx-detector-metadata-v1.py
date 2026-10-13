from pathlib import Path
import urllib.request,json
r=Path('/home/octadim/MyProjects/Multi_User_RAG_Assist_System/harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof')
with urllib.request.urlopen('https://huggingface.co/api/models/onnx-community/dfine-egret-x-rukopys-ONNX?blobs=true',timeout=30) as response:data=json.load(response)
with (r/'dfine-onnx-metadata-v1.json').open('x') as out:json.dump(data,out,indent=2);out.write('\n')
print(data['sha'],[(p['rfilename'],p.get('size')) for p in data['siblings']])
