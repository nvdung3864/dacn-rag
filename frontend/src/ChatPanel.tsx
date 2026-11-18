import {useEffect,useRef,useState} from 'react';
import {ArrowUp,ArrowUpRight,BookOpen,ChevronDown,Clock,Database,Link2,Loader2,RefreshCw,Sparkles} from 'lucide-react';
import {request,streamAnswer,type Answer,type Citation,type Row} from './api';
import {FreshnessNote,AnswerFeedback} from './AcceptancePanels';

type Message={id:string;question:string;result?:Answer;pending?:boolean;error?:string;retrievalOnly?:boolean;followupQueryId?:string;draft?:string;stage?:string};
type Props={conversationId:string|null;resetKey:number;onConversation:(id:string|null)=>void;onChanged:()=>Promise<void>;
 sources:Row[];sourceId:string;onSource:(id:string)=>void;topK:number;retrievalOnly:boolean;signedOut:boolean;
 revision?:string;initial:string;onLogin:()=>void;onCitation:(citation:Citation)=>void};

export default function ChatPanel(props:Props){
 const [messages,setMessages]=useState<Message[]>([]),[question,setQuestion]=useState(''),[sending,setSending]=useState(false),[loading,setLoading]=useState(false),[loadError,setLoadError]=useState('');
 const loaded=useRef<string|null>(null),controller=useRef<AbortController|null>(null),end=useRef<HTMLDivElement>(null),generation=useRef(0),sendLock=useRef(false);
 useEffect(()=>{return()=>{generation.current++;controller.current?.abort();};},[]);
 useEffect(()=>{
  if(loaded.current===props.conversationId&&props.conversationId&&!props.signedOut)return;
  generation.current++;controller.current?.abort();sendLock.current=false;setSending(false);setQuestion('');setLoadError('');
  if(props.signedOut||!props.conversationId){loaded.current=null;setMessages([]);setLoading(false);return;}
  const active=new AbortController();controller.current=active;const version=generation.current;
  setLoading(true);setMessages([]);
  request<Row>('/conversations/'+props.conversationId,{signal:active.signal}).then(row=>{
   if(version!==generation.current)return;
   const scope=row.messages.at(-1)?.result.source_ids||[];props.onSource(scope.length===1?scope[0]:'');
   loaded.current=row.id;setMessages(row.messages.map((m:Row)=>({id:m.id,question:m.question,result:{...m.result,query_id:m.id,conversation_id:row.id}})));
  }).catch(error=>{if(!active.signal.aborted){const message=(error as Error).message;if(message.toLocaleLowerCase('vi-VN').includes('cuộc trò chuyện')){loaded.current=null;setMessages([]);props.onConversation(null);}else setLoadError(message);}}).finally(()=>{if(version===generation.current)setLoading(false);});
  return()=>active.abort();
 },[props.conversationId,props.resetKey,props.signedOut]);
 useEffect(()=>{end.current?.scrollIntoView({behavior:'smooth',block:'nearest'});},[messages.length,sending]);
 async function send(text=question,retryId?:string,followupQueryId?:string){
  if(!text.trim()||sendLock.current||loading)return;
  if(props.signedOut){props.onLogin();return;}
  sendLock.current=true;setSending(true);setQuestion('');setLoadError('');
  const id=retryId||crypto.randomUUID(),version=generation.current,active=new AbortController();controller.current=active;
  const item:Message={id,question:text.trim(),pending:true,retrievalOnly:props.retrievalOnly,followupQueryId};
  setMessages(previous=>retryId?previous.map(m=>m.id===retryId?item:m):[...previous,item]);
  try{
   const body={question:text.trim(),conversation_id:loaded.current,followup_query_id:followupQueryId,top_k:props.topK,source_ids:props.sourceId?[props.sourceId]:[],retrieval_only:props.retrievalOnly};
   const result=await streamAnswer(body,(kind,data)=>{
    if(version!==generation.current)return;
    if(kind==='draft'||kind==='status')setMessages(previous=>previous.map(m=>m.id===id?{...m,draft:kind==='draft'?data.text:m.draft,stage:kind==='status'?data.message:m.stage}:m));
   },active.signal);
   if(version!==generation.current)return;
   setMessages(previous=>previous.map(m=>m.id===id?{...item,id:result.query_id||id,pending:false,result}:m));
   if(result.conversation_id){loaded.current=result.conversation_id;props.onConversation(result.conversation_id);}
   props.onChanged().catch(()=>{});
  }catch(error){
   if(version===generation.current&&!active.signal.aborted)setMessages(previous=>previous.map(m=>m.id===id?{...item,pending:false,error:(error as Error).message}:m));
  }finally{if(version===generation.current){sendLock.current=false;setSending(false);}}
 }
 return <div className="chat-main">
  {loading?<div className="thinking chat-loading" role="status"><Loader2 size={20} className="spin"/>Đang mở cuộc trò chuyện…</div>:loadError?<div className="empty-answer" role="alert">{loadError}</div>:!messages.length?<div className="welcome"><div className="sparkle-tile"><Sparkles size={30}/></div><h2>Bạn muốn tìm hiểu điều gì?</h2></div>:<div className="conversation" aria-label="Nội dung cuộc trò chuyện">{messages.map(message=><div className="chat-turn" key={message.id}>
   <div className="question-row"><div className="avatar small">{props.initial}</div><div><small>Bạn</small><p>{message.question}</p></div></div>
   <div className="answer-row"><div className="answer-icon"><Sparkles size={17}/></div><div className="answer-body"><div className="answer-head"><strong>BK Tri thức</strong>{message.result&&<span className="pill">{message.result.needs_clarification?'Cần làm rõ':message.result.no_answer?'Chưa đủ thông tin':message.result.missing_information?.length?'Thiếu một phần thông tin':message.retrievalOnly?'Chỉ truy xuất':'Dựa trên nguồn'}</span>}</div>
   {message.pending?<><div className="thinking" role="status"><Loader2 size={18} className="spin"/>{message.stage||'Đang tìm ngữ cảnh…'}</div>{message.draft&&<><p className="inline-note">Đang soạn · Nội dung chưa được kiểm chứng</p><div className="answer-text draft-answer">{message.draft.split('\n').map((line,index)=><p key={index}>{line}</p>)}</div></>}</>:message.error?<div className="message-error" role="alert"><p>{message.error}</p><button className="btn" disabled={sending} onClick={()=>send(message.question,message.id,message.followupQueryId)}><RefreshCw size={15}/>Thử lại</button></div>:message.result?<Reply message={message} revision={props.revision} disabled={sending} onAsk={()=>send(message.result?.resolved_question||message.question)} onExplain={()=>send('Giải thích thêm',undefined,message.result?.query_id)} onCitation={props.onCitation}/>:null}
   </div></div>
  </div>)}<div ref={end}/></div>}
  <form className="composer" onSubmit={event=>{event.preventDefault();send();}}><textarea aria-label="Câu hỏi" placeholder={messages.length?'Hỏi tiếp trong cuộc trò chuyện…':'Đặt câu hỏi về tài liệu của bạn…'} value={question} maxLength={3000} onChange={event=>setQuestion(event.target.value)} onKeyDown={event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.nativeEvent.isComposing){event.preventDefault();send();}}}/><div className="composer-bottom"><label className="source-select"><Database size={14}/><select aria-label="Chọn nguồn" value={props.sourceId} onChange={event=>props.onSource(event.target.value)} disabled={props.signedOut||sending}><option value="">Tất cả nguồn tri thức</option>{props.sources.filter(s=>s.enabled).map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select><ChevronDown size={13}/></label><button className="send" type="submit" disabled={!question.trim()||sending||loading||!!loadError} aria-label="Gửi câu hỏi"><ArrowUp size={19}/></button></div></form>
 </div>;
}

