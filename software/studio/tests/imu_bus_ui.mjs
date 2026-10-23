import assert from 'node:assert/strict';

const [base, cdp] = process.argv.slice(2);
const target = await (await fetch(`http://127.0.0.1:${cdp}/json/new?about:blank`, { method: 'PUT' })).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(resolve => ws.addEventListener('open', resolve, { once: true }));
let id = 0;
const pending = new Map(), errors = [];
ws.addEventListener('message', event => {
  const message = JSON.parse(event.data);
  if (pending.has(message.id)) { pending.get(message.id)(message); pending.delete(message.id); }
  if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
});
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const key = ++id;
  const timer = setTimeout(() => { pending.delete(key); reject(Error(`CDP timeout: ${method}`)); }, 10000);
  pending.set(key, message => { clearTimeout(timer); message.error ? reject(Error(JSON.stringify(message.error))) : resolve(message.result); });
  ws.send(JSON.stringify({ id: key, method, params }));
});
const js = async expression => {
  const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result?.value;
};
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const wait = async (expression, label) => {
  for (let i = 0; i < 100; i++) { if (await js(expression)) return; await pause(50); }
  throw Error(`${label}\n${await js('document.body.innerText')}`);
};
try {
  await send('Runtime.enable');
  await send('Page.navigate', { url: base });
  await wait('document.readyState === "complete"', 'static page');
  await js(`(async () => {
    const { h, render } = await import('/vendor/preact-htm.module.js');
    const { ImuPage } = await import('/imu.js');
    document.body.innerHTML = '<main id="fixture"></main>';
    const root = document.querySelector('#fixture');
    window.calls = []; window.replies = [];
    window.props = { live: true, link: { status: 'open', cmd: (name, args) => {
      calls.push({name, args}); return new Promise(resolve => replies.push(resolve));
    } }, st: { mode: 'commissioning', posture: 'holding', gravity: [0, 0, -1], joints_age_ms: 5,
      imu: {status: 'ok'}, hold: {stage: 'holding', max_error_deg: 0.4} },
      imu: { source: 'bus', mode: 'commissioning', mount: {quat: [1,0,0,0], verified: true},
        imu_bus: {protocol: 'feetech', board: 'ft6', identity: [1,2,3]}, redo: {} } };
    window.draw = () => render(h(ImuPage, props), root);
    window.clickText = text => {
      const button = [...root.querySelectorAll('button')].find(b => b.textContent.trim() === text);
      if (!button || button.disabled) throw Error('Missing enabled button: ' + text);
      button.click();
    };
    draw();
  })()`);
  await wait('document.querySelector(".imu-page")', 'IMU page');
  assert.match(await js('document.querySelector(".imu-side").innerText'), /FT6.*Feetech/);
  assert.doesNotMatch(await js('document.body.innerText'), /只认 FT6/);
  assert.match(await js('document.body.innerText'), /支持 FT6、IMU-to-DXL（Feetech）；SFLP 124\/12（Dynamixel 2\.0）/);
  for (const [protocol, board, label] of [['feetech', 'imu_to_dxl', 'IMU-to-DXL'], ['dxl2', 'sflp_124_12', 'SFLP 124/12']]) {
    for (const mode of ['motion', 'commissioning']) {
      await js(`props.st = {...props.st, mode:${JSON.stringify(mode)}};
        props.imu = {...props.imu, mode:${JSON.stringify(mode)},
        imu_bus: {protocol:${JSON.stringify(protocol)}, board:${JSON.stringify(board)}, identity:[1,2,3]},
        mount: {...props.imu.mount, verified:${protocol === 'feetech'}}, mount_protocol_mismatch:${protocol === 'dxl2'}}; draw()`);
      const protocolLabel = protocol === 'feetech' ? 'Feetech' : 'Dynamixel 2.0';
      await wait(`document.querySelector('.sv-metrics').innerText.includes(${JSON.stringify(`${label} · ${protocolLabel}`)})`, `${mode} board label ${board}`);
    }
    const text = await js('document.body.innerText');
    if (protocol === 'dxl2') {
      assert.match(text, /重新标定/);
      assert.doesNotMatch(await js('document.querySelector(".sv-metrics").innerText'), /方向已确认/);
      assert.match(text, /不提供.*序号.*状态.*年龄/);
      assert.match(text, /主机.*新鲜度.*原始字节/);
    } else {
      assert.match(await js('document.querySelector(".sv-metrics").innerText'), /方向已确认/);
      assert.doesNotMatch(text, /不提供采样序号/);
    }
  }
  // A delayed capture belongs to the original board and must not advance its replacement.
  await js(`clickText('采静止（3 秒）')`);
  await wait('calls.length === 1', 'coarse capture request');
  await js(`props.imu = {...props.imu, imu_bus: {...props.imu.imu_bus, identity:[9,9,9]}}; draw()`);
  await pause(120);
  await js(`replies.shift()({ok:true, data:{n:30, samples:[{step:'still',g:[0,0,-1]}]}})`);
  await pause(120);
  assert.equal(await js(`[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='采前倾（3 秒）')`), false);
  assert.equal(await js(`[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='采静止（3 秒）'&&!b.disabled)`), true);
  // Standing collection also resets when only transport identity changes.
  await js(`props.st = {...props.st, mode:'motion', hold:null}; props.imu = {...props.imu, mode:'motion',
    mount:{quat:[1,0,0,0],verified:true}, mount_protocol_mismatch:false}; draw()`);
  await pause(120);
  await js(`clickText('开始采集')`);
  await wait('document.querySelector(".imu-big.rec")', 'standing collection started');
  await js(`props.imu = {...props.imu, imu_bus:{...props.imu.imu_bus, identity:[8,8,8]}}; draw()`);
  await wait('!document.querySelector(".imu-big.rec")', 'standing collection reset');
  assert.equal(await js(`document.querySelector('.imu-big').textContent.trim()`), '开始采集');
  await js(`props.imu = {...props.imu, source:'lsm6dsv16x', imu_bus:null}; draw()`);
  await wait('document.querySelector(".sv-metrics").innerText.includes("LSM6DSV16X（I²C）")', 'I2C label');
  assert.deepEqual(errors, []);
  process.stdout.write('IMU bus browser assertions passed\n');
} finally {
  await send('Page.close').catch(() => {});
  ws.close();
}
