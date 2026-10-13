from pathlib import Path
import urllib.request,json
r=Path('/home/octadim/MyProjects/Multi_User_RAG_Assist_System/harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof')
for slug in ['Hukyl/dfine-egret-x-rukopys','Hukyl/doclayout-yolov10-rukopys']:
 url='https://huggingface.co/api/models/'+slug+'?blobs=true'
 with urllib.request.urlopen(url,timeout=30) as response:data=json.load(response)
 name=slug.split('/')[1]
 with (r/(name+'-metadata-v1.json')).open('x') as out:json.dump(data,out,indent=2);out.write('\n')
 print(slug,data['sha'],[(p['rfilename'],p.get('size')) for p in data['siblings']],flush=True)
url='https://huggingface.co/api/models?search=dfine-egret-x-rukopys&limit=20'
with urllib.request.urlopen(url,timeout=30) as response:data=json.load(response)
with (r/'dfine-variants-v1.json').open('x') as out:json.dump(data,out,indent=2);out.write('\n')
print([p['id'] for p in data])
