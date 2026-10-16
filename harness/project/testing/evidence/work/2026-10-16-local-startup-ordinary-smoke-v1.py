from pathlib import Path
import json,os,signal,socket,subprocess,time,tomllib
from urllib.request import Request,urlopen
import psycopg
ROOT=Path("/home/octadim/MyProjects/Multi_User_RAG_Assist_System")
OUT=Path("/tmp/compound-engineering-1000/rag-local-startup-20261016")
DSN=tomllib.loads((ROOT/"backend/config/service.local.toml").read_text())["database"]["dsn"]
def listening(port):
    with socket.socket() as s:
        s.settimeout(.2)
        return s.connect_ex(("127.0.0.1",port))==0
def descendants(root):
    relations={}
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():continue
        try:
            stat=(path/"stat").read_text().rsplit(") ",1)[1].split()
            relations[int(path.name)]=int(stat[1])
        except (OSError,ValueError,IndexError):pass
    owned={root}
    while True:
        next_owned=owned|{pid for pid,parent in relations.items() if parent in owned}
        if next_owned==owned:return owned
        owned=next_owned
results=[]
env={key:value for key,value in os.environ.items() if not key.startswith("RAG_")}
for number,stop in enumerate((signal.SIGINT,signal.SIGTERM),1):
    assert not listening(8000) and not listening(8080), "ordinary ports already in use; no unrelated process will be stopped"
    backend_log=OUT/f"ordinary-backend-{number}.log"
    frontend_log=OUT/f"ordinary-frontend-{number}.log"
    processes=[];owned=set();partial=None
    with backend_log.open("x") as blog,frontend_log.open("x") as flog:
        try:
            backend=subprocess.Popen(["python3","backend/main.py"],cwd=ROOT,env=env,stdout=blog,stderr=subprocess.STDOUT,start_new_session=True)
            frontend=subprocess.Popen(["python3","frontend/main.py"],cwd=ROOT,env=env,stdout=flog,stderr=subprocess.STDOUT,start_new_session=True)
            processes=[backend,frontend]
            deadline=time.monotonic()+120
            while True:
                assert backend.poll() is None, "backend exited before readiness; inspect owned log"
                assert frontend.poll() is None, "frontend exited before readiness; inspect owned log"
                owned |= descendants(backend.pid)|descendants(frontend.pid)
                try:
                    with urlopen(Request("http://127.0.0.1:8000/api/public-settings",headers={"Origin":"http://127.0.0.1:8080"}),timeout=.4) as response:
                        api=response.status==200
                        assert response.headers.get("Access-Control-Allow-Origin")=="http://127.0.0.1:8080"
                        assert json.loads(response.read())["document_formats"]
                    with urlopen("http://127.0.0.1:8080/",timeout=.4) as response:
                        html=response.read()
                        assert b'content="http://127.0.0.1:8000"' in html
                    with psycopg.connect(DSN,autocommit=True) as db:
                        healthy=db.execute("SELECT healthy_until>clock_timestamp() FROM coordinator_lease WHERE id=1").fetchone()[0]
                    if api and healthy and "native_spawn" in backend_log.read_text():break
                except (OSError,psycopg.Error):pass
                assert time.monotonic()<deadline,"ordinary startup readiness timeout"
                time.sleep(.1)
            owned |= descendants(backend.pid)|descendants(frontend.pid)
            children=descendants(backend.pid)-{backend.pid}
            assert len(children)>=4,"API,documents,generation,native child not all owned"
            assert descendants(frontend.pid)=={frontend.pid},"unexpected frontend child service"
            partial=socket.create_connection(("127.0.0.1",8080),timeout=2)
            partial.sendall(b"GET / HTTP/1.1\r\nHost:")
            for process in processes:process.send_signal(stop)
            for process in processes:
                assert process.wait(timeout=20)==0,"main did not stop successfully"
            remaining=[pid for pid in owned if Path(f"/proc/{pid}").exists()]
            assert not remaining,f"owned processes remain: {remaining}"
            assert not listening(8000) and not listening(8080),"application socket remained open"
            with psycopg.connect(DSN) as db:
                assert db.execute("SELECT 1").fetchone()[0]==1
            record={"cycle":number,"stop":stop.name,"backend_owned_children":len(children),"owned_processes_gone":len(owned),"frontend_partial_http_open_on_stop":True,"application_ports_released":True,"postgres_survived":True}
            results.append(record)
            print(json.dumps(record),flush=True)
        finally:
            if partial is not None:partial.close()
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=15)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
(OUT/"ordinary-startup-results.json").write_text(json.dumps(results,indent=2))
print("ORDINARY_STARTUP_SMOKE_PASSED",flush=True)
