"""The lease owner must not load the native worker's inference stack."""
import json
import subprocess
import sys


def test_supervisor_import_keeps_inference_dependencies_in_native_worker(tmp_path):
    result=subprocess.run([sys.executable,'-c','''
import gc,json,resource,sys
from pathlib import Path
from app.generation import Supervisor
status=Path('/proc/self/status').read_text().splitlines()
heavy=sorted(name for name in sys.modules if name.split('.')[0] in
             {'numpy','onnxruntime','langgraph','llama_cpp'} or name=='app.rag')
print(json.dumps({'heavy_modules':heavy,'gc_objects':len(gc.get_objects()),
                  'rss_kib':int(next(row for row in status if row.startswith('VmRSS:')).split()[1]),
                  'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}))
'''],cwd=tmp_path,capture_output=True,text=True,check=True,timeout=30)
    proof=json.loads(result.stdout)
    (tmp_path/'supervisor-import.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof),flush=True)
    assert proof['heavy_modules']==[],proof
