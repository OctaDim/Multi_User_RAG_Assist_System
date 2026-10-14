import base64,json,os
from io import BytesIO
from pathlib import Path
from PIL import Image
from app.ocr import DocumentOCR,render_pdf_page,parse_spotting
root=Path('/home/octadim/MyProjects/Multi_User_RAG_Assist_System/backend/tests/fixtures/answer_lifecycle')
out=Path('/home/octadim/MyProjects/Multi_User_RAG_Assist_System/harness/project/testing/evidence/work/2026-10-14-answer-lifecycle-u8-integration/2026-10-14-cyrillic-ocr-probe-results-v1.json')
assert not out.exists()
profiles=[('official-upscale','Spotting:',True),('original-script-instruction','Spotting: Recognize the original Cyrillic script where present. Do not transliterate.',True),('ocr-task-characterization','OCR:',True)]
images=[('ru',Image.open(root/'handwritten-ru-august.png').convert('RGB'),['август']),('be',render_pdf_page(root/'handwritten-be-kupala.pdf',1),['Беларусы','крыўду','людзьмі'])]
ocr=DocumentOCR();records=[]
try:
 for language,image,expected in images:
  for label,prompt,upscale in profiles:
   prepared=image
   if upscale and image.width<1500 and image.height<1500:prepared=image.resize((image.width*2,image.height*2),Image.Resampling.LANCZOS)
   data=BytesIO();prepared.save(data,format='PNG')
   result=ocr.model.create_chat_completion(messages=[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(data.getvalue()).decode()}},{'type':'text','text':prompt}]}],temperature=0,max_tokens=0)
   count=result['usage']['completion_tokens'];tokens=ocr.model.input_ids[ocr.model.n_tokens-count:ocr.model.n_tokens].tolist();raw=ocr.model.detokenize(tokens,special=True).decode('utf-8')
   try:lines=parse_spotting(raw,prepared.width,prepared.height);text='\n'.join(line['text'] for line in lines);valid_spans=True
   except Exception as error:text=result['choices'][0]['message']['content'];valid_spans=False
   record={'language':language,'profile':label,'prompt':prompt,'original_size':image.size,'processed_size':prepared.size,'text':text,'raw_special':raw,'finish':result['choices'][0]['finish_reason'],'valid_spotting':valid_spans,'expected_independent_gt':expected,'missing':[word for word in expected if word.casefold() not in text.casefold()]}
   records.append(record);print(json.dumps(record,ensure_ascii=False),flush=True)
finally:
 ocr.close();out.write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
 print('Native OCR context closed:',ocr.model._ctx.ctx is None,flush=True)
