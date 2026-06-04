import re
from pathlib import Path

"""
Document Parser Service (ドキュメント解析サービス)
PDFやWord、テキストファイルから本文を抽出し、
引用（[1]など）の前後文脈や参考文献リストをパースします。
"""

# Unicode 上付き数字（PDF で ¹²³ として残ることがある）
_SUPERSCRIPT_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_SUPERSCRIPT_MAP = {c: i for i, c in enumerate(_SUPERSCRIPT_DIGITS)}

_REF_SECTION_MARKERS = [
    r"(?im)^\s*(?:references|bibliography|works\s+cited|literature\s+cited)\s*$",
    r"(?im)^\s*(?:参考文献|引用文献|文献)\s*$",
]


def normalize_text(text: str) -> str:
    text = text.replace("\ufeff", "")
    # 全角数字・括弧を半角に寄せる（検出のため）
    trans = str.maketrans("０１２３４５６７８９［］（）", "0123456789[]()")
    return text.translate(trans).strip()


def extract_text(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return _pdf_text(file_path)
    if suffix in {".docx", ".doc"}:
        return _docx_text(file_path)
    if suffix in {".txt", ".md", ".tex", ".rtf"}:
        return normalize_text(file_path.read_text(encoding="utf-8", errors="replace"))
    raise ValueError(f"未対応の形式です: {suffix}")


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    return normalize_text("\n".join(parts))


def _docx_text(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    return normalize_text("\n".join(p.text for p in doc.paragraphs if p.text.strip()))


_GENERIC_HEADERS = re.compile(
    r"^(?:consensus\s+statement|original\s+article|review\s+article|"
    r"abstract|summary|introduction|keywords|key\s+words|"
    r"table\s+of\s+contents|contents|doi\s*:|https?://)\s*$",
    re.IGNORECASE,
)

# タイトル直前の短い帯のみ（Abstract 等は含めない）
_TITLE_BANNER = re.compile(
    r"^(?:consensus\s+statement|original\s+article|review\s+article|"
    r"brief\s+report|short\s+communication)\s*$",
    re.IGNORECASE,
)

_TITLE_KEYWORDS = re.compile(
    r"consensus|guideline|statement|review|meta-?analysis|"
    r"diagnosis|treatment|classification|monitoring|pulmonary|hypertension",
    re.IGNORECASE,
)


def _insert_spaces_in_glued_text(s: str) -> str:
    """PDFでつながった英単語に空白を挿入（ACVIMconsensus... 等）。"""
    if len(s) < 20:
        return s
    if s.count(" ") >= max(4, len(s) // 25):
        return re.sub(r"\s+", " ", s).strip()

    s = s.replace(",", ", ")
    s = re.sub(r"^ACVIM", "ACVIM ", s, flags=re.I)
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)

    glued_phrases = [
        (r"consensusstatement", "consensus statement"),
        (r"statementguidelines", "statement guidelines"),
        (r"guidelinesfor", "guidelines for"),
        (r"forthe", "for the"),
        (r"thediagnosis", "the diagnosis"),
        (r"andmonitoringof", "and monitoring of"),
        (r"monitoringof", "monitoring of"),
        (r"ofpulmonary", "of pulmonary"),
        (r"pulmonaryhypertension", "pulmonary hypertension"),
        (r"hypertensionin", "hypertension in"),
        (r"hypertensionindogs", "hypertension in dogs"),
        (r"indogs", "in dogs"),
        (r"in\s*dogs", "in dogs"),
        (r"in\s*cats", "in cats"),
    ]
    for pat, repl in glued_phrases:
        s = re.sub(pat, repl, s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


def _normalize_title_candidate(raw: str) -> str:
    t = re.sub(r"\s+", " ", raw).strip()
    if len(t) > 35 and (t.count(" ") <= 3 or re.search(r"[a-z]{5,}[a-z]{5,}", t, re.I)):
        t = _insert_spaces_in_glued_text(t)
    return t[:512]


def _title_score(candidate: str) -> float:
    if len(candidate) < 12:
        return -10.0
    if _GENERIC_HEADERS.match(candidate.strip()):
        return -5.0
    score = min(len(candidate), 300) / 10.0
    if _TITLE_KEYWORDS.search(candidate):
        score += 15.0
    if re.search(r"\bACVIM\b", candidate, re.I):
        score += 10.0
    if candidate.isupper() and len(candidate) < 35:
        score -= 8.0
    if re.match(r"^\[\d+\]", candidate):
        score -= 20.0
    return score


def extract_metadata_title(file_path: Path) -> str | None:
    """PDFのメタデータからタイトル取得を試みる。"""
    if file_path.suffix.lower() != ".pdf":
        return None
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(file_path))
        meta = reader.metadata
        if meta and meta.title:
            # 意味のないタイトル（"Microsoft Word - ..." 等）を除外
            t = meta.title.strip()
            if t and not re.search(r"Microsoft Word|Untitled|pdf|layout", t, re.I):
                return t
    except:
        pass
    return None


def extract_doi_from_text(text: str) -> str | None:
    """テキストの先頭付近から論文自身のDOIを探す。"""
    # 先頭20000文字程度を対象にする（DOIは通常1ページ目にあるが、前置きが長い場合を考慮）
    head = text[:20000]
    # DOIの正規パターン (10.1234/abc...)
    # PDF抽出時にノイズが入ることを考慮して少し緩めに、かつ確実にDOIらしいものを探す
    m = re.search(r"10\.\d{4,9}/[^\s<>]+", head, re.I)
    if m:
        doi = m.group(0).rstrip(".,;)]}") # 末尾の記号を除去
        # 明らかなゴミが混じっている場合は除外
        if len(doi) > 10 and "/" in doi:
            return doi
    return None


def guess_title(text: str, filename: str, file_path: Path | None = None) -> str:
    """
    論文タイトルを推定。
    1. メタデータ (PDF)
    2. 先頭付近からの抽出（短い見出し行はスキップ、複数行を結合）
    3. ファイル名（最終手段）
    """
    # 1. メタデータ
    if file_path:
        meta_title = extract_metadata_title(file_path)
        if meta_title:
            return meta_title

    # 2. テキスト解析
    head = text[:8000]
    lines = [ln.strip() for ln in head.splitlines() if ln.strip()]

    candidates: list[str] = []

    # 汎用見出し（CONSENSUS STATEMENT 等）の直後から数行を正式タイトル候補にする
    start = 0
    for i, line in enumerate(lines[:8]):
        if _TITLE_BANNER.match(line) or (
            line.isupper() and len(line) < 40 and "STATEMENT" in line.upper()
        ):
            start = i + 1
    title_after_banner: str | None = None
    if start > 0 and start < len(lines):
        title_lines: list[str] = []
        for line in lines[start : start + 6]:
            low = line.lower()
            if low.startswith("abstract") or low.startswith("introduction"):
                break
            if _GENERIC_HEADERS.match(line):
                continue
            title_lines.append(line)
        if title_lines:
            title_after_banner = _normalize_title_candidate(" ".join(title_lines))
            candidates.append(title_after_banner)

    for i, line in enumerate(lines[:45]):
        if re.match(r"^\[\d+\]", line) or _GENERIC_HEADERS.match(line):
            continue
        norm = _normalize_title_candidate(line)
        if norm and len(norm) >= 20:
            candidates.append(norm)
        if i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if (
                len(norm) >= 10
                and len(nxt) >= 5
                and not _GENERIC_HEADERS.match(nxt)
                and not nxt.lower().startswith("abstract")
            ):
                merged = _normalize_title_candidate(f"{norm} {nxt}")
                candidates.append(merged)

    if not candidates:
        return Path(filename).stem

    if title_after_banner and _title_score(title_after_banner) > 5:
        return title_after_banner

    best = max(candidates, key=lambda c: (_title_score(c), len(c)))
    if _title_score(best) < 0:
        return Path(filename).stem
    return best


def split_body_and_references(text: str) -> tuple[str, str]:
    """本文と参考文献セクションを分離（本文検索で参考文献を拾わない）。"""
    start = len(text)
    for pattern in _REF_SECTION_MARKERS:
        m = re.search(pattern, text)
        if m and m.start() < start:
            start = m.start()
    if start < len(text):
        return text[:start].strip(), text[start:].strip()
    # 見出しが無い場合: 末尾の [n] / n. 条目が続く塊を参考文献とみなす
    tail = text[-15000:] if len(text) > 15000 else text
    ref_start_in_tail = None
    for m in re.finditer(
        r"(?:^|\n)\s*(?:\[(\d+)\]|(\d+)\.)\s+(.{20,})",
        tail,
        re.MULTILINE,
    ):
        n = int(m.group(1) or m.group(2))
        if n <= 3:
            ref_start_in_tail = m.start()
            break
    if ref_start_in_tail is not None and len(text) > 5000:
        abs_start = len(text) - len(tail) + ref_start_in_tail
        if abs_start > len(text) * 0.4:
            return text[:abs_start].strip(), text[abs_start:].strip()
    return text.strip(), ""


def extract_reference_section(text: str) -> list[tuple[int, str]]:
    """参考文献セクションから [番号] または番号. 形式の条目を抽出。"""
    _body, ref_section = split_body_and_references(text)
    section = ref_section if ref_section else text[-12000:]

    entries: list[tuple[int, str]] = []
    pattern = re.compile(
        r"(?:^|\n)\s*(?:\[(\d+)\]|(\d+)\.)\s+(.+?)(?=(?:\n\s*(?:\[\d+\]|\d+\.)\s)|\Z)",
        re.DOTALL,
    )
    for m in pattern.finditer(section):
        num = int(m.group(1) or m.group(2))
        body = re.sub(r"\s+", " ", m.group(3)).strip()
        if len(body) > 15:
            entries.append((num, body))

    if not entries:
        nums = sorted({int(x) for x in re.findall(r"\[(\d+)\]", section)})
        for n in nums[:80]:
            entries.append((n, f"Reference {n} (参考文献テキストから自動抽出)"))
    return sorted(entries, key=lambda x: x[0])


def _to_superscript_str(n: int) -> str:
    return "".join(_SUPERSCRIPT_DIGITS[int(d)] for d in str(n))


def _parse_author_year_hints(reference_text: str) -> tuple[list[str], str | None]:
    cleaned = re.sub(r"^[\[\d\.\]\s]+", "", reference_text)
    year_m = re.search(r"\b(19|20)\d{2}[a-z]?\b", cleaned)
    year = year_m.group(0) if year_m else None

    authors: list[str] = []
    seen: set[str] = set()

    for m in re.finditer(
        r"([A-Z][A-Za-z\-']+)(?:\s*,\s*[A-Z]\.?|\s+et\s+al\.?)?",
        cleaned[:300],
    ):
        name = m.group(1)
        if name.lower() not in {"the", "and", "for", "vol", "doi", "http", "https"}:
            if name not in seen:
                seen.add(name)
                authors.append(name)

    for m in re.finditer(r"([一-龯々〆ヵヶ]{1,6})(?:\s*[，,、]\s*|[\s　])", cleaned[:300]):
        name = m.group(1)
        if name not in seen and len(name) >= 2:
            seen.add(name)
            authors.append(name)

    return authors[:4], year


def _collect_excerpts(text: str, pattern: re.Pattern, limit: int = 5) -> list[str]:
    hits = pattern.findall(text)
    unique: list[str] = []
    seen: set[str] = set()
    for h in hits[:limit]:
        compact = re.sub(r"\s+", " ", h).strip()
        if len(compact) > 20 and compact not in seen:
            seen.add(compact)
            unique.append(compact)
    return unique


def extract_body_citations(
    text: str,
    ref_number: int,
    reference_text: str = "",
) -> str:
    """
    指定引用番号に対応する本文抜粋を返す。
    複数の引用表記（番号・著者年・上付き・範囲指定・リスト指定）を順に試す。
    """
    body, _ = split_body_and_references(text)
    if not body.strip():
        body = text

    n = ref_number
    strategies: list[tuple[str, list[str]]] = []

    # A) ブラケット内 [...], (...) を解析して、個別の数字・範囲が含まれるかチェック
    # 例: [1, 2, 5-8] を 1, 2, 5, 6, 7, 8 に展開して判定
    bracket_patterns = [
        r"\[([\d\s,\-\–\—]+)\]",
        r"\(([\d\s,\-\–\—]+)\)",
    ]
    for bp in bracket_patterns:
        matches = []
        for m in re.finditer(bp, body):
            content = m.group(1)
            # コンマやスペースで区切られたパーツを取得
            parts = re.split(r"[,;\s]+", content)
            hit = False
            for p in parts:
                p = p.strip()
                if not p: continue
                # 範囲指定が含まれるかチェック 5-8
                rm = re.search(r"(\d+)\s?[\-\–\—]\s?(\d+)", p)
                if rm:
                    if int(rm.group(1)) <= n <= int(rm.group(2)):
                        hit = True; break
                elif p.isdigit() and int(p) == n:
                    hit = True; break
            
            if hit:
                matches.append(_get_highlighted_excerpt(body, m.start(), m.end(), n))
        
        if matches:
            strategies.append(("combined_bracket", matches[:5]))

    # C) 1) [n] / (n) / 上付き
    numeric_patterns = [
        ("bracket", rf"\[{n}\]"),
        ("paren", rf"\({n}\)"),
        ("superscript", re.escape(_to_superscript_str(n))),
        ("inline_num", rf"(?<=[^\d\[]){n}(?=[,、\-\)\s\.。])"),
    ]
    for mode, pat in numeric_patterns:
        matches = []
        for m in re.finditer(pat, body):
            matches.append(_get_highlighted_excerpt(body, m.start(), m.end(), n))
        if matches:
            strategies.append((mode, matches[:5]))

    # D) 2) 著者名 + 年（Harvard / APA 系）
    authors, year = _parse_author_year_hints(reference_text)
    if authors:
        author_hits: list[str] = []
        for author in authors:
            # f-string 内で {n,m} を使うには二重括弧が必要
            pat_str = rf"{re.escape(author)}.{{0,50}}{year}" if year else re.escape(author)
            for m in re.finditer(pat_str, body, re.IGNORECASE):
                author_hits.append(_get_highlighted_excerpt(body, m.start(), m.end(), author))
        if author_hits:
            strategies.append(("author_year", author_hits[:5]))

    if not strategies:
        return ""

    mode, excerpts = strategies[0]
    return "\n---\n".join(excerpts)


def _get_highlighted_excerpt(text: str, start: int, end: int, target: any) -> str:
    """指定箇所の前後500文字を切り出し、ターゲットを強調表示する。"""
    s = max(0, start - 500)
    e = min(len(text), end + 500)
    
    before = text[s:start]
    target_text = text[start:end]
    after = text[end:e]
    
    # AIが迷わないようにマーカーを打つ
    return f"{before}【★今回の審査対象引用⇒】{target_text}【★ここまで】{after}"


def diagnose_citation_extraction(text: str) -> dict:
    """デバッグ用: どの形式がどれだけ検出されたか。"""
    body, ref_sec = split_body_and_references(text)
    refs = extract_reference_section(text)
    found = sum(
        1 for n, rt in refs if extract_body_citations(text, n, rt).strip()
    )
    return {
        "reference_count": len(refs),
        "body_chars": len(body),
        "matched_in_body": found,
        "has_reference_section": bool(ref_sec),
        "bracket_markers_in_body": len(re.findall(r"\[\d+\]", body)),
        "author_year_like_in_body": len(
            re.findall(r"\([A-Z][a-z]+[^)]{0,40}(19|20)\d{2}", body)
        ),
    }
