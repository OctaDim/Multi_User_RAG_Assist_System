import json
from pathlib import Path
from app.ocr import DocumentOCR
from app.auth import AccessError
original_prepare=DocumentOCR.prepare_page
original_finish=DocumentOCR.finish_page
trace=Path('/tmp/rag-u8-all-application-v4/test_actual_twenty_page_failur1/actual-finished-pages.jsonl')
def prepare(self,path,number,mode):
    if number==16:raise AccessError('u8_controlled_page_fault',422)
    return original_prepare(self,path,number,mode)
def finish(self,prepared,cancelled):
    result=original_finish(self,prepared,cancelled)
    with trace.open('a') as output:output.write(json.dumps({'text':result['text'],'regions':result['regions'],'mode':prepared['mode'],'skips':prepared['skips']},ensure_ascii=False)+'\n')
    return result
DocumentOCR.prepare_page=prepare
DocumentOCR.finish_page=finish
from app.document_worker import main
main()
