import json
import re
import os
import sys
import threading
import gc
from backend.config import settings
from backend.models import Verdict

"""
Verifier Service (検証サービス)
ローカルLLM (llama-cpp-python) を使用して、引用の整合性を意味的に判定します。
一定時間（5分）使われないと自動的にVRAMを解放するエコモジュールです。
"""

_llm = None
_last_used_time = 0
_lock = threading.Lock()
_unload_timer = None


def _unload_model():
    """モデルをVRAMから解放します。"""
    global _llm, _unload_timer
    with _lock:
        if _llm is not None:
            print("\n" + "💤" * 15)
            print("IDLE DETECTED: UNLOADING MODEL FROM VRAM...")
            print("💤" * 15 + "\n")
            # llama-cpp-pythonのインスタンスを削除
            del _llm
            _llm = None
        _unload_timer = None
        # ガベージコレクションを促す
        gc.collect()


def _reset_unload_timer():
    """解放タイマーをリセット（延長）します。"""
    global _unload_timer
    with _lock:
        if _unload_timer is not None:
            _unload_timer.cancel()
        
        # 300秒（5分）間アクセスがなければアンロード
        _unload_timer = threading.Timer(300.0, _unload_model)
        _unload_timer.daemon = True
        _unload_timer.start()


def _get_llm():
    global _llm
    # ロード済みならタイマーを回して返す
    if _llm is not None:
        _reset_unload_timer()
        return _llm
    
    # ロードが必要な場合
    if not settings.llm_model_path:
        return None

    # Windows で CUDA DLL を見つけられるようにパスを追加
    if sys.platform == "win32":
        # 1. Pip でインストールした NVIDIA パッケージの DLL を優先
        base_venv = os.path.join(settings.base_dir, ".venv", "Lib", "site-packages", "nvidia")
        nvidia_bins = [
            os.path.join(base_venv, "cuda_runtime", "bin"),
            os.path.join(base_venv, "cublas", "bin"),
            os.path.join(base_venv, "cudnn", "bin"),
            os.path.join(base_venv, "cuda_nvrtc", "bin"),
            os.path.join(base_venv, "curand", "bin"),
        ]
        # 2. システムの CUDA パス
        cuda_paths = [
            os.environ.get("CUDA_PATH"),
            r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.3",
            r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2",
            r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.4",
        ]
        
        all_paths = nvidia_bins + cuda_paths
        for p in all_paths:
            if p and os.path.exists(p) and any(f.endswith(".dll") for f in os.listdir(p)):
                print(f"DEBUG: Adding DLL directory: {p}")
                try:
                    os.add_dll_directory(p)
                    # PATHにも追加（一部の依存関係解決のため）
                    os.environ["PATH"] = p + os.pathsep + os.environ["PATH"]
                except Exception as e:
                    print(f"DEBUG: Failed to add DLL directory {p}: {e}")

    from llama_cpp import Llama

    print("\n" + "★"*30)
    print("🚀 LOCAL LLM (Gemma) LOADING...")
    print("★"*30)
    
    try:
        _llm = Llama(
            model_path=settings.llm_model_path,
            n_ctx=settings.llm_n_ctx,
            n_gpu_layers=settings.llm_n_gpu_layers,
            verbose=False,
        )
        print("\n" + "🟢" * 20)
        print("✅ LOCAL LLM IS READY (GPU/CPU)")
        print("🟢" * 20 + "\n")
        # 正常にロードされたらタイマー起動
        _reset_unload_timer()
    except Exception as e:
        print("\n" + "❌" * 20)
        print(f"FAILED TO LOAD LLM: {e}")
        print("❌" * 20 + "\n")
        _llm = None

    return _llm


VERDICT_PROMPT = """あなたは学術論文の引用整合性を審査する、学識豊かな専門家アシスタントです。
単なる「言葉の一致」ではなく、著者が**なぜその文献を引用したのか（引用の意図）**を深く読み取り、学術的に妥当であれば積極的に肯定判定（match）を行ってください。

判定の重要指針:
1. 【引用意図を汲む】:
   引用は必ずしも「全く同じ結果」である必要はありません。以下のようなケースはすべて「match（◯）」です：
   - 背景説明: 一般論や定義として引用している場合。
   - 比較・対照: 「他種（犬や人）ではこうだったが、本研究（馬）ではどうか」という文脈で他種の論文を引用している場合。
   - 基礎理論: 分子生物学や統計手法、メカニズムの共通性を根拠にしている場合。
   - 先行研究の紹介: 過去の知見として、たとえ本論文と異なる視点であっても正しく言及している場合。
   - **【タイトルのみの判断】**: 要約や本文が取得できなくても、**論文のタイトルが本論文の主張内容と明らかに合致している場合**（例：利尿剤の話をしていて、タイトルに利尿剤の名前がある）は、積極的に「match」と判定してください。

2. 【種の違いは「推奨される引用」】:
   馬の論文で、犬、マウス、ヒト、あるいは一般的な哺乳類の研究を引用することは、比較生物学において極めて一般的かつ正当な行為です。
   「対象動物が違う」という理由だけでリジェクト（mismatch）しないでください。むしろ「比較対象として適切に引用されている」と評価してください。

3. 「mismatch（☓）」とするのは、以下の明白な**「嘘・間違い」**のみです:
   - 引用文献が「効果なし」と結論しているのに、本論文が「効果ありの根拠」として歪曲して引用している。
   - 数値や期間、成分名が事実として明らかに異なっている。
   - 著者が「これは馬の研究である」と明記しているのに、実際の付随文献が他種である（著者の誤認）。

4. 「unavailable（△）」とするケース:
   - **論文タイトルも要約も一切不明**で、何を根拠に引用しているか100%推測不可能な場合。
   - 本論文側の抜粋（body）が短すぎて、どの文章に対して引用されているか特定できない場合。

【注意事項】: 本論文の抜粋内に複数の著者名（例：Ganiats et al.）が出てきても、**今回審査すべきはメタデータに記載された論文（{authors} 等）です。** 混乱しないよう注意してください。

出力は必ず次のJSONのみ（説明文不要）:
{{
  "verdict": "match" | "mismatch" | "unavailable",
  "reason": "学術的背景を踏まえた判定理由。他種引用の場合は、なぜそれが妥当かを肯定的に説明してください。",
  "evidence_main": "本論文の主張点（要約）",
  "evidence_source": "引用文献の知見（要約）"
}}

verdictの定義:
- match: 引用の意図が正当であり、学術的に整合している（◯）
- mismatch: 内容の歪曲、事実の捏造、致命的な誤引用（☓）
- unavailable: 本文不足により、推測すら困難（△）

【本論文の該当箇所】
{body}

【引用文献メタデータ】
タイトル: {title}
著者等: {authors}
年: {year}

【引用文献の本文・要約】
{source}

【参考文献リストの記載】
{reference}
"""


