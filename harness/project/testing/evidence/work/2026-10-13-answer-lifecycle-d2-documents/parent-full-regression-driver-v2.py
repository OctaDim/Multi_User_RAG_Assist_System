from pathlib import Path
import os,subprocess
root=Path('/home/octadim/MyProjects/Multi_User_RAG_Assist_System')
evidence=root/'harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-documents'
env=dict(os.environ,RAG_OCR_DIR='/tmp/rag-answer-lifecycle-models/ocr',RAG_MODEL_PATH='/tmp/rag-answer-lifecycle-models/Qwen3.5-2B-Q4_K_M.gguf',RAG_E5_DIR='/tmp/rag-answer-lifecycle-models/e5',RAG_MULTI_API_EVIDENCE_DIR=str(evidence),RAG_MULTI_API_RUN_NAME='parent-full-v2')
codes=[]
commands=[('parent-all-app-v2.txt',['xvfb-run','-a','uv','run','--project','backend','--frozen','--cache-dir','/tmp/rag-answer-lifecycle-uv-cache','pytest','-c','backend/pyproject.toml','backend/tests','--basetemp','/tmp/rag-d2-full-v2','-q','-s','--assert=plain']),('parent-all-harness-v2.txt',['uv','run','--project','backend','--frozen','--cache-dir','/tmp/rag-answer-lifecycle-uv-cache','pytest','-c','pytest.ini','-q'])]
for name,command in commands:
 log=evidence/name
 with log.open('x') as out:
  out.write('Canonical D2 full accumulated application regression and complete active harness.\n'+repr(command)+'\n');out.flush()
  result=subprocess.run(command,cwd=root,env=env,stdout=out,stderr=subprocess.STDOUT)
 codes.append(result.returncode)
 print(name,flush=True)
 print('\n'.join(log.read_text().splitlines()[-25:]),flush=True)
for name in ['first-supervisor.log','second-supervisor.log','competing-supervisor.log','healthy-supervisor.log']:
 for index,source in enumerate(Path('/tmp/rag-d2-full-v2').rglob(name)):
  with (evidence/name.replace('.log',f'-parent-full-v2-{index}.txt')).open('xb') as out: out.write(source.read_bytes())
raise SystemExit(any(codes))
