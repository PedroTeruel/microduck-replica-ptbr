import test from 'node:test';
import assert from 'node:assert/strict';
import { audioLabel, rhythmLabel } from '../web/audio-ui-state.js';
import * as audioUI from '../web/audio-ui-state.js';

test('listening state is explicit so R3 clicks are observable', () => {
  assert.equal(audioLabel({available:true,listening:false}), '监听已关闭');
  assert.equal(audioLabel({available:true,listening:true}), '正在听你说话');
  assert.equal(audioLabel({available:true,listening:true,music:true}), '正在听音乐和提问');
  assert.equal(audioLabel({available:false}), '语音服务未连接');
});
test('uncertain or stale music does not display an invented beat or genre', () => {
  assert.equal(rhythmLabel({confidence:0,bpm:120,feel:'lively',age:0}), '等待清晰节拍');
  assert.equal(rhythmLabel({confidence:.9,bpm:120,feel:'lively',age:.8}), '等待清晰节拍');
  assert.equal(rhythmLabel({confidence:.9,bpm:120,feel:'lively',age:.02}), '轻快 · 120 BPM');
  assert.equal(rhythmLabel({confidence:.9,bpm:100,feel:'sway',age:.02}), '摇摆 · 100 BPM');
});
test('standalone music distinguishes waiting for stable beats from actual motion', () => {
  const motion = {state:'idle_motion', idle_kind:'music', idle_phase:'waiting'};
  assert.equal(audioUI.musicMotionLabel?.(motion), '等待稳定节拍');
  assert.equal(audioUI.musicMotionLabel?.({...motion, idle_phase:'moving'}), '随乐律动中');
  assert.equal(audioUI.musicMotionLabel?.({...motion, idle_phase:'waiting'}), '等待稳定节拍');
  assert.equal(audioUI.musicMotionLabel?.({...motion, idle_phase:null}), '等待稳定节拍');
});
test('music phase labels leave ordinary recording and lively status labels alone', () => {
  assert.equal(audioUI.musicMotionLabel?.({state:'recording', idle_kind:'music', idle_phase:'moving'}), null);
  assert.equal(audioUI.musicMotionLabel?.({state:'idle_motion', idle_kind:'lively'}), null);
  assert.equal(audioUI.musicMotionLabel?.({state:'idle'}), null);
});
