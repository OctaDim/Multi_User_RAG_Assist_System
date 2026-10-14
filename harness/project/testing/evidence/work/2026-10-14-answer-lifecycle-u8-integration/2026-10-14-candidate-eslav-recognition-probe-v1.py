from pathlib import Path
import json,math
import numpy as np
import onnxruntime as ort
from PIL import Image
from app.ocr import render_pdf_page,parse_spotting
root=Path('/home/octadim/MyProjects/Multi_User_RAG_Assist_System/backend/tests/fixtures/answer_lifecycle')
evidence=Path('/home/octadim/MyProjects/Multi_User_RAG_Assist_System/harness/project/testing/evidence/work/2026-10-14-answer-lifecycle-u8-integration')
assets=Path('/tmp/rag-u8-worker-eslav-probe-assets')
chars=['blank']+(assets/'dict.txt').read_text().splitlines()+[' ']
options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
session=ort.InferenceSession(str(assets/'rec.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
print(json.dumps({'inputs':[(x.name,x.shape,x.type) for x in session.get_inputs()],'outputs':[(x.name,x.shape,x.type) for x in session.get_outputs()],'dict_count':len(chars),'contains_BE':all(x in chars for x in ['ў','і'])}),flush=True)
def recognize(image):
 w,h=image.size;target_h=48;target_w=max(320,math.ceil(w/h*target_h));resized_w=min(target_w,math.ceil(w/h*target_h))
 array=np.asarray(image.resize((resized_w,target_h),Image.Resampling.BILINEAR).convert('RGB'),dtype=np.float32)[:,:,::-1]/255
 array=(array-.5)/.5;batch=np.zeros((1,3,target_h,target_w),dtype=np.float32);batch[0,:,:,:resized_w]=array.transpose(2,0,1)
 output=session.run(None,{session.get_inputs()[0].name:batch})[0]
 assert output.shape[-1]==len(chars),(output.shape,len(chars))
 labels=output.argmax(axis=-1)[0];text=[];scores=[]
 for index,label in enumerate(labels):
  if label!=0 and (index==0 or label!=labels[index-1]):text.append(chars[label]);scores.append(float(output[0,index,label]))
 return {'text':''.join(text),'score':sum(scores)/len(scores) if scores else 0,'input_shape':list(batch.shape),'output_shape':list(output.shape)}
images=[('ru','actual word',Image.open(root/'handwritten-ru-august.png').convert('RGB')),
        ('de','actual sentence',Image.open(root/'handwritten-de-row5.jpg').convert('RGB'))]
page=render_pdf_page(root/'handwritten-be-kupala.pdf',1)
record=next(row for row in json.loads((evidence/'2026-10-14-cyrillic-ocr-probe-results-v1.json').read_text()) if row['language']=='be' and row['profile']=='official-upscale')
for i,line in enumerate(parse_spotting(record['raw_special'],page.width,page.height)):
 x0,y0,x1,y1=line['bbox'];images.append(('be',f'actual spotted line{i+1}',page.crop((max(0,math.floor(x0)-3),max(0,math.floor(y0)-3),min(page.width,math.ceil(x1)+3),min(page.height,math.ceil(y1)+3)))))
results=[]
for lang,name,image in images:
 result={'language':lang,'source':name,'size':image.size,**recognize(image)};results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
p=evidence/'2026-10-14-eslav-recognition-probe-results-v1.json';assert not p.exists();p.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
