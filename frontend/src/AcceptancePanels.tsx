import {useEffect,useState} from 'react';
import {ThumbsUp,ThumbsDown,RefreshCw} from 'lucide-react';
import {request,type Answer,type Citation,type Row} from './api';

export function FreshnessNote({sources}:{sources:Citation[]}){
 const web=[...new Map(sources.filter(s=>s.format==='WEB').map(s=>[s.source_id,s])).values()];
 if(!web.length)return null;
 const missing=web.some(s=>!s.last_synced_at);
 const stale=web.filter(s=>s.last_synced_at&&(Date.now()-Date.parse(s.last_synced_at))/86400000>(s.freshness_days||30));
 const dates=web.map(s=>s.last_synced_at).filter(Boolean) as string[];
 const oldest=dates.sort()[0];
 return <p className={'freshness-note '+(missing||stale.length?'freshness-warning':'')} role={missing||stale.length?'status':undefined}>
  {missing?'Một số nguồn chưa có thời điểm đồng bộ. ':oldest?'Nguồn được đồng bộ: '+new Date(oldest).toLocaleString('vi-VN')+'. ':''}
  {stale.length?'Nguồn đã lâu chưa đồng bộ; hãy mở bản gốc để kiểm tra thay đổi.':'Nội dung phản ánh bản dữ liệu đã lưu, không phải tra cứu trực tiếp website.'}
 </p>;
}

export function AnswerFeedback({answer}:{answer:Answer}){
 const [rating,setRating]=useState<number|null>(answer.feedback?.rating||null),[comment,setComment]=useState(answer.feedback?.comment||''),[expanded,setExpanded]=useState(false),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
 async function save(value:number){
  setBusy(true);setMessage('');
  try{await request('/history/'+answer.query_id+'/feedback',{method:'POST',body:JSON.stringify({rating:value,comment})});setRating(value);setMessage('Đã lưu phản hồi.');}
  catch(error){setMessage((error as Error).message);}
  finally{setBusy(false);}
 }
 if(!answer.query_id)return null;
 return <div className="feedback-panel"><div className="feedback-actions"><span>Câu trả lời có hữu ích?</span>
  <button className={'btn '+(rating===1?'feedback-selected':'')} aria-pressed={rating===1} disabled={busy} onClick={()=>save(1)}><ThumbsUp size={14}/>Hữu ích</button>
  <button className={'btn '+(rating===-1?'feedback-selected':'')} aria-pressed={rating===-1} disabled={busy} onClick={()=>save(-1)}><ThumbsDown size={14}/>Chưa đúng</button>
  <button className="btn" onClick={()=>setExpanded(!expanded)}>{expanded?'Thu gọn':'Góp ý thêm'}</button></div>
  {expanded&&<form onSubmit={e=>{e.preventDefault();save(rating||-1);}}><label className="field-label">Nội dung cần điều chỉnh<textarea maxLength={1000} value={comment} onChange={e=>setComment(e.target.value)} placeholder="Ví dụ: thiếu một điều kiện hoặc dẫn nhầm nguồn…"/></label><button className="btn" disabled={busy}>Lưu góp ý</button></form>}
  {message&&<p className="feedback-message" role="status">{message}</p>}
 </div>;
}

export function DocumentLabels({document,onSave,busy}:{document:Row;onSave:(values:Row)=>Promise<void>;busy:boolean}){
 const [category,setCategory]=useState<string>(document.category||''),[tags,setTags]=useState<string>((document.tags||[]).join(', '));
 return <form className="document-labels" onSubmit={e=>{e.preventDefault();onSave({category:category.trim(),tags:tags.split(',').map(t=>t.trim()).filter(Boolean)});}}>
  <label className="field-label">Danh mục<input maxLength={80} value={category} onChange={e=>setCategory(e.target.value)} placeholder="Ví dụ: Học vụ"/></label>
  <label className="field-label">Nhãn, phân cách bằng dấu phẩy<input maxLength={800} value={tags} onChange={e=>setTags(e.target.value)} placeholder="Ngoại ngữ, Đăng ký môn học"/></label>
  <button className="btn" disabled={busy}>Lưu phân loại</button>
 </form>;
}

