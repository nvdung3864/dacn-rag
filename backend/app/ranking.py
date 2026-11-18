"""Keyword reranking of a bounded, permission-filtered vector shortlist."""
import math
import re
from collections import Counter
from .questions import normalize_question

STOP_WORDS=set('là thì có không được của và hay với cho trong em tôi mình bạn vậy rồi giờ ko hông dc đc gì nào mấy tới bao nhiêu điểm'.split())


def tokens(text):
    return [t for t in re.findall(r'\d+[.,]\d+|[^\W\d_]+|\d+',normalize_question(text)) if t not in STOP_WORDS]


def rerank(question,hits,top_k):
    terms=set(tokens(question))
    if not terms or len(hits)<2:return hits[:top_k]
    bags=[Counter(tokens(h['text'])) for h in hits]
    df={t:sum(t in bag for bag in bags) for t in terms}
    scores=[sum(math.log(1+(len(hits)+1)/(df[t]+1))*min(bag[t],2) for t in terms if t in bag) for bag in bags]
    if not any(scores):return hits[:top_k]
    lexical=sorted(range(len(hits)),key=lambda i:(-scores[i],i))
    ranks={idx:rank+1 for rank,idx in enumerate(lexical)}
    # Similarity remains the actual cosine score used by no-answer filtering.
    combined=[{**h,'keyword_score':round(scores[i],4),'ranking_score':1/(20+i+1)+1/(20+ranks[i])} for i,h in enumerate(hits)]
    return sorted(combined,key=lambda h:(-h['ranking_score'],-h['keyword_score'],-h['score'],h['chunk_id']))[:top_k]
