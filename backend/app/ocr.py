import base64
import hashlib
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
from app.configuration import load_settings
from app.ocr_fragments import fragment_boxes, merge_fragments, translate_region


SKIP_TEXT = 'Рукописный текст пропущен. Для распознавания требуется разрешение OCR рукописей'
LOCATIONS = re.compile(r'(.*?)(?P<wrapped><\|LOC_BEGIN\|>)?(?P<coordinates>(?:<\|LOC_\d+\|>){8})(?(wrapped)<\|LOC_END\|>)', re.S)


def render_pdf_page(path,number):
    with pdfium.PdfDocument(path) as document:
        if number<1 or number>len(document):
            raise AccessError('not_found',404)
        page=document[number-1]
        try:
            bitmap=page.render(scale=load_settings('ocr')['geometry']['render_width']/page.get_width())
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
    # Keep printed reading order and insert handwriting or omissions in their column.
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


def ink_mask(image):
    """Image-derived foreground threshold; no text, language or known answer."""
    gray=np.asarray(image.convert('L'))
    threshold=load_settings('ocr')['geometry']['foreground_threshold']
    histogram=np.bincount(gray[gray<threshold].ravel(),minlength=256).astype(float)
    if not histogram.sum():
        return np.zeros(gray.shape,dtype=bool)
    if np.count_nonzero(histogram)==1:
        return gray<threshold
    weight=np.cumsum(histogram);moment=np.cumsum(histogram*np.arange(256))
    variance=(moment[-1]*weight-moment*weight[-1])**2/np.maximum(weight*(weight[-1]-weight),1)
    return (gray<threshold) & (gray<=int(variance.argmax()))


def ink_components(foreground):
    """Connected original foreground; never derive a new threshold after masking."""
    mask=foreground.copy();height,width=mask.shape;regions=[]
    for y,x in zip(*np.where(mask)):
        if not mask[y,x]:continue
        stack=[(int(y),int(x))];mask[y,x]=False;count=0
        x0=x1=int(x);y0=y1=int(y)
        while stack:
            yy,xx=stack.pop();count+=1
            x0=min(x0,xx);x1=max(x1,xx);y0=min(y0,yy);y1=max(y1,yy)
            for dy,dx in [(0,1),(0,-1),(1,0),(-1,0),(1,1),(1,-1),(-1,1),(-1,-1)]:
                ry,rx=yy+dy,xx+dx
                if 0<=ry<height and 0<=rx<width and mask[ry,rx]:
                    mask[ry,rx]=False;stack.append((ry,rx))
        regions.append({'bbox':[x0,y0,x1+1,y1+1],'pixels':count})
    return regions


