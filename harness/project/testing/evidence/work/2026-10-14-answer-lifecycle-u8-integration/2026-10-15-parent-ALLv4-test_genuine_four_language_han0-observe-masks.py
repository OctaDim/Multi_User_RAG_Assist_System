import hashlib,json,os
from pathlib import Path
from app.ocr import DocumentOCR
original=DocumentOCR.finish_page
original_transcribe=DocumentOCR.transcribe
trace=Path('/tmp/rag-u8-all-application-v4/test_genuine_four_language_han0/actual-pre-recognition-masks.jsonl')
identities={}
def identity(model,projector):
    paths=(model,projector)
    if paths not in identities:
        identities[paths]=[]
        for path in paths:
            with open(path,'rb') as source:identities[paths].append(hashlib.file_digest(source,'sha256').hexdigest())
    return identities[paths]
def finish(self,prepared,cancelled):
    self.observed_source_mode=prepared['mode']
    self.observed_handwriting_calls=[]
    image=prepared['image']
    for region in prepared['handwriting']:
        x0,y0,x1,y1=region['bbox']
        assert image.crop((x0,y0,x1,y1)).getextrema()==((255,255),(255,255),(255,255))
    record={'mode':prepared['mode'],'image_sha256':hashlib.sha256(image.tobytes()).hexdigest(),
        'size':image.size,'skips':prepared['skips'],'handwriting':prepared['handwriting'],
        'printed_model':self.model.model_path,'handwriting_model':self.handwriting_model.model_path,
        'printed_identity':identity(self.model.model_path,str(Path(os.environ['RAG_OCR_DIR'])/'PaddleOCR-VL-1.5-mmproj.gguf')),
        'handwriting_identity':identity(self.handwriting_model.model_path,str(Path(os.environ['RAG_OCR_DIR'])/'mmproj-F16.gguf'))}
    with trace.open('a') as out:out.write(json.dumps(record,ensure_ascii=False)+'\n')
    result=original(self,prepared,cancelled)
    with (trace.parent/'actual-printed-texts.jsonl').open('a') as out:
        out.write(json.dumps({'mode':prepared['mode'],'printed_text':' '.join(row['text'] for row in result['regions'] if row['kind']=='printed'),
            'handwritten_text':' '.join(row['text'] for row in result['regions'] if row['kind']=='handwritten'),
            'handwriting_calls':self.observed_handwriting_calls,'regions':result['regions']},ensure_ascii=False)+'\n')
    return result
def transcribe(self,image,cancelled=None):
    assert self.observed_source_mode=='complete'
    self.observed_handwriting_calls.append({'mode':self.observed_source_mode,'size':image.size,
        'sha256':hashlib.sha256(image.tobytes()).hexdigest()})
    return original_transcribe(self,image,cancelled)
DocumentOCR.finish_page=finish
DocumentOCR.transcribe=transcribe
from app.document_worker import main
main()
