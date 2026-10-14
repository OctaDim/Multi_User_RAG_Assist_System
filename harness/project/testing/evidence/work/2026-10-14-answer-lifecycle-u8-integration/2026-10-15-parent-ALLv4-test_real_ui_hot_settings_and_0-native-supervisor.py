from app import generation
original=generation.subprocess.Popen
def spawn(args,**kwargs):
    if '--worker' in args:args=[args[0],'/tmp/rag-u8-all-application-v4/test_real_ui_hot_settings_and_0/native-worker.py',*args[3:]]
    return original(args,**kwargs)
generation.subprocess.Popen=spawn
generation.main()