class DocumentOCR:
    def __init__(self):
        root = Path(os.environ['RAG_OCR_DIR'])
        profiles=load_settings('ocr')
        self.config = json.loads((root/'dfine/config.json').read_text())
        processing = json.loads((root/'dfine/preprocessor_config.json').read_text())
        if processing['do_normalize'] or processing['size']!={'height':640,'width':640} or not self.config['use_focal_loss']:
            raise AccessError('ocr_profile_mismatch',503)
        options = ort.SessionOptions()
        options.intra_op_num_threads=profiles['detector']['intra_op_num_threads']
        options.inter_op_num_threads=profiles['detector']['inter_op_num_threads']
        self.detector = ort.InferenceSession(str(root/'dfine/model.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
        self.lock = Lock()
        self.model = None
        self.handwriting_model = None
        try:
            for role in ('printed','handwriting'):
                profile=profiles[role]
                model=root/profile['model'] if role=='printed' else Path(os.environ.get('RAG_OCR_MODEL_PATH') or os.environ['RAG_MODEL_PATH'])
                projector=root/profile['projector']
                for path,digest in [(model,profile['model_sha256']),(projector,profile['projector_sha256'])]:
                    with path.open('rb') as source:
                        if hashlib.file_digest(source,'sha256').hexdigest()!=digest:
                            raise AccessError('ocr_profile_mismatch',503)
                handler=MTMDChatHandler(str(projector),use_gpu=False,verbose=False)
                instance=Llama(model_path=str(model),chat_handler=handler,n_ctx=profile['n_ctx'],
                    **profiles['execution'],n_gpu_layers=0,flash_attn=True,verbose=False)
                if role=='printed':self.model=instance
                else:self.handwriting_model=instance
        except BaseException:
            self.close()
            raise

    def page_count(self,path):
        with pdfium.PdfDocument(path) as document:
            count = len(document)
        if count < 1:
            raise AccessError('empty_pdf',422)
        return count

    def detect_handwriting(self,image):
        # Detect on original pixels once. A D-FINE hit must not suppress missed
        # cursive elsewhere, and a partial box must cover its full ink component.
        components=ink_components(ink_mask(image))
        geometry=load_settings('ocr')['geometry']
        padding=geometry['padding']
        regions=self.detect_text_regions(image)
        def intersects(a,b):
            return min(a[2],b[2])>max(a[0],b[0]) and min(a[3],b[3])>max(a[1],b[1])
        for component in components:
            x0,y0,x1,y1=component['bbox'];w,h=x1-x0,y1-y0
            touching=[region for region in regions if intersects(region['bbox'],component['bbox'])]
            if touching:
                for region in touching:
                    box=region['bbox']
                    region['bbox']=[max(0,min(box[0],x0-padding)),max(0,min(box[1],y0-padding)),
                        min(image.width,max(box[2],x1+padding)),min(image.height,max(box[3],y1+padding))]
                    region['coordinate_source']='dfine_layout_and_original_ink'
            elif (h>=geometry['component_min_height'] and w/h>geometry['component_min_aspect']
                    and component['pixels']>=geometry['component_min_pixels']
                    and component['pixels']/(w*h)<geometry['component_max_density']):
                regions.append({'kind':'handwritten','bbox':[max(0,x0-padding),max(0,y0-padding),min(image.width,x1+padding),min(image.height,y1+padding)],
                    'detection_source':'connected_ink','coordinate_source':'original_ink_component'})
        # Expansion can make multiple layout detections describe the same
        # source ink. Union those crops rather than transcribing duplicates.
        merged=[]
        for region in regions:
            candidate=dict(region)
            index=0
            while index<len(merged):
                prior=merged[index];a=candidate['bbox'];b=prior['bbox']
                overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
                if overlap>=geometry['region_union_overlap']*min((a[2]-a[0])*(a[3]-a[1]),(b[2]-b[0])*(b[3]-b[1])):
                    detections=candidate.get('detections',[dict(candidate)])+prior.get('detections',[dict(prior)])
                    candidate={'kind':'handwritten','bbox':[min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3])],
                        'coordinate_source':'original_ink_region_union','detections':detections}
                    merged.pop(index);index=0
                else:index+=1
            merged.append(candidate)
        return sorted(merged,key=lambda region:(region['bbox'][1],region['bbox'][0]))

    def detect_text_regions(self,image):
        # Embedded DOCX crops can be much smaller than the detector's page
        # input. Keep their original aspect and pixels with white page context
        # instead of stretching a two-line crop to fill the entire page.
        offset_x = offset_y = 0
        settings=load_settings('ocr')
        padding=settings['geometry']['padding']
        detection_image = image
        if image.width < 640 and image.height < 640:
            detection_image = Image.new('RGB',(640,640),'white')
            offset_x, offset_y = (640-image.width)//2, (640-image.height)//2
            detection_image.paste(image,(offset_x,offset_y))
        batch = np.asarray(detection_image.resize((640,640),Image.Resampling.BILINEAR),dtype=np.float32)/255
        logits,boxes = self.detector.run(None,{'pixel_values':np.ascontiguousarray(batch.transpose(2,0,1)[None])})
        scores = 1/(1+np.exp(-logits[0]))
        handwritten=next(int(key) for key,value in self.config['id2label'].items() if value=='handwritten')
        regions = []
        for index in np.argsort(scores[:,handwritten])[::-1]:
            confidence = float(scores[index,handwritten])
            if confidence < settings['detector']['confidence']:
                continue
            cx,cy,w,h = boxes[0,index]
            bbox = [max(0,math.floor((cx-w/2)*detection_image.width)-offset_x-padding),max(0,math.floor((cy-h/2)*detection_image.height)-offset_y-padding),
                    min(image.width,math.ceil((cx+w/2)*detection_image.width)-offset_x+padding),min(image.height,math.ceil((cy+h/2)*detection_image.height)-offset_y+padding)]
            if bbox[0]<bbox[2] and bbox[1]<bbox[3]:
                regions.append({'kind':'handwritten','bbox':bbox,'detection_confidence':confidence,'coordinate_source':'dfine_layout'})
        return sorted(regions,key=lambda region:(region['bbox'][1],region['bbox'][0]))

    def recognize(self,image,cancelled=None):
        return self._run_native(self.model,self._recognize,image,cancelled)

    def _run_native(self,model,operation,image,cancelled):
        cancelled = cancelled if cancelled is not None else Event()
        with self.lock:
            if cancelled.is_set():
                raise AccessError('document_processing_cancelled',409)
            callback = native.ggml_abort_callback(lambda _:cancelled.is_set())
            native.llama_set_abort_callback(model._ctx.ctx,callback,None)
            try:
                return operation(image)
            except Exception:
                if cancelled.is_set():
                    raise AccessError('document_processing_cancelled',409) from None
                raise
            finally:
                native.llama_set_abort_callback(model._ctx.ctx,native.ggml_abort_callback(),None)

    def _recognize(self,image):
        data=BytesIO();image.save(data,format='PNG')
        uri='data:image/png;base64,'+base64.b64encode(data.getvalue()).decode()
        result=self.model.create_chat_completion(messages=[{'role':'user','content':[
            {'type':'image_url','image_url':{'url':uri}}, {'type':'text','text':load_settings('prompts')['ocr']['printed']},
        ]}],temperature=0,max_tokens=load_settings('ocr')['decoding']['max_tokens'])
        if result['choices'][0]['finish_reason']!='stop':
            raise AccessError('ocr_truncated',422)
        count=result['usage']['completion_tokens']
        tokens=self.model.input_ids[self.model.n_tokens-count:self.model.n_tokens].tolist()
        raw=self.model.detokenize(tokens,special=True).decode('utf-8')
        return parse_spotting(raw,image.width,image.height)

    def transcribe(self,image,cancelled=None):
        return self._run_native(self.handwriting_model,self._transcribe,image,cancelled)

    def _transcribe(self,image):
        data=BytesIO();image.save(data,format='PNG')
        uri='data:image/png;base64,'+base64.b64encode(data.getvalue()).decode()
        result=self.handwriting_model.chat_handler(llama=self.handwriting_model,messages=[{'role':'user','content':[
            {'type':'image_url','image_url':{'url':uri}}, {'type':'text','text':load_settings('prompts')['ocr']['handwriting']},
        ]}],enable_thinking=False,temperature=0,max_tokens=load_settings('ocr')['decoding']['max_tokens'])
        if result['choices'][0]['finish_reason']!='stop':
            raise AccessError('ocr_truncated',422)
        return result['choices'][0]['message']['content']

    def prepare_page(self,path,number,mode):
        image=render_pdf_page(path,number)
        return self.prepare_image(image,mode)

    def prepare_image(self,image,mode):
        foreground=ink_mask(image)
        boxes=fragment_boxes(image)
        if len(boxes)==1:
            handwriting=self.detect_handwriting(image)
            masks=handwriting
        else:
            detected=[(box,self.detect_handwriting(image.crop(box))) for box in boxes]
            handwriting=merge_fragments(detected)
            # A hit in either overlapping view masks both printed inputs,
            # including small differences between duplicate detection boxes.
            masks=[translate_region(region,box) for box,regions in detected for region in regions]
        printed=image.copy();draw=ImageDraw.Draw(printed);skips=[]
        printed_foreground=foreground.copy()
        for region in masks:
            draw.rectangle(region['bbox'],fill='white')
            x0,y0,x1,y1=region['bbox'];printed_foreground[y0:y1+1,x0:x1+1]=False
        for region in handwriting:
            if mode=='skip_handwriting':
                skips.append(region | {'kind':'skip','text':SKIP_TEXT,'reason':'handwriting_permission'})
        prepared={'image':printed,'original':image if mode=='complete' else None,
                'handwriting':handwriting,'skips':skips,'mode':mode,'printed_ink':bool(printed_foreground.any())}
        if len(boxes)>1:
            prepared['fragments']=[(box,bool(printed_foreground[box[1]:box[3],box[0]:box[2]].any())) for box in boxes]
        return prepared

    def finish_page(self,prepared,cancelled):
        def check_cancelled():
            if cancelled is not None and cancelled.is_set():
                raise AccessError('document_processing_cancelled',409)
        check_cancelled()
        if prepared.get('fragments'):
            recognized=[]
            for box,printed_ink in prepared['fragments']:
                check_cancelled()
                if printed_ink:
                    recognized.append((box,self.recognize(prepared['image'].crop(box),cancelled)))
            lines=merge_fragments(recognized)
        else:
            lines=self.recognize(prepared['image'],cancelled) if prepared['printed_ink'] else []
        insertions=list(prepared['skips'])
        if prepared['mode']=='complete':
            for region in prepared['handwriting']:
                check_cancelled()
                x0,y0,x1,y1=region['bbox']
                text=self.transcribe(prepared['original'].crop((x0,y0,x1,y1)),cancelled)
                if text.strip():
                    insertions.append(region | {'text':text.strip(),'polygon':[[x0,y0],[x1,y0],[x1,y1],[x0,y1]]})
        check_cancelled()
        if not lines:
            return compose_page(sorted(insertions,key=lambda block:(block['bbox'][1],block['bbox'][0])),[])
        return compose_page(lines,insertions)

    def close(self):
        with self.lock:
            for model in (self.handwriting_model,self.model):
                if model is not None:model.close()
