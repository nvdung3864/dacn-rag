import {useEffect,useState} from 'react';
import {Search,MessageSquare,ChevronLeft,ChevronRight,ArrowUpRight,Trash2,Loader2,X,Check} from 'lucide-react';
import {request} from './api';

type HistoryItem={id:string;question:string;answer_preview:string;created_at:string;updated_at:string;message_count:number;no_answer:boolean;needs_clarification:boolean};
type HistoryPage={items:HistoryItem[];total:number;page:number;page_size:number};

const dateLabel=(value:string)=>new Date(value).toLocaleString('vi-VN',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});

export default function HistoryPanel({onOpen,onChanged,onDeleted,disabled}:{onOpen:(id:string)=>Promise<void>;onChanged:()=>Promise<void>;onDeleted?:(id:string)=>void;disabled:boolean}){
 const [search,setSearch]=useState(''),[query,setQuery]=useState(''),[page,setPage]=useState(1),[tick,setTick]=useState(0);
 const [data,setData]=useState<HistoryPage>({items:[],total:0,page:1,page_size:10}),[loading,setLoading]=useState(true),[error,setError]=useState(''),[deleting,setDeleting]=useState<string|null>(null),[pending,setPending]=useState<string|null>(null);
 useEffect(()=>{const timer=setTimeout(()=>{setQuery(search.trim());setPage(1);},250);return()=>clearTimeout(timer);},[search]);
 useEffect(()=>{
  const controller=new AbortController();setLoading(true);setError('');
  const params=new URLSearchParams({q:query,page:String(page),page_size:'10'});
  request<HistoryPage>('/conversations/search?'+params,{signal:controller.signal}).then(result=>{
   if(controller.signal.aborted)return;
   const last=Math.max(1,Math.ceil(result.total/result.page_size));
   if(page>last){setPage(last);return;}
   setData(result);
  }).catch(e=>{if(!controller.signal.aborted)setError((e as Error).message);}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
  return()=>controller.abort();
 },[query,page,tick]);
 async function remove(id:string){
  setPending(id);setError('');
  try{await request('/conversations/'+id,{method:'DELETE'});onDeleted?.(id);setDeleting(null);setTick(value=>value+1);await onChanged();}
  catch(e){setError((e as Error).message);}
  finally{setPending(null);}
 }
 const totalPages=Math.max(1,Math.ceil(data.total/data.page_size));
 const searching=search.trim()!==query;
 return <section className="table-panel history-panel" aria-label="Lịch sử trò chuyện">
  <div className="table-toolbar history-toolbar"><span className="history-count">{data.total} cuộc trò chuyện</span><div className="search history-search"><Search size={17}/><input autoFocus aria-label="Tìm lịch sử trò chuyện" placeholder="Tìm câu hỏi hoặc câu trả lời…" value={search} onChange={e=>setSearch(e.target.value)}/>{search&&<button className="icon-btn" aria-label="Xóa từ khóa" onClick={()=>setSearch('')}><X size={15}/></button>}</div></div>
  {error&&<p className="history-error" role="alert">{error}</p>}
  {loading||searching?<div className="history-empty" role="status"><Loader2 size={22} className="spin"/><p>Đang tải lịch sử…</p></div>:data.items.length?<>
   <div className="table-scroll"><table className="history-table"><thead><tr><th>Cuộc trò chuyện</th><th>Trạng thái</th><th>Thời gian</th><th><span className="sr-only">Thao tác</span></th></tr></thead><tbody>{data.items.map(item=><tr key={item.id}>
    <td><button className="history-open" disabled={disabled||!!pending} onClick={()=>onOpen(item.id)}><MessageSquare size={18}/><span><strong>{item.question}</strong><small>{item.message_count} lượt hỏi · {item.answer_preview}</small></span></button></td>
    <td><span className={'status '+(item.no_answer?'pending':'succeeded')}><span/>{item.needs_clarification?'Cần làm rõ':item.no_answer?'Chưa đủ thông tin':'Đã trả lời'}</span></td>
    <td><time dateTime={item.updated_at}>{dateLabel(item.updated_at)}</time></td>
    <td>{deleting===item.id?<div className="history-delete"><button className="icon-btn danger" title="Xác nhận xóa" aria-label="Xác nhận xóa cuộc trò chuyện" disabled={!!pending} onClick={()=>remove(item.id)}>{pending===item.id?<Loader2 size={16} className="spin"/>:<Check size={16}/>}</button><button className="icon-btn" title="Hủy" aria-label="Hủy xóa" disabled={!!pending} onClick={()=>setDeleting(null)}><X size={16}/></button></div>:<div className="history-actions"><button className="icon-btn" title="Mở cuộc trò chuyện" aria-label={'Mở '+item.question} disabled={disabled||!!pending} onClick={()=>onOpen(item.id)}><ArrowUpRight size={18}/></button><button className="icon-btn danger" title="Xóa cuộc trò chuyện" aria-label={'Xóa '+item.question} disabled={disabled||!!pending} onClick={()=>setDeleting(item.id)}><Trash2 size={16}/></button></div>}</td>
   </tr>)}</tbody></table></div>
   <div className="history-pagination"><span>{(page-1)*data.page_size+1}–{Math.min(page*data.page_size,data.total)} / {data.total}</span><div><button className="btn" disabled={page===1} aria-label="Trang trước" onClick={()=>{setDeleting(null);setPage(value=>value-1);}}><ChevronLeft size={16}/></button><span>Trang {page} / {totalPages}</span><button className="btn" disabled={page>=totalPages} aria-label="Trang sau" onClick={()=>{setDeleting(null);setPage(value=>value+1);}}><ChevronRight size={16}/></button></div></div>
  </>:<div className="history-empty"><MessageSquare size={28}/><h3>{query?'Không tìm thấy cuộc trò chuyện':'Chưa có cuộc trò chuyện'}</h3></div>}
 </section>;
}
