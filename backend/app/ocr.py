import base64
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
from threading import Event, Lock

from PIL import Image, ImageDraw
import numpy as np
import onnxruntime as ort
import pypdfium2 as pdfium
from llama_cpp import Llama
import llama_cpp as native
from llama_cpp.llama_chat_format import MTMDChatHandler

from app.auth import AccessError


SKIP_TEXT = 'Рукописный текст пропущен. Для распознавания требуется разрешение OCR рукописей'
LOCATIONS = re.compile(r'(.*?)(?P<wrapped><\|LOC_BEGIN\|>)?(?P<coordinates>(?:<\|LOC_\d+\|>){8})(?(wrapped)<\|LOC_END\|>)', re.S)


def render_pdf_page(path,number):
    with pdfium.PdfDocument(path) as document:
        if number<1 or number>len(document):
            raise AccessError('not_found',404)
        page=document[number-1]
        try:
            bitmap=page.render(scale=1200/page.get_width())
            try:
                return bitmap.to_pil().convert('RGB')
            finally:
                bitmap.close()
        finally:
            page.close()


def parse_spotting(raw, width, height):
    lines, end = [], 0
    for match in LOCATIONS.finditer(raw):
        text = match.group(1).strip()
        if text.startswith('<|TEXT_START|>') and text.endswith('<|TEXT_END|>'):
            text = text[len('<|TEXT_START|>'):-len('<|TEXT_END|>')].strip()
        values = [int(value) for value in re.findall(r'<\|LOC_(\d+)\|>', match.group('coordinates'))]
        if not text or '<|LOC_' in text or any(value > 1000 for value in values):
            raise AccessError('invalid_ocr_coordinates', 422)
        polygon = [[values[index]/1000*width, values[index+1]/1000*height] for index in range(0,8,2)]
        xs, ys = [point[0] for point in polygon], [point[1] for point in polygon]
        bbox = [min(xs), min(ys), max(xs), max(ys)]
        area = sum(point[0]*polygon[(index+1)%4][1]-polygon[(index+1)%4][0]*point[1] for index,point in enumerate(polygon))
        if bbox[0] >= bbox[2] or bbox[1] >= bbox[3] or abs(area) < 1e-8:
            raise AccessError('invalid_ocr_coordinates', 422)
        lines.append({'kind':'printed','text':text,'bbox':bbox,'polygon':polygon})
        end = match.end()
    if raw[end:].strip():
        raise AccessError('unlocated_ocr_text', 422)
    return lines


def compose_page(lines, skips):
    blocks = [dict(line) for line in lines]
    # Keep the recognizer's printed reading order and insert omissions in their column.
    for skip in sorted(skips, key=lambda value:(value['bbox'][1],value['bbox'][0]), reverse=True):
        x0,y0,x1,_ = skip['bbox']
        candidates = [(index,value) for index,value in enumerate(blocks)
                      if value['kind']!='skip' and min(x1,value['bbox'][2])>max(x0,value['bbox'][0])]
        following = next((index for index,value in candidates if value['bbox'][1]>=y0),None)
        preceding = [index for index,value in candidates if value['bbox'][1]<y0]
        index = following if following is not None else preceding[-1]+1 if preceding else len(blocks)
        blocks.insert(index,dict(skip))
    text, regions = '', []
    for block in blocks:
        start = len(text)
        text += block['text']
        regions.append(block | {'start':start,'end':len(text)})
        text += '\n'
    return {'text':text,'regions':regions}


