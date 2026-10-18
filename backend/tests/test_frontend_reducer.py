"""Pure state regression; real UI/lifetime/native proofs are separate browser tests."""
from pathlib import Path
import subprocess


def test_delayed_empty_snapshot_keeps_accepted_request_and_new_draft():
    script = r'''import assert from 'node:assert/strict';
globalThis.document = {querySelector: () => ({content:'http://127.0.0.1:8000'})};
globalThis.sessionStorage = {
  getItem(key) {return this[key] ?? null;},
  setItem(key,value) {this[key]=String(value);},
  removeItem(key) {delete this[key];},
};
const {Conversations}=await import('./frontend/src/conversations.js');
const {Drafts}=await import('./frontend/src/drafts.js');
const drafts=new Drafts('owner');
drafts.edit('room','New unsent draft');
const controller=Object.create(Conversations.prototype);
controller.drafts=drafts;
controller.histories=new Map([['room', {
  conversation_id:'room',watermark:5,
  requests:[{id:'accepted',version:1,operation_key:'operation',state:'accepted'}],
  messages:[{request_id:'accepted',role:'user',text:'Already accepted question'}],
}]]);
controller.install({conversation_id:'room',watermark:0,requests:[],messages:[]});
assert.deepEqual(controller.histories.get('room').requests.map(row=>row.id),['accepted']);
assert.deepEqual(controller.histories.get('room').messages.map(row=>row.text),['Already accepted question']);
assert.equal(drafts.get('room').text,'New unsent draft');
console.log('Real reducer and draft store preserved newer accepted state against an older empty snapshot.');
'''
    result=subprocess.run(['node','--experimental-default-type=module','--input-type=module','-'],
        input=script,text=True,capture_output=True,cwd=Path(__file__).resolve().parents[2],timeout=15)
    assert result.returncode==0, result.stdout+result.stderr


def test_source_status_event_marks_original_without_replacing_quote():
    script=r'''import assert from 'node:assert/strict';
globalThis.document={querySelector:()=>({content:'http://127.0.0.1:8000'})};
globalThis.sessionStorage={getItem:()=>null,removeItem:()=>{}};
const {Conversations}=await import('./frontend/src/conversations.js');
const request={id:'answer',version:3,state:'generating',answer_text:'100 euros [source:1]',citations:[{quote:'100'}]};
const controller=Object.create(Conversations.prototype);
controller.current=()=>true;controller.render=()=>{};controller.selected='room';controller.cursor=2;
controller.histories=new Map([['room',{requests:[request],messages:[]}]]);
await controller.receive({id:3,kind:'source_status',conversation_id:'room',request_id:'answer',payload:{
 version:4,state:'generating',source_flags:{document:'corrected'},excluded:true}});
assert.deepEqual(request.source_flags,{document:'corrected'});
assert.equal(request.excluded,true);assert.equal(request.state,'generating');
assert.equal(request.answer_text,'100 euros [source:1]');assert.equal(request.citations[0].quote,'100');
await controller.receive({id:4,kind:'output',conversation_id:'room',request_id:'answer',payload:{
 version:3,text:'stale',source_flags:{},excluded:false}});
assert.deepEqual(request.source_flags,{document:'corrected'});assert.equal(request.excluded,true);
'''
    result=subprocess.run(['node','--experimental-default-type=module','--input-type=module','-'],
        input=script,text=True,capture_output=True,cwd=Path(__file__).resolve().parents[2],timeout=15)
    assert result.returncode==0,result.stdout+result.stderr


def test_scope_is_per_conversation_and_pending_submission_is_immutable():
    script=r'''import assert from 'node:assert/strict';
globalThis.document={querySelector:()=>({content:'http://127.0.0.1:8000'})};
globalThis.sessionStorage={getItem(key){return this[key]??null;},setItem(key,value){this[key]=String(value);},removeItem(key){delete this[key];}};
const {Drafts}=await import('./frontend/src/drafts.js');
const drafts=new Drafts('owner');
drafts.edit('first','Question one');
drafts.selectSources('first',['missing-document']);
drafts.edit('second','Question two');
drafts.selectSources('second',['other-document']);
const body={operation_key:'operation',question:'Question one',document_ids:drafts.get('first').documentIds,tab_id:'tab'};
const pending=drafts.begin('first',body);
body.document_ids.push('must-not-leak');
drafts.edit('first','New unsent question');
drafts.selectSources('first',['replacement-document']);
drafts.accepted('first','operation');
assert.deepEqual(pending.body.document_ids,['missing-document']);
assert.deepEqual(drafts.get('first').documentIds,['replacement-document']);
assert.equal(drafts.get('first').text,'New unsent question');
assert.deepEqual(new Drafts('owner').get('second').documentIds,['other-document']);
assert.equal(drafts.get('second').text,'Question two');
assert.equal(drafts.get('first').pending,null);
drafts.selectSources('first',[]);
assert.deepEqual(drafts.get('first').documentIds,[]);
const {Conversations}=await import('./frontend/src/conversations.js');
const controller=Object.create(Conversations.prototype);
controller.documents=[{id:'other-document',ready:true},{id:'not-ready',ready:false}];
drafts.selectSources('first',['missing-document']);
assert.deepEqual(controller.effectiveSources(drafts.get('first')),[]);
drafts.selectSources('first',[]);
assert.deepEqual(controller.effectiveSources(drafts.get('first')).map(value=>value.id),['other-document']);
controller.current=()=>true;controller.render=()=>{};controller.list=()=>{};
controller.drafts=drafts;controller.histories=new Map();controller.selected='second';controller.cursor=null;
const passport={scope_mode:'all',selected_document_ids:[]};
await controller.receive({id:1,kind:'accepted',conversation_id:'first',request_id:'request',payload:{
 state:'accepted',version:1,operation_key:'admitted',scope:['other-document'],question:'Accepted question',passport}});
assert.deepEqual(controller.histories.get('first').requests[0].passport,passport);
assert.equal(controller.selected,'second');
assert.equal(drafts.get('second').text,'Question two');
'''
    result=subprocess.run(['node','--experimental-default-type=module','--input-type=module','-'],
        input=script,text=True,capture_output=True,cwd=Path(__file__).resolve().parents[2],timeout=15)
    assert result.returncode==0,result.stdout+result.stderr
