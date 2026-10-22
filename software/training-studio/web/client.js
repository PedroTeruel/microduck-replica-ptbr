export function token() { return sessionStorage.getItem('microduck-training-token')||''; }
export async function request(path, {method='GET',body,blob=false,signal}={}) {
  const headers={'Accept':blob?'*/*':'application/json'};
  if(token()) headers['X-Studio-Token']=token();
  if(body!==undefined) headers['Content-Type']='application/json';
  const response=await fetch(path,{method,headers,body:body===undefined?undefined:JSON.stringify(body),signal,cache:'no-store'});
  if(!response.ok) {
    let info;try{info=await response.json();}catch{info={error:`请求失败（${response.status}）`};}
    const error=new Error(info.detail?`${info.error}：${typeof info.detail==='string'?info.detail:JSON.stringify(info.detail)}`:info.error||'请求失败');error.status=response.status;throw error;
  }
  return blob?response.blob():response.json();
}
export async function download(path, name) {
  const data=await request(path,{blob:true});const url=URL.createObjectURL(data);
  const a=document.createElement('a');a.href=url;a.download=name||path.split('/').pop();a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
}
