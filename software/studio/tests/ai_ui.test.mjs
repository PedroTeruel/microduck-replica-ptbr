import test from 'node:test';
import assert from 'node:assert/strict';
import { blankDraft, draftFrom, isDirty, missingFields, requestMessages } from '../web/ai-ui-state.js';

const saved = { id:'a', revision:1, name:'one', provider:'doubao_ark', base_url:'https://ark.cn-beijing.volces.com/api/v3', model:'mine', auth_mode:'bearer', key_configured:true };
test('a public saved connection becomes a clean blank-key form', () => {
  const form = draftFrom(saved);
  assert.equal(form.api_key,'');
  assert.equal(isDirty(form,saved),false);
  assert.deepEqual(missingFields(form,saved),[]);
  assert.equal(isDirty({...form,model:'changed'},saved),true);
});
test('destination change and explicit clear cannot use the retained credential', () => {
  assert.deepEqual(missingFields({...draftFrom(saved),base_url:'https://other.example'},saved),['API Key']);
  assert.deepEqual(missingFields({...draftFrom(saved),clear_key:true},saved),['API Key']);
  assert.deepEqual(missingFields({...draftFrom(saved),provider:'openai_compatible'},saved),['API Key']);
  assert.equal(isDirty(blankDraft(),null),false);
  assert.equal(isDirty({...blankDraft(),name:'draft'},null),true);
});
test('request context contains bounded whole pairs with a final user message', () => {
  const history = Array.from({length:12},(_,i)=>({role:i%2?'assistant':'user',content:'x'.repeat(2000)}));
  const result = requestMessages(history,'next');
  assert.equal(result[0].role,'user');
  assert.equal(result.at(-1).content,'next');
  assert.ok(result.length<=11);
  assert.ok(result.reduce((n,m)=>n+m.content.length,0)<=12000);
});
test('long assistant replies remain intact and excess context drops whole old turns', () => {
  const history = [{role:'user',content:'first'}, {role:'assistant',content:'x'.repeat(4000)}];
  const next = requestMessages(history,'next question');
  assert.deepEqual(next,[...history,{role:'user',content:'next question'}]);
  const full = [
    {role:'user',content:'old'.repeat(500)}, {role:'assistant',content:'x'.repeat(4000)},
    {role:'user',content:'recent'.repeat(250)}, {role:'assistant',content:'y'.repeat(4000)},
  ];
  const input = 'z'.repeat(2000);
  assert.deepEqual(requestMessages(full,input),[...full.slice(2),{role:'user',content:input}]);
  assert.equal(full.length,4);
});
