// Live acceptance against an isolated, owned demo service. No API mocking or GPU jobs.
// npm install --no-save playwright, or set PLAYWRIGHT_MODULE_ROOT to an existing node_modules.
import assert from 'node:assert/strict';
import {spawn,spawnSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {mkdtemp,mkdir,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve,join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {randomUUID} from 'node:crypto';

const root=fileURLToPath(new URL('../',import.meta.url));
const require=createRequire(process.env.PLAYWRIGHT_MODULE_ROOT?join(resolve(process.env.PLAYWRIGHT_MODULE_ROOT),'entry.cjs'):import.meta.url);
const {chromium}=require('playwright');
const python=process.env.PYTHON||'python';
const out=process.env.BROWSER_CHECK_OUTPUT?resolve(process.env.BROWSER_CHECK_OUTPUT):await mkdtemp(join(tmpdir(),'microduck-ui-'));
await mkdir(out,{recursive:true});
const stateDir=await mkdtemp(join(tmpdir(),'microduck-ui-state-'));
const token=randomUUID();
const server=spawn(python,['run.py','--demo','--port','0','--state-dir',stateDir,'--token',token],{cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe']});
let base='',browser,serverLog='';
server.stdout.on('data',b=>{serverLog+=b.toString();base=serverLog.match(/http:\/\/127\.0\.0\.1:\d+/)?.[0]||base;});
server.stderr.on('data',b=>{serverLog+=b.toString();});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function until(check,label,timeout=18000){const start=Date.now();while(Date.now()-start<timeout){const result=await check();if(result)return result;await sleep(120);}throw new Error('Timed out: '+label);}
async function api(path,body){const r=await fetch(base+path,{method:body===undefined?'GET':'POST',headers:{'X-Studio-Token':token,'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});const data=await r.json();assert.ok(r.ok,JSON.stringify(data));return data;}
const records=[];
try{
  await until(()=>base,'demo server starts');
  browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{}),args:['--no-proxy-server']});
  const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
  const page=await context.newPage(),pageErrors=[];
  page.on('pageerror',e=>pageErrors.push(e.message));
  const failures=[];
  page.on('response',r=>{if(r.status()>=400&&r.status()!==401)failures.push(`${r.status()} ${r.url()}`);});
  page.on('dialog',d=>d.accept());
  await page.goto(base);
  await page.getByLabel('Token de acesso',{exact:true}).fill(token);
  await page.getByRole('button',{name:'Conectar ao Training Studio',exact:true}).click();
  await page.getByRole('heading',{name:'Painel de treinamento',exact:true}).waitFor();
  await page.getByRole('button',{name:'Reproduzir demonstração do movimento',exact:true}).waitFor();
  await until(()=>page.getByRole('button',{name:'Reproduzir demonstração do movimento',exact:true}).isEnabled(),'CAD assets loaded');
  await page.screenshot({path:join(out,'01-workspace-desktop.png'),fullPage:true,animations:'disabled'});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  records.push('token authentication, CAD load and desktop layout');

  // New user flow: smoke first, then formal run with visible custom values.
  await page.getByRole('button',{name:'Novo treinamento',exact:true}).click();
  await page.getByLabel('Nome do experimento',{exact:true}).fill('Verificação do navegador · teste rápido');
  assert.equal(await page.locator('input[name="kind"][value="train"]').isDisabled(),true);
  await page.getByRole('button',{name:'Configurações avançadas'}).click();
  await page.screenshot({path:join(out,'02-new-experiment.png'),fullPage:true,animations:'disabled'});
  await page.getByRole('button',{name:'Iniciar teste curto',exact:true}).click();
  const smoke=await until(async()=>{const s=await api('/api/state');return s.runs.find(r=>r.name==='Verificação do navegador · teste rápido'&&r.status==='completed');},'smoke finishes');
  assert.equal(smoke.config.num_envs,64);assert.equal(smoke.config.iterations,5);
  await page.getByRole('button',{name:'Iniciar treinamento completo →',exact:true}).waitFor();
  await page.getByRole('button',{name:'Iniciar treinamento completo →',exact:true}).click();
  await page.getByLabel('Nome do experimento',{exact:true}).fill('Passada em terreno plano · Treinamento A');
  await page.getByRole('button',{name:'Configurações avançadas'}).click();
  await page.locator('input[name="iterations"]').fill('80');
  await page.locator('input[name="save_interval"]').fill('5');
  await page.getByRole('button',{name:'Configurações avançadas'}).click();
  assert.match(await page.locator('.change-summary').innerText(),/80/);
  assert.equal(await page.locator('input[name="iterations"]').count(),0);
  await page.getByRole('button',{name:'Iniciar treinamento',exact:true}).click();
  const running=await until(async()=>{const s=await api('/api/state');return s.runs.find(r=>r.name==='Passada em terreno plano · Treinamento A'&&r.checkpoints.length>=2);},'two formal checkpoints');
  await page.getByRole('button',{name:'Pausar treinamento',exact:true}).click();
  await page.getByRole('button',{name:'Retomar treinamento',exact:true}).waitFor();
  const paused=await api('/api/runs/'+running.id);
  assert.equal(paused.status,'paused');await sleep(1100);
  assert.equal((await api('/api/runs/'+running.id)).progress.iteration,paused.progress.iteration);
  await page.screenshot({path:join(out,'03-training-paused.png'),fullPage:true,animations:'disabled'});
  await page.reload();await page.getByRole('button',{name:'Retomar treinamento',exact:true}).click();
  await until(async()=>(await api('/api/runs/'+running.id)).progress.iteration>paused.progress.iteration,'resumed iterations');
  await page.getByRole('button',{name:'Parar tarefa',exact:true}).click();
  await until(async()=>(await api('/api/runs/'+running.id)).status==='stopped','stop');
  await page.getByRole('button',{name:'Continuar treinamento a partir do checkpoint',exact:true}).waitFor();
  records.push('smoke gate, collapsed advanced edits, pause stability, refresh, resume and stop');

  // Select an older checkpoint, evaluate/export precisely that checkpoint.
  await page.locator('.checkpoint').first().click();
  const selectedName=await page.locator('.checkpoint.chosen b').innerText();
  await page.getByRole('button',{name:'Reprodução da avaliação',exact:true}).last().click();
  await until(async()=>(await api('/api/runs/'+running.id)).operation?.status==='completed','evaluate');
  await page.locator('.artifact-image').waitFor();
  assert.match(await page.locator('.stage-label').innerText(),/Reprodução de demonstração/);
  await page.getByRole('button',{name:'Exportar registro de demonstração',exact:true}).click();
  await page.getByRole('button',{name:'Baixar registro',exact:true}).waitFor();
  const downloadWait=page.waitForEvent('download');
  await page.getByRole('button',{name:'Baixar registro',exact:true}).click();
  const download=await downloadWait,zipPath=join(out,'demo-records.zip');await download.saveAs(zipPath);
  const inspect=spawnSync(python,['-c','import sys,zipfile,json; z=zipfile.ZipFile(sys.argv[1]); print(json.dumps(z.namelist()))',zipPath],{encoding:'utf8',windowsHide:true});
  assert.equal(inspect.status,0,inspect.stderr);const names=JSON.parse(inspect.stdout);assert.ok(names.includes('provenance.json'));assert.ok(!names.some(n=>/\.(onnx|pt)$/i.test(n)));assert.ok(names.some(n=>n.includes('evaluation')&&n.endsWith('.svg')));
  await page.screenshot({path:join(out,'04-checkpoint-replay.png'),fullPage:true,animations:'disabled'});
  await page.getByRole('button',{name:'Continuar treinamento a partir do checkpoint',exact:true}).click();
  const continued=await until(async()=>{const s=await api('/api/state');return s.runs.find(r=>r.parent_id===running.id&&r.status==='running');},'new continuation run');
  assert.equal(continued.resume_checkpoint_id,(await api('/api/runs/'+running.id)).checkpoints[0].id);
  await page.getByRole('button',{name:'Parar tarefa',exact:true}).click();
  await until(async()=>(await api('/api/runs/'+continued.id)).status==='stopped','continued stop');
  records.push(`selected checkpoint ${selectedName}, authenticated replay/download, honest ZIP and continuation identity`);

  // Compare and small-screen layouts.
  await page.getByRole('button',{name:'Comparar experimentos',exact:true}).click();
  await page.getByRole('dialog',{name:'O que mudou desta vez?'}).waitFor();
  await page.locator('.diff-table').waitFor();
  await page.screenshot({path:join(out,'05-experiment-comparison.png'),fullPage:true,animations:'disabled'});
  await page.getByRole('button',{name:'Fechar comparação de experimentos'}).click();
  await page.getByRole('button',{name:'Meus experimentos',exact:false}).click();
  await page.getByPlaceholder('Buscar nome do experimento').fill('Passada em terreno plano');
  assert.ok(await page.locator('.run-table tbody tr').count()>=1);
  await page.getByRole('button',{name:'Modelos e resultados',exact:true}).click();
  await page.locator('.model-card').first().waitFor();
  await page.getByRole('button',{name:'Ambiente computacional',exact:true}).click();
  await page.getByRole('button',{name:'Verificar novamente',exact:true}).click();
  await page.getByText('Verificação do ambiente atualizada',{exact:true}).waitFor();
  await page.goto(base+'/#/runs/'+running.id);
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('heading',{name:'Passada em terreno plano · Treinamento A',exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:join(out,'06-training-mobile.png'),fullPage:true,animations:'disabled'});
  await page.getByRole('navigation',{name:'Navegação móvel'}).waitFor();
  await page.getByRole('button',{name:'Painel de treinamento',exact:true}).click();
  await page.getByRole('button',{name:'Novo treinamento',exact:true}).click();
  await page.getByRole('dialog',{name:'Iniciar um novo treinamento'}).waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:join(out,'07-new-experiment-mobile.png'),fullPage:false,animations:'disabled'});
  await page.getByRole('button',{name:'Fechar novo treinamento'}).click();
  records.push('comparison, experiment search, models, environment refresh, mobile bottom navigation, run and drawer');
  await page.setViewportSize({width:1440,height:1000});
  await page.getByRole('button',{name:'Novo treinamento',exact:true}).click();
  await page.getByLabel('Nome do experimento',{exact:true}).fill('Alteração de parâmetros · novo teste rápido');
  await page.locator('input[name="kind"][value="train"]').check();
  await page.getByRole('button',{name:'Configurações avançadas'}).click();
  await page.locator('input[name="iterations"]').fill('120');
  await page.locator('input[name="seed"]').fill('43');
  await page.getByRole('button',{name:'Iniciar teste curto',exact:true}).click();
  const revised=await until(async()=>{const s=await api('/api/state');return s.runs.find(r=>r.name==='Alteração de parâmetros · novo teste rápido'&&r.status==='completed');},'changed configuration short check');
  assert.equal(revised.kind,'smoke');assert.equal(revised.config.seed,43);assert.equal(revised.config.iterations,5);
  await page.getByRole('button',{name:'Iniciar treinamento completo →',exact:true}).click();
  await page.getByRole('button',{name:'Configurações avançadas'}).click();
  assert.equal(await page.locator('input[name="iterations"]').inputValue(),'120');
  assert.equal(await page.locator('input[name="seed"]').inputValue(),'43');
  await page.getByRole('button',{name:'Fechar novo treinamento'}).click();
  records.push('changed learning configuration forces re-smoke while preserving formal drafts');
  assert.deepEqual(pageErrors,[]);assert.deepEqual(failures,[]);
  await writeFile(join(out,'result.json'),JSON.stringify({ok:true,checks:records,pageErrors,failures,stateDir},null,2));
  console.log(JSON.stringify({ok:true,checks:records,screenshots:out,stateDir},null,2));
}catch(error){
  await writeFile(join(out,'failure.txt'),String(error.stack||error));throw error;
}finally{
  if(base){try{const s=await api('/api/state');const r=s.runs.find(r=>r.id===s.active_run_id);if(r&&['starting','running','paused'].includes(r.status)){await api('/api/runs/'+r.id+'/stop',{});await until(async()=>!(await api('/api/state')).active_run_id,'cleanup stop',8000);}}catch{}}
  await browser?.close();server.kill();
}