def verify_citation(
    body_excerpt: str,
    reference_text: str,
    source_meta: dict,
    manual_text: str | None = None,
) -> dict:
    source_body = manual_text or source_meta.get("abstract") or ""
    title = source_meta.get("title") or ""
    authors = source_meta.get("authors") or ""
    year = source_meta.get("year") or ""

    if not body_excerpt.strip():
        return _result(
            Verdict.UNAVAILABLE,
            "本論文内に該当引用の記述を検出できませんでした。",
            "",
            "",
        )

    llm = _get_llm()
    
    if not source_body.strip() and not title:
        return _result(
            Verdict.UNAVAILABLE,
            "引用文献をオンラインで取得できませんでした。手元のPDF等をアップロードして再判定してください。",
            body_excerpt[:400],
            "",
        )

    if llm is None:
        return _heuristic_verify(body_excerpt, source_body, reference_text)

    # LLMが動く場合は、コンソールに一行だけログ
    print(f"  └─ [LLM判定中...] Reference [{source_meta.get('ref_number', '?')}]")

    prompt = VERDICT_PROMPT.format(
        body=body_excerpt[:4000],
        title=title,
        authors=authors,
        year=year,
        source=source_body[:4000] or "(本文・要約なし)",
        reference=reference_text[:1000],
    )
    print(f"DEBUG: Processing reference index {source_meta.get('ref_number', '?')} with LLM...")
    try:
        out = llm.create_chat_completion(
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
        )
        text = out["choices"][0]["message"]["content"]
        parsed = _parse_json_response(text)
        if parsed:
            return parsed
    except Exception as exc:
        fallback = _heuristic_verify(body_excerpt, source_body, reference_text)
        fallback["reason"] += f"（LLMエラー: {exc}）"
        return fallback

    return _heuristic_verify(body_excerpt, source_body, reference_text)


def _heuristic_verify(body: str, source: str, reference: str) -> dict:
    """LLM未設定時の簡易キーワード・数値一致。"""
    body_nums = set(re.findall(r"\b\d+(?:\.\d+)?%?\b", body))
    src_nums = set(re.findall(r"\b\d+(?:\.\d+)?%?\b", source))
    overlap_nums = body_nums & src_nums if src_nums else set()

    body_words = _keywords(body)
    src_words = _keywords(source + " " + reference)
    overlap_words = body_words & src_words

    if not source.strip():
        return _result(
            Verdict.UNAVAILABLE,
            "引用文献の本文がなく簡易判定のみ。手動アップロードを推奨します。",
            body[:300],
            "",
        )

    score = len(overlap_words) + (2 * len(overlap_nums))
    if score >= 4 or (overlap_nums and len(overlap_words) >= 2):
        return _result(
            Verdict.MATCH,
            f"簡易判定: 共通キーワード{len(overlap_words)}、数値一致{len(overlap_nums)}。ローカルLLM設定で精査推奨。",
            _snippet(body),
            _snippet(source),
        )
    if overlap_words or overlap_nums:
        return _result(
            Verdict.MISMATCH,
            "簡易判定: 一致が弱く、内容の食い違いの可能性。ローカルLLMで再確認してください。",
            _snippet(body),
            _snippet(source),
        )
    return _result(
        Verdict.MISMATCH,
        "簡易判定: 本論文と引用文献要約の対応が見つかりませんでした。",
        _snippet(body),
        _snippet(source),
    )


def _keywords(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z]{4,}|[一-龯ぁ-んァ-ン]{2,8}", text.lower())
    stop = {"that", "this", "with", "from", "have", "were", "which", "their", "study", "results"}
    return {w for w in words if w not in stop}


def _snippet(text: str, n: int = 280) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    return t[:n] + ("…" if len(t) > n else "")


def _parse_json_response(text: str) -> dict | None:
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    verdict = data.get("verdict", "unavailable")
    if verdict not in {v.value for v in Verdict}:
        verdict = Verdict.UNAVAILABLE.value
    return {
        "verdict": verdict,
        "reason": str(data.get("reason", ""))[:2000],
        "evidence_main": str(data.get("evidence_main", ""))[:2000],
        "evidence_source": str(data.get("evidence_source", ""))[:2000],
    }


def _result(verdict: Verdict, reason: str, em: str, es: str) -> dict:
    return {
        "verdict": verdict.value,
        "reason": reason,
        "evidence_main": em,
        "evidence_source": es,
    }
