// 数字步进控件的纯逻辑测试：取整、夹边界、按住连加/连减的节奏（假时钟）。
// 跑法：node --test tests/stepper.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  stepperDecimals, stepperNumber, stepperClamp, stepperStep, stepperText,
  createHoldRepeater, HOLD_DELAY_MS, HOLD_INTERVAL_MS,
} from '../web/stepper.js';

test('按 step 的小数位取整，不出现浮点尾巴', () => {
  assert.equal(stepperDecimals(0.5), 1);
  assert.equal(stepperDecimals(0.01), 2);
  assert.equal(stepperDecimals(1), 0);
  assert.equal(stepperStep(0.1, 1, { min: 0, max: 1, step: 0.1 }), 0.2);
  assert.equal(stepperStep(0.2, 1, { min: 0, max: 1, step: 0.1 }), 0.3);
  assert.equal(stepperStep(0.3, -1, { min: 0, max: 1, step: 0.1 }), 0.2);
  assert.equal(String(stepperStep(0.1, 2, { min: 0, max: 1, step: 0.1 })), '0.3');
  assert.equal(stepperStep(1.05, 1, { min: 0, max: 9, step: 0.01 }), 1.06);
});

test('碰到 min / max 就夹住', () => {
  assert.equal(stepperStep(30, 1, { min: 0, max: 30, step: 0.5 }), 30);
  assert.equal(stepperStep(29.8, 1, { min: 0, max: 30, step: 0.5 }), 30);
  assert.equal(stepperStep(0, -1, { min: 0, max: 30, step: 0.5 }), 0);
  assert.equal(stepperStep(0.2, -1, { min: 0, max: 30, step: 0.5 }), 0);
  assert.equal(stepperStep(5, 1, { min: 6, max: 9, step: 0.01 }), 6);
  assert.equal(stepperClamp(99, 0, 30), 30);
  assert.equal(stepperClamp(-1, 0, 30), 0);
});

test('空值从 min 起步；不是数字的输入交给调用方恢复原值', () => {
  assert.equal(stepperStep(null, 1, { min: 6, max: 9, step: 0.01 }), 6.01);
  assert.equal(stepperStep('', -1, { min: 6, max: 9, step: 0.01 }), 6);
  assert.equal(stepperNumber(' 7.62 '), 7.62);
  assert.equal(stepperNumber(''), null);
  assert.equal(stepperNumber('abc'), null);
  assert.equal(stepperText(7.80), '7.8');
  assert.equal(stepperText(null), '');
});

class FakeClock {
  constructor() { this.now = 0; this.seq = 0; this.tasks = new Map(); }
  setTimeout(fn, ms) { const id = ++this.seq; this.tasks.set(id, { fn, at: this.now + ms, every: 0 }); return id; }
  setInterval(fn, ms) { const id = ++this.seq; this.tasks.set(id, { fn, at: this.now + ms, every: ms }); return id; }
  clearTimeout(id) { this.tasks.delete(id); }
  clearInterval(id) { this.tasks.delete(id); }
  advance(ms) {
    const end = this.now + ms;
    for (;;) {
      let due = null;
      for (const [id, t] of this.tasks) {
        if (t.at <= end && (!due || t.at < due.at || (t.at === due.at && id < due.id))) due = { id, ...t };
      }
      if (!due) break;
      this.now = due.at;
      if (due.every) this.tasks.set(due.id, { ...due, at: this.now + due.every });
      else this.tasks.delete(due.id);
      due.fn();
    }
    this.now = end;
  }
}

test('按住：先停 400 ms，再每 80 ms 一格；stop 后不再响', () => {
  assert.equal(HOLD_DELAY_MS, 400);
  assert.equal(HOLD_INTERVAL_MS, 80);
  const clock = new FakeClock();
  let hits = 0;
  const rep = createHoldRepeater(() => { hits += 1; }, { timers: clock });
  rep.start();
  clock.advance(399);
  assert.equal(hits, 0);
  clock.advance(1);
  assert.equal(hits, 1);
  clock.advance(79);
  assert.equal(hits, 1);
  clock.advance(1);
  assert.equal(hits, 2);
  clock.advance(80);
  assert.equal(hits, 3);
  rep.stop();
  clock.advance(1000);
  assert.equal(hits, 3);
});

test('按住还没到 400 ms 就松手：一格都不响', () => {
  const clock = new FakeClock();
  let hits = 0;
  const rep = createHoldRepeater(() => { hits += 1; }, { timers: clock });
  rep.start();
  clock.advance(250);
  rep.stop();
  clock.advance(1000);
  assert.equal(hits, 0);
});
