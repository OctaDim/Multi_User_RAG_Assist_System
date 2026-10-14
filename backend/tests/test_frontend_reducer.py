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
