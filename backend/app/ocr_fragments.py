"""Bounded raster inputs and geometry in original-page coordinates."""


def fragment_boxes(image):
    limit,overlap=2400,128
    if max(image.size)<=limit:
        return [(0,0,image.width,image.height)]
    # Search near each cut for a blank row/column, keeping the full overlap.
    projections=image.convert('L').point(lambda value:255 if value<245 else 0).getprojection()
    def ranges(length,projection):
        result=[];start=0
        while True:
            end=min(start+limit,length)
            if end<length:
                end=next((cut for cut in range(end,end-overlap,-1) if not projection[cut-1]),end)
            result.append((start,end))
            if end==length:
                return result
            start=end-overlap
    xs,ys=(ranges(length,projection) for length,projection in zip(image.size,projections))
    return [(x0,y0,x1,y1) for y0,y1 in ys for x0,x1 in xs]


def translate_region(region,box):
    x,y=box[:2]
    result=dict(region)
    x0,y0,x1,y1=region['bbox']
    result['bbox']=[x0+x,y0+y,x1+x,y1+y]
    if 'polygon' in region:
        result['polygon']=[[px+x,py+y] for px,py in region['polygon']]
    if 'detections' in region:
        result['detections']=[translate_region(value,box) for value in region['detections']]
    return result


def _reading_order(regions):
    """Read columns top to bottom, with spanning headings/footers outside them."""
    rows=sorted(regions,key=lambda row:(row['bbox'][1],row['bbox'][0]))
    prefix,suffix=[],[]
    while len(rows)>1:
        left=min(row['bbox'][0] for row in rows)
        right=max(row['bbox'][2] for row in rows)
        first,last=rows[0]['bbox'],max(rows,key=lambda row:row['bbox'][3])['bbox']
        if first[2]-first[0]>=.8*(right-left) and first[3]<=min(row['bbox'][1] for row in rows[1:]):
            prefix.append(rows.pop(0))
        elif last[2]-last[0]>=.8*(right-left) and all(row['bbox']==last or row['bbox'][3]<=last[1] for row in rows):
            index=next(index for index,row in enumerate(rows) if row['bbox']==last)
            suffix.insert(0,rows.pop(index))
        else:
            break
    groups=[];edge=None
    for row in sorted(rows,key=lambda row:row['bbox'][0]):
        if edge is None or row['bbox'][0]>edge:
            groups.append([])
        groups[-1].append(row)
        edge=max(edge if edge is not None else row['bbox'][2],row['bbox'][2])
    middle=[row for group in groups for row in _reading_order(group)] if len(groups)>1 else rows
    return prefix+middle+suffix


def merge_fragments(fragments):
    """Deduplicate the same ink across overlaps, never deduplicate by text."""
    kept=[]
    for index,(box,regions) in enumerate(fragments):
        for local in regions:
            region=translate_region(local,box)
            a=region['bbox'];area=(a[2]-a[0])*(a[3]-a[1])
            # Prefer an intact detection over a box clipped at an input edge.
            clipped=sum(abs(value-boundary)<=1 for value,boundary in zip(a,box))
            score=(-clipped,area)
            for position,(prior,source,prior_score) in enumerate(kept):
                if source==index or prior['kind']!=region['kind']:
                    continue
                b=prior['bbox'];prior_area=(b[2]-b[0])*(b[3]-b[1])
                intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
                if intersection>=.8*min(area,prior_area) and intersection>=.5*max(area,prior_area):
                    if score>prior_score:
                        kept[position]=(region,index,score)
                    break
            else:
                kept.append((region,index,score))
    return _reading_order([region for region,_,_ in kept])