class DocumentOCR:
    def __init__(self):
        root = Path(os.environ['RAG_OCR_DIR'])
        self.config = json.loads((root/'dfine/config.json').read_text())
        processing = json.loads((root/'dfine/preprocessor_config.json').read_text())
        if processing['do_normalize'] or processing['size']!={'height':640,'width':640} or not self.config['use_focal_loss']:
            raise AccessError('ocr_profile_mismatch',503)
        options = ort.SessionOptions()
        options.intra_op_num_threads=2
        options.inter_op_num_threads=1
        self.detector = ort.InferenceSession(str(root/'dfine/model.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
        handler = MTMDChatHandler(str(root/'PaddleOCR-VL-1.5-mmproj.gguf'),use_gpu=False,verbose=False)
        # OCR uses the model's full trained context, independent of RAG's 4096 context.
        self.model = Llama(model_path=str(root/'PaddleOCR-VL-1.5.gguf'),chat_handler=handler,n_ctx=0,
                           n_threads=4,n_threads_batch=8,n_gpu_layers=0,n_batch=128,n_ubatch=128,flash_attn=True,verbose=False)
        self.lock = Lock()

    def page_count(self,path):
        with pdfium.PdfDocument(path) as document:
            count = len(document)
        if count < 1:
            raise AccessError('empty_pdf',422)
        return count

    def detect_handwriting(self,image):
        batch = np.asarray(image.resize((640,640),Image.Resampling.BILINEAR),dtype=np.float32)/255
        logits,boxes = self.detector.run(None,{'pixel_values':np.ascontiguousarray(batch.transpose(2,0,1)[None])})
        scores = 1/(1+np.exp(-logits[0]))
        handwritten = next(int(key) for key,value in self.config['id2label'].items() if value=='handwritten')
        regions = []
        for index in np.argsort(scores[:,handwritten])[::-1]:
            confidence = float(scores[index,handwritten])
            if confidence < .5:
                continue
            cx,cy,w,h = boxes[0,index]
            bbox = [max(0,math.floor((cx-w/2)*image.width)-12),max(0,math.floor((cy-h/2)*image.height)-12),
                    min(image.width,math.ceil((cx+w/2)*image.width)+12),min(image.height,math.ceil((cy+h/2)*image.height)+12)]
            if bbox[0]<bbox[2] and bbox[1]<bbox[3]:
                regions.append({'bbox':bbox,'detection_confidence':confidence})
        return regions

    def recognize(self,image,cancelled=None):
        cancelled = cancelled if cancelled is not None else Event()
        with self.lock:
            if cancelled.is_set():
                raise AccessError('document_processing_cancelled',409)
            callback = native.ggml_abort_callback(lambda _:cancelled.is_set())
            native.llama_set_abort_callback(self.model._ctx.ctx,callback,None)
            try:
                return self._recognize(image)
            except Exception:
                if cancelled.is_set():
                    raise AccessError('document_processing_cancelled',409) from None
                raise
            finally:
                native.llama_set_abort_callback(self.model._ctx.ctx,native.ggml_abort_callback(),None)

    def _recognize(self,image):
        data=BytesIO()
        image.save(data,format='PNG')
        uri='data:image/png;base64,'+base64.b64encode(data.getvalue()).decode()
        result=self.model.create_chat_completion(messages=[{'role':'user','content':[
            {'type':'image_url','image_url':{'url':uri}}, {'type':'text','text':'Spotting:'},
        ]}],temperature=0,max_tokens=0)
        if result['choices'][0]['finish_reason']!='stop':
            raise AccessError('ocr_truncated',422)
        count=result['usage']['completion_tokens']
        # Ordinary completion text hides LOC control tokens; native EOS has evaluated all emitted tokens.
        tokens=self.model.input_ids[self.model.n_tokens-count:self.model.n_tokens].tolist()
        raw=self.model.detokenize(tokens,special=True).decode('utf-8')
        return parse_spotting(raw,image.width,image.height)

    def prepare_page(self,path,number,mode):
        image=render_pdf_page(path,number)
        return self.prepare_image(image,mode)

    def prepare_image(self,image,mode):
        handwriting=self.detect_handwriting(image)
        skips=[]
        if mode=='skip_handwriting':
            image=image.copy()
            draw=ImageDraw.Draw(image)
            for region in handwriting:
                draw.rectangle(region['bbox'],fill='white')
                skips.append(region | {'kind':'skip','text':SKIP_TEXT,'reason':'handwriting_permission'})
        return {'image':image,'handwriting':handwriting,'skips':skips,'mode':mode}

    def finish_page(self,prepared,cancelled):
        lines=self.recognize(prepared['image'],cancelled)
        if prepared['mode']=='complete':
            for line in lines:
                bx0,by0,bx1,by1=line['bbox']
                if any(min(bx1,r['bbox'][2])>max(bx0,r['bbox'][0]) and min(by1,r['bbox'][3])>max(by0,r['bbox'][1]) for r in prepared['handwriting']):
                    line['kind']='handwritten'
        return compose_page(lines,prepared['skips'])

    def close(self):
        with self.lock:
            self.model.close()
