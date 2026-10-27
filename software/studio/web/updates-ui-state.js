export const PHASES={queued:'等待任务启动',uploading:'上传中',checking:'检查发布源',downloading:'下载中',downloaded:'已下载',
  preflight:'检查停稳与供电',verifying:'验证签名与软件包',extracting:'验证运行文件',swapping:'切换版本',
  applying:'启动匹配的网页和语音服务',health_gate:'检查网页与本地语音',committing:'记录安装结果',
  rolling_back:'正在恢复上一版',completed:'任务完成',failed:'任务失败',interrupted:'任务曾中断，需核对结果',
  waiting_validation:'已下载，待停稳验证',rolled_back:'更新失败，已恢复旧版'};
export function updateMessage(data){
  if(!data?.available)return '软件更新服务尚未安装或暂时不可用';
  const job=data.job;
  if(job?.phase==='rolled_back')return '更新失败，已恢复旧版。'+(job.error||'');
  if(job?.phase==='waiting_validation')return '已下载，待停稳验证。'+(job.error||'');
  if(job?.phase==='failed'||job?.phase==='interrupted')return (PHASES[job.phase]||'任务未完成')+'：'+(job.error||'请重试');
  if(data.busy)return PHASES[job?.phase]||'更新任务进行中';
  if(data.ready)return '签名和运行文件已由升级引擎验证，可安装。';
  if(data.source_state==='no_release')return '尚无发布的软件更新。';
  if(data.source_state==='network_error')return '网络检查失败，请稍后重试；尚未确认是否有更新。';
  if(data.source_state==='up_to_date')return '当前已是发布源中的最新软件版本。';
  if(data.source_state==='available')return '发现软件更新，下载后由升级引擎验证。';
  return job?.phase==='completed'?'任务完成。':'手动检查软件更新，或上传离线软件包。';
}
export function updateActions(data,pending=false){
  const idle=!!data?.available&&!data.busy&&!pending;
  return {check:idle,upload:idle,download:idle&&!!data.candidate&&data.source_state==='available',
    validate:idle&&!!data.staged,install:idle&&data.ready===true,rollback:idle&&data.can_rollback===true};
}