function Reply({message,revision,disabled,onAsk,onExplain,onCitation}:{message:Message;revision?:string;disabled:boolean;onAsk:()=>void;onExplain:()=>void;onCitation:(c:Citation)=>void}){
 const answer=message.result!;
 const [related,setRelated]=useState(false);
 return <>
  {revision&&answer.answer_revision!==revision&&<p className="inline-note">Kết quả được lưu từ phiên bản trước.</p>}
  {answer.answer&&<div className="answer-text">{answer.answer.split('\n').map((line,index)=><p key={index}>{line}</p>)}</div>}
  <FreshnessNote sources={answer.citations}/>
  {!message.retrievalOnly&&answer.citations.length>0&&<div className="citations"><div className="small-label"><Link2 size={14}/>NGUỒN TRÍCH DẪN <span>{answer.citations.length}</span></div>{answer.citations.map(c=><button className="citation-card" key={c.chunk_id} onClick={()=>onCitation(c)}><span className="source-number">{c.marker?.slice(1)||'1'}</span><div><strong>{c.title}</strong><small>{c.source_name}{c.page?' · Trang '+c.page:''}{c.section?' · '+c.section:''}</small></div><ArrowUpRight size={16}/></button>)}</div>}
  <div className="answer-actions"><button className="btn" disabled={disabled} onClick={onAsk}><RefreshCw size={15}/>Hỏi lại</button><button className="btn" onClick={()=>setRelated(!related)}><BookOpen size={15}/>{related?'Ẩn đoạn liên quan':'Xem đoạn liên quan'}</button>{!message.retrievalOnly&&!answer.no_answer&&answer.citations.length>0&&<button className="btn" disabled={disabled} onClick={onExplain}><Sparkles size={15}/>Giải thích thêm</button>}</div>
  {(related||message.retrievalOnly)&&<div className="related">{answer.retrieved_chunks.length?answer.retrieved_chunks.map((c,index)=><button key={c.chunk_id} onClick={()=>onCitation(c)}><div><strong>{index+1}. {c.title}</strong>{c.score!=null&&<span>Độ tương đồng {c.score.toFixed(3)}</span>}</div><p>{c.text}</p></button>):<p>Không có đoạn phù hợp.</p>}</div>}
  <div className="run-info"><Clock size={13}/>{(answer.latency_ms.total_ms/1000).toLocaleString('vi-VN',{maximumFractionDigits:1})} giây</div>
  {!message.retrievalOnly&&<AnswerFeedback answer={answer}/>}
 </>;
}
