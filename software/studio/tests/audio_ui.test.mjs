import test from 'node:test';
import assert from 'node:assert/strict';
import { audioLabel, rhythmLabel } from '../web/audio-ui-state.js';
import * as audioUI from '../web/audio-ui-state.js';

test('listening state is explicit so R3 clicks are observable', () => {
  assert.equal(audioLabel({available:true,listening:false}), 'Monitoramento desativado');
  assert.equal(audioLabel({available:true,listening:true}), 'Ouvindo você');
  assert.equal(audioLabel({available:true,listening:true,music:true}), 'Ouvindo música e perguntas');
  assert.equal(audioLabel({available:false}), 'Serviço de voz desconectado');
});
test('uncertain or stale music does not display an invented beat or genre', () => {
  assert.equal(rhythmLabel({confidence:0,bpm:120,feel:'lively',age:0}), 'Aguardando um ritmo nítido');
  assert.equal(rhythmLabel({confidence:.9,bpm:120,feel:'lively',age:.8}), 'Aguardando um ritmo nítido');
  assert.equal(rhythmLabel({confidence:.9,bpm:120,feel:'lively',age:.02}), 'Animado · 120 BPM');
  assert.equal(rhythmLabel({confidence:.9,bpm:100,feel:'sway',age:.02}), 'Balançando · 100 BPM');
});
test('standalone music distinguishes waiting for stable beats from actual motion', () => {
  const motion = {state:'idle_motion', idle_kind:'music', idle_phase:'waiting'};
  assert.equal(audioUI.musicMotionLabel?.(motion), 'Aguardando um ritmo estável');
  assert.equal(audioUI.musicMotionLabel?.({...motion, idle_phase:'moving'}), 'Movendo-se ao som da música');
  assert.equal(audioUI.musicMotionLabel?.({...motion, idle_phase:'waiting'}), 'Aguardando um ritmo estável');
  assert.equal(audioUI.musicMotionLabel?.({...motion, idle_phase:null}), 'Aguardando um ritmo estável');
});
test('music phase labels leave ordinary recording and lively status labels alone', () => {
  assert.equal(audioUI.musicMotionLabel?.({state:'recording', idle_kind:'music', idle_phase:'moving'}), null);
  assert.equal(audioUI.musicMotionLabel?.({state:'idle_motion', idle_kind:'lively'}), null);
  assert.equal(audioUI.musicMotionLabel?.({state:'idle'}), null);
});
