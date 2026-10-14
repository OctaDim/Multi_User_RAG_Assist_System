import logging
logging.basicConfig(level=logging.DEBUG,format='%(message)s')
logging.getLogger('psycopg').setLevel(logging.WARNING)
logging.getLogger('psycopg.pool').setLevel(logging.WARNING)
from app import generation
original_finish=generation.Coordinator.finish
async def traced_finish(self,request_id,state,reason):
    generation.trace('native_finish_attempt',request=str(request_id),epoch=self.epoch,
                     step=self.step_number,revision=self.revision,state=state,reason=reason)
    return await original_finish(self,request_id,state,reason)
generation.Coordinator.finish=traced_finish
original=generation.subprocess.Popen
def spawn(args,**kwargs):
    if '--worker' in args:args=[args[0],__file__,*args[3:]]
    return original(args,**kwargs)
generation.subprocess.Popen=spawn
generation.main()
