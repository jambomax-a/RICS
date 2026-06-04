import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, joinedload

from backend.config import settings
from backend.database import get_db, init_db
from backend.models import CitationCheck, Paper, Verdict
from backend.schemas import CitationCheckOut, PaperDetail, PaperSummary, PaperTitleUpdate
from backend.services.pipeline import process_paper, recheck_with_manual

"""
RICS (Reference Integrity Check System) メインエントリーポイント
FastAPI を使用した WEB API サーバーを定義します。
"""

app = FastAPI(title="RICS", description="Reference Integrity Check System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = settings.base_dir / "frontend"


@app.on_event("startup")
def on_startup():
    init_db()


ALLOWED_SUFFIX = {".pdf", ".docx", ".doc", ".txt", ".md", ".tex", ".rtf"}


def _counts(citations: list[CitationCheck]) -> dict:
    c = {v.value: 0 for v in Verdict}
    for item in citations:
        c[item.verdict] = c.get(item.verdict, 0) + 1
    return c


@app.get("/api/papers", response_model=list[PaperSummary])
def list_papers(db: Session = Depends(get_db)):
    papers = db.query(Paper).order_by(Paper.created_at.desc()).all()
    out = []
    for p in papers:
        citations = p.citations
        counts = _counts(citations)
        out.append(
            PaperSummary(
                id=p.id,
                title=p.title,
                filename=p.filename,
                created_at=p.created_at,
                citation_count=len(citations),
                match_count=counts.get(Verdict.MATCH.value, 0),
                mismatch_count=counts.get(Verdict.MISMATCH.value, 0),
                unavailable_count=counts.get(Verdict.UNAVAILABLE.value, 0),
            )
        )
    return out


@app.get("/api/papers/{paper_id}", response_model=PaperDetail)
def get_paper(paper_id: int, db: Session = Depends(get_db)):
    paper = (
        db.query(Paper)
        .options(joinedload(Paper.citations))
        .filter(Paper.id == paper_id)
        .first()
    )
    if not paper:
        raise HTTPException(404, "論文が見つかりません")
    citations = sorted(paper.citations, key=lambda c: c.ref_number)
    return PaperDetail(
        id=paper.id,
        title=paper.title,
        filename=paper.filename,
        created_at=paper.created_at,
        citations=[
            CitationCheckOut(
                id=c.id,
                ref_number=c.ref_number,
                reference_text=c.reference_text,
                body_excerpt=c.body_excerpt,
                source_title=c.source_title,
                source_url=c.source_url,
                verdict=c.verdict,
                reason=c.reason,
                evidence_main=c.evidence_main,
                evidence_source=c.evidence_source,
                has_manual_upload=bool(c.manual_file_path),
            )
            for c in citations
        ],
    )


@app.post("/api/papers/upload", response_model=PaperDetail)
async def upload_paper(file: UploadFile = File(...), db: Session = Depends(get_db)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIX:
        raise HTTPException(400, f"対応形式: {', '.join(sorted(ALLOWED_SUFFIX))}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        paper = await process_paper(db, tmp_path, file.filename or "upload")
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, f"論文の処理に失敗しました: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    return get_paper(paper.id, db)


@app.post("/api/citations/{citation_id}/upload-manual", response_model=CitationCheckOut)
async def upload_manual_reference(
    citation_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIX:
        raise HTTPException(400, "PDF / Word / テキスト形式を指定してください")

    check = db.get(CitationCheck, citation_id)
    if not check:
        raise HTTPException(404, "引用が見つかりません")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        updated = await recheck_with_manual(db, citation_id, tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    return CitationCheckOut(
        id=updated.id,
        ref_number=updated.ref_number,
        reference_text=updated.reference_text,
        body_excerpt=updated.body_excerpt,
        source_title=updated.source_title,
        source_url=updated.source_url,
        verdict=updated.verdict,
        reason=updated.reason,
        evidence_main=updated.evidence_main,
        evidence_source=updated.evidence_source,
        has_manual_upload=bool(updated.manual_file_path),
    )


def _paper_summary(p: Paper, db: Session) -> PaperSummary:
    counts = _counts(p.citations)
    return PaperSummary(
        id=p.id,
        title=p.title,
        filename=p.filename,
        created_at=p.created_at,
        citation_count=len(p.citations),
        match_count=counts.get(Verdict.MATCH.value, 0),
        mismatch_count=counts.get(Verdict.MISMATCH.value, 0),
        unavailable_count=counts.get(Verdict.UNAVAILABLE.value, 0),
    )


@app.patch("/api/papers/{paper_id}", response_model=PaperSummary)
def update_paper_title(
    paper_id: int,
    body: PaperTitleUpdate,
    db: Session = Depends(get_db),
):
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "タイトルを入力してください")
    if len(title) > 512:
        raise HTTPException(400, "タイトルは512文字以内にしてください")

    paper = db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(404, "論文が見つかりません")
    paper.title = title
    db.commit()
    db.refresh(paper)
    return _paper_summary(paper, db)


@app.post("/api/papers/{paper_id}/refresh-title", response_model=PaperSummary)
def refresh_paper_title(paper_id: int, db: Session = Depends(get_db)):
    from backend.services import document_parser

    paper = db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(404, "論文が見つかりません")
    if not paper.full_text:
        raise HTTPException(400, "保存された全文がないため再抽出できません")

    paper.title = document_parser.guess_title(paper.full_text, paper.filename)
    db.commit()
    db.refresh(paper)
    return _paper_summary(paper, db)


@app.get("/api/debug/citation-diagnosis")
def citation_diagnosis(db: Session = Depends(get_db)):
    """直近登録論文の引用検出状況（チューニング用）。"""
    from backend.services import document_parser

    paper = db.query(Paper).order_by(Paper.created_at.desc()).first()
    if not paper or not paper.full_text:
        raise HTTPException(404, "論文がありません")
    diag = document_parser.diagnose_citation_extraction(paper.full_text)
    diag["paper_id"] = paper.id
    diag["title"] = paper.title
    return diag


@app.delete("/api/papers/{paper_id}")
def delete_paper(paper_id: int, db: Session = Depends(get_db)):
    paper = (
        db.query(Paper)
        .options(joinedload(Paper.citations))
        .filter(Paper.id == paper_id)
        .first()
    )
    if not paper:
        raise HTTPException(404, "論文が見つかりません")

    file_paths: set[Path] = set()
    if paper.file_path:
        file_paths.add(Path(paper.file_path))
    for citation in paper.citations:
        if citation.manual_file_path:
            file_paths.add(Path(citation.manual_file_path))

    db.delete(paper)
    db.commit()

    for path in file_paths:
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass

    return {"ok": True}


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")
