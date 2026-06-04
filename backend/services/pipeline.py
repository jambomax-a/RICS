import asyncio
import shutil
import tempfile
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import CitationCheck, Paper, Verdict
from backend.services import document_parser, reference_fetcher, verifier

"""
Pipeline Service (メインパイプライン)
論文のアップロードから、解析、文献取得、AI検証までの一連の流れをオーケストレートします。
"""

def _create_empty_result(verdict: Verdict, reason: str, body_excerpt: str, source_excerpt: str):
    return {
        "verdict": verdict,
        "reason": reason,
        "body_excerpt": body_excerpt,
        "source_excerpt": source_excerpt,
        "evidence_main": "",
        "evidence_source": "",
    }


async def _download_oa_pdf(url: str) -> Path | None:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, follow_redirects=True)
            if resp.status_code == 200 and "application/pdf" in resp.headers.get(
                "content-type", ""
            ):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(resp.content)
                    return Path(tmp.name)
    except Exception:
        pass
    return None


async def process_paper(db: Session, file_path: Path, filename: str) -> Paper:
    text = document_parser.normalize_text(document_parser.extract_text(file_path))
    
    # メイン論文のタイトル取得を強化
    # 1. DOIを探してオンラインで正確なタイトルを取得
    main_doi = document_parser.extract_doi_from_text(text)
    title = None
    if main_doi:
        print(f"DEBUG: Main paper DOI detected: {main_doi}. Fetching real title...")
        try:
            main_meta = await reference_fetcher.fetch_source_metadata(f"doi: {main_doi}")
            if main_meta and main_meta.get("title"):
                title = main_meta["title"]
                print(f"DEBUG: Found real title online: {title}")
        except Exception as e:
            print(f"DEBUG: Failed to fetch title via DOI: {e}")
    
    # 2. メタデータ (PDF形式のみ) から取得
    if not title:
        meta_title = document_parser.extract_metadata_title(file_path)
        if meta_title:
            title = meta_title

    # 3. DOIでもメタデータでも見つからない場合はテキストから推測
    if not title:
        title = document_parser.guess_title(text, filename, file_path=file_path)

    # 4. タイトルが不十分な場合（ファイル名のまま等）はLLMに訊くか再抽出
    if not title or title == Path(filename).stem or len(title) < 10:
        try:
            # LLMが初期化可能なら、タイトルの推定を試みる
            llm = verifier._get_llm()
            if llm:
                prompt = (
                    "以下の論文の冒頭部分から、正式なタイトルのみを抽出してテキストで答えてください。\n"
                    "装飾や説明は不要です。タイトルが見つからない場合はファイル名を使用してください。\n\n"
                    f"Filename: {filename}\n"
                    f"Content:\n{text[:2000]}"
                )
                output = llm.create_chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=200,
                    temperature=0.1
                )
                extracted = output["choices"][0]["message"]["content"].strip().strip('"')
                if extracted and len(extracted) > 10 and "\n" not in extracted:
                    title = extracted
        except Exception as e:
            print(f"DEBUG: LLM title extraction failed: {e}")
            # LLMが失敗した場合は元の判定を維持
            if not title:
                title = document_parser.guess_title(text[:2000], filename)

    refs = document_parser.extract_reference_section(text)

    dest = settings.uploads_dir / f"{file_path.stem}_{filename}"
    shutil.copy2(file_path, dest)

    paper = Paper(
        title=title,
        filename=filename,
        file_path=str(dest),
        full_text=text,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)

    total_refs = len(refs)
    for i, (ref_num, ref_text) in enumerate(refs):
        try:
            print(f"[{i+1}/{total_refs}] Reference [{ref_num}] - 処理中...", end="\r")
            # 429エラー回避のため、検索前に待機
            await asyncio.sleep(1.0) 
            body = document_parser.extract_body_citations(text, ref_num, ref_text)
            
            # 本文抜粋がまったくない場合は、LLM 判定自体に意味がない（コンテキスト不足）ためスキップ
            if not body.strip():
                print(f"[{i+1}/{total_refs}] Reference [{ref_num}] - Skipped (No body citation found)")
                v = _create_empty_result(Verdict.UNAVAILABLE, "本論文内にこの文献の引用箇所を見つけられませんでした。形式が特殊な可能性があります。", "", "")
                meta = {"title": "Not found in body", "ref_number": ref_num}
            else:
                meta = await reference_fetcher.fetch_source_metadata(ref_text) or {}
                meta['ref_number'] = ref_num

                oa_pdf_url = meta.get("open_access_pdf")
                oa_text = None
                if oa_pdf_url:
                    tmp_pdf = await _download_oa_pdf(oa_pdf_url)
                    if tmp_pdf:
                        try:
                            oa_text = document_parser.extract_text(tmp_pdf)
                        finally:
                            tmp_pdf.unlink()

                v = verifier.verify_citation(body, ref_text, meta, manual_text=oa_text)
            
            # 結果を表示 (LLMを使っているかを明示)
            mode = "🤖 LLM" if verifier._llm else "📄 HEURISTIC"
            print(f"[{i+1}/{total_refs}] Ref [{ref_num}] - {mode} | Verdict: {v['verdict']}")

            check = CitationCheck(
                paper_id=paper.id,
                ref_number=ref_num,
                reference_text=ref_text,
                body_excerpt=body,
                source_title=meta.get("title"),
                source_url=meta.get("url"),
                source_abstract=meta.get("abstract"),
                verdict=v["verdict"],
                reason=v["reason"],
                evidence_main=v["evidence_main"],
                evidence_source=v["evidence_source"],
            )
            db.add(check)
            db.commit()
        except Exception as e:
            print(f"\n[Error] Reference [{ref_num}] の処理中に致命的なエラーが発生しました: {e}")
            import traceback
            traceback.print_exc()
            # 個別の引用エラーで全体を止めない
            continue

    db.refresh(paper)
    return paper


async def recheck_with_manual(
    db: Session, citation_id: int, manual_path: Path
) -> CitationCheck:
    check = db.get(CitationCheck, citation_id)
    if not check:
        raise ValueError("引用チェックが見つかりません")

    manual_text = document_parser.normalize_text(
        document_parser.extract_text(manual_path)
    )
    dest = settings.uploads_dir / f"manual_{citation_id}_{manual_path.name}"
    shutil.copy2(manual_path, dest)
    check.manual_file_path = str(dest)

    meta = {
        "title": check.source_title or "",
        "abstract": manual_text[:8000],
        "authors": "",
        "year": "",
    }
    v = verifier.verify_citation(
        check.body_excerpt,
        check.reference_text,
        meta,
        manual_text=manual_text,
    )
    check.verdict = v["verdict"]
    check.reason = v["reason"]
    check.evidence_main = v["evidence_main"]
    check.evidence_source = v["evidence_source"]
    db.commit()
    db.refresh(check)
    return check
