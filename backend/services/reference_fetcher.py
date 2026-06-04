import re
import httpx
from backend.config import settings

async def fetch_source_metadata(reference_text: str) -> dict:
    """
    DOI抽出、Semantic Scholar、および Crossref を組み合わせて
    論文メタデータ・要約を取得する。
    """
    # 1. DOIの抽出を試みる
    doi = _extract_doi(reference_text)
    
    async with httpx.AsyncClient(timeout=settings.request_timeout_sec) as client:
        # A. DOIがある場合は最優先
        if doi:
            data = await _fetch_from_semantic_scholar_by_id(client, doi)
            if data and data.get("title"): return data
        
        # B. 段階的にクエリを変えて検索
        queries = [
            _query_from_reference(reference_text),  # 著者 + タイトルの一部
            re.sub(r"^[\[\d\.\]\s]+", "", reference_text)[:120], # 行の冒頭
            re.sub(r"[\(\)\[\]]", " ", reference_text)[:150], # 括弧を除去した生テキスト
        ]
        
        for q in queries:
            if not q or len(q) < 10: continue
            
            # Semantic Scholar
            data = await _fetch_from_semantic_scholar_search(client, q)
            if data and data.get("title"): return data
            
            # Crossref
            data = await _fetch_from_crossref(client, q)
            if data and data.get("title"): return data

    return {}

def _extract_doi(text: str) -> str | None:
    # doi: 10.xxxx/xxxx 形式を抽出
    m = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", text, re.I)
    return m.group(0) if m else None

async def _fetch_from_semantic_scholar_by_id(client, paper_id):
    url = f"{settings.semantic_scholar_base}/paper/{paper_id}"
    params = {"fields": "title,abstract,url,openAccessPdf,year,authors"}
    try:
        resp = await client.get(url, params=params)
        if resp.status_code == 200:
            return _parse_s2_item(resp.json())
    except: pass
    return None

async def _fetch_from_semantic_scholar_search(client, query):
    url = f"{settings.semantic_scholar_base}/paper/search"
    params = {"query": query, "limit": 2, "fields": "title,abstract,url,openAccessPdf,year,authors"}
    try:
        resp = await client.get(url, params=params)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("data"):
                return _parse_s2_item(data["data"][0])
    except: pass
    return None

async def _fetch_from_crossref(client, query):
    url = "https://api.crossref.org/works"
    params = {"query.bibliographic": query, "rows": 1}
    # Crossrefはユーザーエージェントを推奨している（制限緩和のため）
    headers = {"User-Agent": "RICS_Reference_Checker/1.0 (mailto:example@example.com)"}
    try:
        resp = await client.get(url, params=params, headers=headers)
        if resp.status_code == 200:
            items = resp.json().get("message", {}).get("items", [])
            if items:
                item = items[0]
                
                # タイトル、ジャーナル名、年などを結合して、より正確な情報を渡す
                title_list = item.get("title", [])
                title = title_list[0] if title_list else ""
                
                container_list = item.get("container-title", [])
                journal = container_list[0] if container_list else ""
                
                full_title = f"{title} [{journal}]".strip()
                
                # 要約(abstract)が含まれている場合は、JATS XML等のタグを除去して抽出
                abstract = item.get("abstract", "")
                if abstract:
                    abstract = re.sub(r"<[^>]+>", " ", abstract) # HTML/XMLタグ除去
                    abstract = re.sub(r"\s+", " ", abstract).strip()

                year = None
                try:
                    dp = item.get("published-print", {}).get("date-parts") or item.get("published", {}).get("date-parts")
                    if dp: year = dp[0][0]
                except: pass

                authors = []
                for a in item.get("author", []):
                    if isinstance(a, dict) and a.get("family"):
                        authors.append(a.get("family"))
                
                return {
                    "title": title,
                    "abstract": item.get("abstract") or "",
                    "url": item.get("URL") or "",
                    "year": year,
                    "authors": ", ".join(authors[:5]),
                    "has_full_text": False,
                    "open_access_pdf": None,
                }
    except Exception as e:
        print(f"  [Crossref Error] {e}")
    return None

def _parse_s2_item(item):
    pdf_info = item.get("open_access_pdf") or {}
    pdf_url = pdf_info.get("url") if isinstance(pdf_info, dict) else None
    authors = ", ".join([a.get("name", "") for a in item.get("authors", [])[:3]])
    return {
        "title": item.get("title") or "",
        "abstract": item.get("abstract") or "",
        "url": item.get("url") or pdf_url or "",
        "year": item.get("year"),
        "authors": authors,
        "has_full_text": bool(item.get("abstract") and len(item["abstract"]) > 50),
        "open_access_pdf": pdf_url,
    }

def _query_from_reference(ref: str) -> str:
    # 1. 参考文献テキストからノイズを除去
    q = re.sub(r"doi[:\s].*$", "", ref, flags=re.I)
    q = re.sub(r"https?://\S+", "", q)
    q = re.sub(r"^[\[\d\.\]\s]+", "", q) 
    
    # 2. 論文タイトルらしい部分をスマートに切り出す
    # 略語のドット（al., J., Vol.）で分割しないように保護
    q_protected = q
    for abbrev in ["al.", "et al.", "J.", "Vol.", "No.", "Ed.", "Eds.", "pp."]:
        q_protected = q_protected.replace(abbrev, abbrev.replace(".", "@@@"))

    segments = [s.replace("@@@", ".").strip() for s in re.split(r"[\.\?]", q_protected) if len(s.strip()) > 5]
    
    # 著者名を除外した「純粋なタイトル」を狙う
    # 通常、最初のセグメントが著者、2番目がタイトルのことが多い
    if len(segments) >= 2:
        title_candidate = segments[1]
        # タイトルが短すぎる場合は、3番目も繋げてみる
        if len(title_candidate) < 20 and len(segments) >= 3:
            title_candidate = f"{title_candidate} {segments[2]}"
        
        # 著者(最初のセグメント)の最初の単語をキーワードとして加える（精度向上）
        author_hint = ""
        author_m = re.search(r"^[A-Z][a-z]+", segments[0])
        if author_m:
            author_hint = author_m.group(0)
            
        return f"{author_hint} {title_candidate}".strip()
    
    # 分割できなかった場合は、最初の100文字程度を返す
    return q[:100].strip()

