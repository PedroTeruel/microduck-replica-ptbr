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
  assert.doesNotMatch(await js('document.body.innerText'), /Somente FT6/);
  assert.match(await js('document.body.innerText'), /reconhece FT6 e IMU-to-DXL \(Feetech\), além de SFLP 124\/12 \(Dynamixel 2\.0\)/);
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
      assert.match(text, /Recalibre a orientação/);
      assert.doesNotMatch(await js('document.querySelector(".sv-metrics").innerText'), /Orientação confirmada/);
      assert.match(text, /não fornece.*número de amostra.*bits de estado.*idade/);
      assert.match(text, /programa principal verifica.*atualidade.*bytes brutos/);
    } else {
      assert.match(await js('document.querySelector(".sv-metrics").innerText'), /Orientação confirmada/);
      assert.doesNotMatch(text, /não fornece número de amostra/);
    }
  }
  // A delayed capture belongs to the original board and must not advance its replacement.
  await js(`clickText('Coletar repouso (3 s)')`);
  await wait('calls.length === 1', 'coarse capture request');
  await js(`props.imu = {...props.imu, imu_bus: {...props.imu.imu_bus, identity:[9,9,9]}}; draw()`);
  await pause(120);
  await js(`replies.shift()({ok:true, data:{n:30, samples:[{step:'still',g:[0,0,-1]}]}})`);
  await pause(120);
  assert.equal(await js(`[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Coletar inclinação frontal (3 s)')`), false);
  assert.equal(await js(`[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Coletar repouso (3 s)'&&!b.disabled)`), true);
  // Standing collection also resets when only transport identity changes.
  await js(`props.st = {...props.st, mode:'motion', hold:null}; props.imu = {...props.imu, mode:'motion',
    mount:{quat:[1,0,0,0],verified:true}, mount_protocol_mismatch:false}; draw()`);
  await pause(120);
  await js(`clickText('Iniciar coleta')`);
  await wait('document.querySelector(".imu-big.rec")', 'standing collection started');
  await js(`props.imu = {...props.imu, imu_bus:{...props.imu.imu_bus, identity:[8,8,8]}}; draw()`);
  await wait('!document.querySelector(".imu-big.rec")', 'standing collection reset');
  assert.equal(await js(`document.querySelector('.imu-big').textContent.trim()`), 'Iniciar coleta');
  // A conflicting secondary diagnostic leaves the chosen board unchanged, but
  // its validity transition must discard collection and stay discarded on recovery.
  await js(`clickText('Iniciar coleta')`);
  await wait('document.querySelector(".imu-big.rec")', 'collection before diagnostic conflict');
  await js(`props.imu={...props.imu,metadata_error:'O programa principal informou um tipo de IMU incompatível',
    profile_error:'O programa principal informou um tipo de IMU incompatível',mount:{...props.imu.mount,verified:false}}; draw()`);
  await wait('!document.querySelector(".imu-big.rec")', 'conflicting metadata resets collection');
  await js(`props.imu={...props.imu,metadata_error:null,profile_error:null,
    mount:{...props.imu.mount,verified:true}}; draw()`);
  await pause(120);
  assert.equal(await js(`!!document.querySelector('.imu-big.rec')`),false);
  assert.equal(await js(`document.querySelector('.imu-big').textContent.trim()`),'Iniciar coleta');
  // Same wire and identity, different explicitly configured data profile.
  await js(`props.imu = {...props.imu, configured_imu_profile:'qinmo', profile_selection:{can_start:true},
    imu_bus:{protocol:'feetech',board:'qinmo',identity:[],profile:'qinmo',gyro_dps_per_lsb:1/16.4,identification:'configured_profile'}}; draw()`);
  await wait('document.querySelector(".imu-side").innerText.includes("Qinmo")', 'Qinmo label');
  await pause(120); // let the configured-profile state synchronize before user input
  assert.match(await js('document.body.innerText'), /Tipo configurado.*Qinmo|Qinmo.*configurado/);
  assert.match(await js('document.body.innerText'), /16\.4/);
  assert.match(await js('document.body.innerText'), /identidade exclusiva do Qinmo/);
  assert.match(await js('document.body.innerText'), /Tipo de IMU do barramento/);
  assert.match(await js('document.body.innerText'), /Conexão real/);
  await js(`const select=document.querySelector('select[aria-label="Tipo de IMU do barramento"]'); select.value='legacy'; select.dispatchEvent(new Event('change',{bubbles:true}));`);
  await pause(100);
  await js(`clickText('Salvar tipo e reconectar')`);
  await pause(750);
  await js(`clickText('O robô está seguro. Confirmar reconexão e recalibração?')`);
  await wait('calls.some(c=>c.args.op==="profile-select")', 'profile selection command');
  assert.deepEqual(await js(`calls.find(c=>c.args.op==='profile-select').args`), {op:'profile-select',profile:'legacy',confirmed:true});
  await js(`replies.shift()({ok:true,data:{}})`);
  await pause(100);
  // Failed discovery still leaves the selector available through configured diagnostics.
  await js(`props.imu={...props.imu,imu_bus:null}; draw()`);
  await wait(`document.body.innerText.includes('Ainda não conectada')`, 'configured versus effective missing');
  await js(`props.imu={...props.imu, configured_imu_profile:null,profile_selection:{can_start:false,reason:'O programa principal ainda não permite selecionar o tipo pela interface web'}}; draw()`);
  await wait(`document.body.innerText.includes('O programa principal ainda não permite selecionar o tipo pela interface web')`, 'old daemon fallback');
  await js(`props.imu={...props.imu,imu_bus:{protocol:'feetech',board:'ft6',identity:[1],profile:'future'},
    profile_error:'O programa principal informou um tipo de IMU não compatível',mount:{quat:[1,0,0,0],verified:false}}; draw()`);
  await wait(`document.querySelector('.imu-side').innerText.includes('Protocolo ou tipo da IMU não confirmado')`, 'unknown profile stays visible and unsafe');
  assert.match(await js(`document.querySelector('.imu-side').innerText`), /tipo da IMU não confirmado/);
  assert.doesNotMatch(await js(`document.querySelector('.imu-side').innerText`), /Valor bruto × 0\.0175|Orientação confirmada/);
  for (const raw of [
    {imu_bus:{protocol:'future',profile:'legacy'},configured_imu_profile:'legacy'},
    {imu_bus:{protocol:'feetech',profile:'legacy'},configured_imu_profile:'future'},
    {imu_bus:null,configured_imu_profile:null},
  ]) {
    await js(`props.imu={...props.imu,...${JSON.stringify(raw)},profile_selection:{can_start:true},
      metadata_error:'O programa principal informou um protocolo ou tipo de IMU não compatível',profile_error:'O programa principal informou um protocolo ou tipo de IMU não compatível'}; draw()`);
    await pause(100);
    assert.match(await js(`document.querySelector('.imu-side').innerText`), /Não confirmado/);
    assert.doesNotMatch(await js(`document.querySelector('.imu-side .imu-kv').innerText`), /Valor bruto × 0\.0175|Valor bruto ÷ 16,4/);
    assert.equal(await js(`[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Salvar tipo e reconectar').disabled`), true);
  }
  await js(`props.imu = {...props.imu, source:'lsm6dsv16x', imu_bus:null}; draw()`);
  await wait('document.querySelector(".sv-metrics").innerText.includes("LSM6DSV16X (I²C)")', 'I2C label');
  // Exercise the actual global Space handler used beside the IMU page. Keep its
  // real component source, with only the link transport supplied by this fixture.
  await js(`(async()=>{
    const source=await (await fetch('/app.js')).text();
    const component=source.slice(source.indexOf('const TEXT_TYPES'),source.indexOf('function TopBar'));
    const {html,h,render,useState,useEffect,useCallback}=await import('/vendor/preact-htm.module.js');
    const EStop=Function('html','useState','useEffect','useCallback','link',component+';return EStop;')(
      html,useState,useEffect,useCallback,props.link);
    const root=document.createElement('aside');document.body.append(root);
    render(h(EStop,{st:{mode:'commissioning'},live:true,open:true}),root);
  })()`);
  await pause(120);
  await js(`window.dispatchEvent(new KeyboardEvent('keydown',{code:'Space',key:' ',bubbles:true}));`);
  await wait(`calls.some(c=>c.name==='relax')`, 'Space emergency relax retained');
  assert.deepEqual(await js(`calls.find(c=>c.name==='relax').args`), {});
  await js(`replies.shift()({ok:true,data:{}})`);
  assert.deepEqual(errors, []);
  process.stdout.write('IMU bus browser assertions passed\n');
} finally {
  await send('Page.close').catch(() => {});
  ws.close();
}