const actionNames:Record<string,string>={'auth.login':'Đăng nhập','user.create':'Tạo tài khoản','user.update':'Đổi vai trò / trạng thái','source.create':'Tạo nguồn','source.update':'Cập nhật nguồn / quyền','source.delete':'Xóa nguồn','document.update':'Cập nhật tài liệu / quyền','document.delete':'Xóa tài liệu','job.enqueue':'Tạo tác vụ','job.schedule':'Đồng bộ theo lịch','evaluation.run':'Chạy đánh giá','query.failed':'Lỗi gọi mô hình'};
export function OperationsPanel(){
 const [summary,setSummary]=useState<Row|null>(null),[events,setEvents]=useState<Row>({items:[],total:0}),[page,setPage]=useState(1),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function load(){setBusy(true);setError('');try{const [s,e]=await Promise.all([request<Row>('/admin/usage?days=30'),request<Row>('/admin/audit?page='+page+'&page_size=25')]);setSummary(s);setEvents(e);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 useEffect(()=>{load();},[page]);
 const seconds=(value:number|null)=>value==null?'—':(value/1000).toLocaleString('vi-VN',{maximumFractionDigits:1})+' giây';
 return <div className="operations-panel"><div className="panel-heading"><h3>Hoạt động 30 ngày gần nhất</h3><button className="btn" disabled={busy} onClick={load}><RefreshCw size={14}/>Làm mới</button></div>
  {error&&<p className="error-text" role="alert">{error}</p>}
  {summary&&<><div className="overview-grid operations-metrics">{[['Lượt hỏi',summary.questions],['Người dùng tra cứu',summary.active_users],['Phản hồi hữu ích',summary.positive_feedback],['Phản hồi cần sửa',summary.negative_feedback],['Thời gian trung vị',seconds(summary.latency_p50_ms)],['Thời gian P95',seconds(summary.latency_p95_ms)],['Token đầu vào',summary.prompt_tokens],['Token đầu ra',summary.completion_tokens]].map(([label,value])=><div className="overview-card" key={label}><div><small>{label}</small><strong>{value}</strong></div></div>)}</div><p className="inline-note">Số liệu sử dụng và phản hồi của người dùng không thay thế đánh giá độ chính xác trên bộ câu hỏi độc lập.</p></>}
  <section className="table-panel"><div className="panel-heading"><h3>Nhật ký quản trị</h3><span>{events.total} sự kiện</span></div><div className="table-scroll"><table><thead><tr><th>Thời gian</th><th>Người thực hiện</th><th>Thao tác</th><th>Đối tượng</th></tr></thead><tbody>{events.items.map((e:Row)=><tr key={e.id}><td>{new Date(e.created_at).toLocaleString('vi-VN')}</td><td>{e.actor_name||'Tự động'}</td><td>{actionNames[e.action]||e.action}</td><td>{e.resource_type}<small className="cell-sub">{e.resource_id.slice(0,12)}</small></td></tr>)}</tbody></table></div><div className="history-pagination"><span>Trang {page} / {Math.max(1,Math.ceil(events.total/25))}</span><div><button className="btn" disabled={busy||page===1} onClick={()=>setPage(page-1)}>Trước</button><button className="btn" disabled={busy||page*25>=events.total} onClick={()=>setPage(page+1)}>Sau</button></div></div></section>
 </div>;
}

export function EvaluationImport({docs,onImport}:{docs:Row[];onImport:(cases:Row[])=>void}){
 const [error,setError]=useState('');
 async function load(file?:File){
  if(!file)return;setError('');
  try{
   if(file.size>2*1024*1024)throw Error('Bộ câu hỏi tối đa 2 MB.');
   const raw=JSON.parse(await file.text());const cases=Array.isArray(raw)?raw:raw.cases;
   if(!Array.isArray(cases)||!cases.length||cases.length>100)throw Error('Cần từ 1 đến 100 câu hỏi.');
   const mapped=cases.map((c:Row)=>{
    if(typeof c.question!=='string')throw Error('Mỗi câu cần nội dung question.');
    const noAnswer=c.expected_behavior?c.expected_behavior!=='answer':!!c.no_answer;
    const filenames=[...new Set((c.expected_evidence||[]).map((e:Row)=>e.file_name))];
    const ids=c.expected_document_ids||filenames.map(name=>{const d=docs.find(d=>d.title===name&&d.status==='INDEXED');if(!d)throw Error('Chưa lập chỉ mục tài liệu: '+name);return d.id;});
    if(!noAnswer&&!ids.length)throw Error('Câu có đáp án cần tài liệu kỳ vọng.');
    return {question:c.question,no_answer:noAnswer,expected_document_ids:noAnswer?[]:ids,expected_chunk_ids:c.expected_chunk_ids||[]};
   });
   onImport(mapped);
  }catch(e){setError((e as Error).message);}
 }
 return <div className="evaluation-import"><label className="field-label">Nhập bộ câu hỏi JSON<input type="file" accept=".json,application/json" onChange={e=>load(e.target.files?.[0])}/></label>{error&&<p className="error-text" role="alert">{error}</p>}<p className="inline-note">Lượt chạy trên trang này chỉ đo truy xuất. Độ đúng câu trả lời và nguồn cần được chấm riêng.</p></div>;
}
