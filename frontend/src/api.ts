export type Row = Record<string, any>;
export type User = {id:string; name:string; email:string; role:'admin'|'user'; active:boolean};
export type Citation = {chunk_id:string;document_id:string;source_id:string;title:string;source_name:string;location:string;format:string;page:number|null;section:string|null;text:string;marker?:string;score?:number;version:number;last_synced_at:string|null;indexed_at?:string|null;freshness_days?:number};
export type Answer = {conversation_id?:string;resolved_question?:string;answer:string;citations:Citation[];retrieved_chunks:Citation[];no_answer:boolean;missing_information?:string[];needs_clarification?:boolean;answer_revision?:string;normalized_question?:string;query_id?:string;feedback?:{rating:number;comment:string}|null;retrieval_cache_hit?:boolean;latency_ms:{total_ms:number;retrieval_ms:number;embedding_ms:number;generation_ms:number};token_usage:Row;top_k:number;config_version:string};
function expireSession(){
  if(!sessionStorage.getItem('bk-token'))return;
  sessionStorage.removeItem('bk-token');
  window.dispatchEvent(new Event('bk-session-expired'));
}
export async function request<T>(path:string,options:RequestInit={}):Promise<T> {
  const headers=new Headers(options.headers);
  const token=sessionStorage.getItem('bk-token');
  if(token)headers.set('Authorization','Bearer '+token);
  if(options.body && !(options.body instanceof FormData)) headers.set('Content-Type','application/json');
  let response:Response;
  try{response=await fetch('/api'+path,{...options,headers});}
  catch(error){if(error instanceof DOMException&&error.name==='AbortError')throw error;throw new Error('Không thể kết nối máy chủ.');}
  if(response.status===204)return undefined as T;
  if(response.status===401)expireSession();
  if(token&&sessionStorage.getItem('bk-token')!==token)throw new Error('Phiên đăng nhập đã thay đổi.');
  let data:Row;
  try{data=await response.json();}catch{throw new Error('Máy chủ phản hồi không hợp lệ.');}
  if(!response.ok){
    const detail=typeof data.detail==='string'?data.detail: Array.isArray(data.detail)? data.detail.map((d:Row)=>d.msg).join('; '):'Yêu cầu thất bại.';
    throw new Error(detail);
  }
  return data as T;
}
export const post = <T,>(path:string,body:unknown) => request<T>(path,{method:'POST',body:JSON.stringify(body)});

export async function streamAnswer(body:unknown,onEvent:(kind:string,data:Row)=>void,signal:AbortSignal):Promise<Answer>{
  const token=sessionStorage.getItem('bk-token');
  const response=await fetch('/api/query/stream',{method:'POST',signal,headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},body:JSON.stringify(body)});
  if(response.status===401)expireSession();
  if(!response.ok){const data=await response.json();throw Error(typeof data.detail==='string'?data.detail:'Không thể bắt đầu câu trả lời.');}
  if(!response.body||!response.headers.get('content-type')?.includes('text/event-stream'))throw Error('Máy chủ không trả luồng câu trả lời hợp lệ.');
  const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',result:Answer|undefined;
  try{
    while(true){
      const {done,value}=await reader.read();buffer=(buffer+decoder.decode(value,{stream:!done})).replace(/\r\n/g,'\n');
      if(buffer.length>2_000_000)throw Error('Luồng phản hồi vượt giới hạn.');
      let boundary:number;
      while((boundary=buffer.indexOf('\n\n'))>=0){
        const block=buffer.slice(0,boundary);buffer=buffer.slice(boundary+2);
        const kind=block.split('\n').find(line=>line.startsWith('event:'))?.slice(6).trim();
        const raw=block.split('\n').filter(line=>line.startsWith('data:')).map(line=>line.slice(5).trimStart()).join('\n');
        if(!kind||!raw)continue;
        if(token!==sessionStorage.getItem('bk-token'))throw Error('Phiên đăng nhập đã thay đổi.');
        const data=JSON.parse(raw);
        if(kind==='error'){if(data.status===401)expireSession();throw Error(data.detail||'Không thể hoàn tất câu trả lời.');}
        if(kind==='result')result=data as Answer;
        else if(kind!=='status'&&kind!=='draft')throw Error('Sự kiện phản hồi không hợp lệ.');
        onEvent(kind,data);
      }
      if(result)return result;
      if(done)break;
    }
    throw Error('Kết nối kết thúc trước khi có câu trả lời đã kiểm chứng.');
  }finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
}
export async function downloadDocument(id:string,name:string){
  const r=await fetch('/api/documents/'+id+'/download',{headers:{Authorization:'Bearer '+sessionStorage.getItem('bk-token')}});
  if(r.status===401)expireSession();
  if(!r.ok)throw new Error('Không tải được file gốc. Kiểm tra quyền truy cập.');
  const url=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=url;a.download=name;a.click();URL.revokeObjectURL(url);
}
