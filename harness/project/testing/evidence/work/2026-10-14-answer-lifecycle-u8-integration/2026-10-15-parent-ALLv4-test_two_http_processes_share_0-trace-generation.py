import logging
logging.basicConfig(level=logging.DEBUG,format='%(message)s')
logging.getLogger('psycopg').setLevel(logging.WARNING)
logging.getLogger('psycopg.pool').setLevel(logging.WARNING)
from app import generation
original=generation.subprocess.Popen
def spawn(args,**kwargs):
    if '--worker' in args:
        args=[args[0],__file__,*args[3:]]
    return original(args,**kwargs)
generation.subprocess.Popen=spawn
generation.main()
