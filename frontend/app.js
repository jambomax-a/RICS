const API = "";

const verdictSymbol = {
  match: "◯",
  mismatch: "☓",
  unavailable: "△",
};

const dropZone = document.getElementById("dropZone");
const fileInput = document.getElementById("fileInput");
const browseBtn = document.getElementById("browseBtn");
const paperList = document.getElementById("paperList");
const detailPanel = document.getElementById("detailPanel");
const toast = document.getElementById("toast");
const busyOverlay = document.getElementById("busyOverlay");
const busyTitle = document.getElementById("busyTitle");
const busyMessage = document.getElementById("busyMessage");
const busyStep = document.getElementById("busyStep");
const busyProgressBar = document.getElementById("busyProgressBar");

let selectedPaperId = null;
let busy = false;
let busyStepTimer = null;
let busyProgressTimer = null;

const UPLOAD_STEPS = [
  { pct: 12, text: "ファイルを読み込んでいます…" },
  { pct: 28, text: "本文と参考文献を解析しています…" },
  { pct: 48, text: "引用番号ごとの該当箇所を抽出しています…" },
  { pct: 65, text: "引用文献をオンライン検索しています…" },
  { pct: 82, text: "内容・数値の整合性を照合しています…" },
  { pct: 92, text: "結果をデータベースに保存しています…" },
];

const RECHECK_STEPS = [
  { pct: 20, text: "アップロードした文献を読み込んでいます…" },
  { pct: 55, text: "本論文との内容を照合しています…" },
  { pct: 85, text: "判定結果を保存しています…" },
];

function isBusy() {
  return busy;
}

function setProgress(pct, indeterminate = false) {
  busyProgressBar.classList.toggle("indeterminate", indeterminate);
  if (!indeterminate) {
    busyProgressBar.style.width = `${Math.min(100, Math.max(0, pct))}%`;
  }
}

function applyStep(step) {
  if (!step) return;
  setProgress(step.pct);
  busyStep.textContent = step.text;
}

function startBusy({ title, message, steps, stepIntervalMs = 3500 }) {
  if (busy) return;
  busy = true;

  document.body.classList.add("is-busy");
  busyOverlay.hidden = false;
  busyOverlay.setAttribute("aria-hidden", "false");
  browseBtn.disabled = true;
  dropZone.classList.add("busy");

  busyTitle.textContent = title;
  busyMessage.textContent = message;
  busyStep.textContent = "";

  let stepIndex = 0;
  applyStep(steps[0]);
  setProgress(steps[0]?.pct ?? 5);

  busyStepTimer = setInterval(() => {
    stepIndex = Math.min(stepIndex + 1, steps.length - 1);
    applyStep(steps[stepIndex]);
  }, stepIntervalMs);

  busyProgressTimer = setInterval(() => {
    const current = parseFloat(busyProgressBar.style.width) || 0;
    if (current < 92) {
      setProgress(Math.min(92, current + 1.5));
    }
  }, 800);
}

function endBusy() {
  clearInterval(busyStepTimer);
  clearInterval(busyProgressTimer);
  busyStepTimer = null;
  busyProgressTimer = null;

  if (!busy) return;
  busy = false;

  setProgress(100);
  busyStep.textContent = "完了しました";

  // 状態変更は即座に行う（直後のrenderDetailなどで参照するため）
  document.body.classList.remove("is-busy");
  browseBtn.disabled = false;
  document.querySelectorAll("button, input").forEach((el) => {
    el.disabled = false;
  });
  dropZone.classList.remove("busy");

  setTimeout(() => {
    busyOverlay.hidden = true;
    busyOverlay.setAttribute("aria-hidden", "true");
    setProgress(0);
    busyProgressBar.classList.remove("indeterminate");
  }, 500);
}

function showToast(msg, isError = false) {
  toast.textContent = msg;
  toast.hidden = false;
  toast.classList.toggle("error", isError);
  setTimeout(() => {
    toast.hidden = true;
    toast.classList.remove("error");
  }, 6000);
}

function queueToast(msg, isError = false) {
  setTimeout(() => showToast(msg, isError), 450);
}

function parseErrorDetail(err) {
  if (!err || !err.detail) return null;
  if (typeof err.detail === "string") return err.detail;
  if (Array.isArray(err.detail)) {
    return err.detail.map((d) => d.msg || String(d)).join("; ");
  }
  return String(err.detail);
}

async function fetchJSON(url, options) {
  const res = await fetch(API + url, options);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err) || res.statusText || `HTTP ${res.status}`);
  }
  if (res.status === 204) return null;
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

async function loadPapers() {
  const papers = await fetchJSON("/api/papers");
  paperList.innerHTML = "";
  if (papers.length === 0) {
    const li = document.createElement("li");
    li.className = "empty-hint";
    li.textContent = "（まだ論文がありません）";
    paperList.appendChild(li);
    return;
  }
  papers.forEach((p) => {
    const li = document.createElement("li");
    li.className = "paper-item";
    if (p.id === selectedPaperId) li.classList.add("active");

    const title = document.createElement("span");
    title.className = "paper-title";
    title.textContent = p.title;
    title.title = `${p.filename} — 引用${p.citation_count}件`;

    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "btn-delete";
    delBtn.title = "この論文を削除";
    delBtn.setAttribute("aria-label", "削除");
    delBtn.textContent = "×";
    delBtn.disabled = busy;
    delBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      deletePaper(p.id, p.title);
    });

    li.appendChild(title);
    li.appendChild(delBtn);
    li.addEventListener("click", () => selectPaper(p.id));
    paperList.appendChild(li);
  });
}

const PLACEHOLDER_HTML =
  '<p class="placeholder">左の一覧から論文を選ぶか、ファイルをアップロードしてください。</p>';

async function editPaperTitle(id, currentTitle) {
  if (isBusy()) return;
  const next = prompt("論文タイトル（DBに保存されます）", currentTitle);
  if (next === null || next.trim() === "" || next.trim() === currentTitle) return;
  try {
    await fetchJSON(`/api/papers/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: next.trim() }),
    });
    await loadPapers();
    await selectPaper(id);
    showToast("タイトルを更新しました");
  } catch (e) {
    showToast("タイトル更新失敗: " + e.message, true);
  }
}

async function refreshPaperTitle(id) {
  if (isBusy()) return;
  try {
    await fetchJSON(`/api/papers/${id}/refresh-title`, { method: "POST" });
    await loadPapers();
    await selectPaper(id);
    showToast("タイトルを再抽出しました");
  } catch (e) {
    showToast("再抽出失敗: " + e.message, true);
  }
}

async function deletePaper(id, title) {
  if (isBusy()) return;
  const label = truncate(title, 60);
  if (!confirm(`「${label}」を削除しますか？\n登録データとアップロードしたファイルも削除されます。`)) {
    return;
  }
  try {
    await fetchJSON(`/api/papers/${id}`, { method: "DELETE" });
    if (selectedPaperId === id) {
      selectedPaperId = null;
      detailPanel.innerHTML = PLACEHOLDER_HTML;
    }
    await loadPapers();
    showToast("論文を削除しました");
  } catch (e) {
    showToast("削除失敗: " + e.message, true);
  }
}

async function selectPaper(id) {
  if (isBusy()) return;
  selectedPaperId = id;
  await loadPapers();
  const paper = await fetchJSON(`/api/papers/${id}`);
  renderDetail(paper);
}

function renderDetail(paper) {
  const counts = { match: 0, mismatch: 0, unavailable: 0 };
  paper.citations.forEach((c) => {
    counts[c.verdict] = (counts[c.verdict] || 0) + 1;
  });

  let html = `
    <div class="detail-header">
      <div>
        <h2>${escapeHtml(paper.title)}</h2>
        <p class="ref-meta">${escapeHtml(paper.filename)} · 引用 ${paper.citations.length} 件</p>
      </div>
      <div class="detail-actions">
        <button type="button" class="btn btn-secondary" id="editTitleBtn">タイトル編集</button>
        <button type="button" class="btn btn-secondary" id="refreshTitleBtn">タイトル再抽出</button>
        <button type="button" class="btn btn-danger" id="deletePaperBtn">削除</button>
      </div>
    </div>
    <div class="stats">
      <span class="match">◯ ${counts.match || 0}</span>
      <span class="mismatch">☓ ${counts.mismatch || 0}</span>
      <span class="unavail">△ ${counts.unavailable || 0}</span>
    </div>
  `;

  if (paper.citations.length === 0) {
    html += `<p class="placeholder">参考文献を抽出できませんでした。PDFの「References」セクションを確認してください。</p>`;
  }

  paper.citations.forEach((c) => {
    const sym = verdictSymbol[c.verdict] || "?";
    const link = c.source_url
      ? `<a href="${escapeAttr(c.source_url)}" target="_blank" rel="noopener">文献リンク</a>`
      : "";
    const manualBlock =
      `<div class="manual-upload">
            <label>手元の引用論文をアップロード（判定の修正・再判定）:
              <input type="file" data-citation-id="${c.id}" class="manual-file" accept=".pdf,.docx,.doc,.txt,.md" ${isBusy() ? "disabled" : ""} />
            </label>
            ${c.has_manual_upload ? "<span>（アップロード済みファイルを使用中）</span>" : ""}
          </div>`;

    html += `
      <article class="citation-card">
        <div class="citation-header">
          <span class="verdict ${c.verdict}">${sym}</span>
          <div>
            <strong>[${c.ref_number}]</strong>
            <p class="ref-meta">${escapeHtml(truncate(c.reference_text, 200))} ${link}</p>
            ${c.source_title ? `<p class="ref-meta">取得: ${escapeHtml(c.source_title)}</p>` : ""}
          </div>
        </div>
        <p><strong>判定理由:</strong> ${escapeHtml(c.reason)}</p>
        <div class="evidence">
          <div>
            <strong>本論文の該当箇所</strong>
            <blockquote>${escapeHtml(c.evidence_main || c.body_excerpt || "—")}</blockquote>
          </div>
          <div>
            <strong>引用文献側</strong>
            <blockquote>${escapeHtml(c.evidence_source || "—")}</blockquote>
          </div>
        </div>
        ${manualBlock}
      </article>
    `;
  });

  detailPanel.innerHTML = html;

  document.getElementById("deletePaperBtn")?.addEventListener("click", () => {
    deletePaper(paper.id, paper.title);
  });
  document.getElementById("editTitleBtn")?.addEventListener("click", () => {
    editPaperTitle(paper.id, paper.title);
  });
  document.getElementById("refreshTitleBtn")?.addEventListener("click", () => {
    refreshPaperTitle(paper.id);
  });

  detailPanel.querySelectorAll(".manual-file").forEach((input) => {
    input.addEventListener("change", () => onManualUpload(input));
  });
}

async function onManualUpload(input) {
  if (isBusy()) {
    input.value = "";
    return;
  }
  const file = input.files[0];
  if (!file) return;
  const id = input.dataset.citationId;
  const fd = new FormData();
  fd.append("file", file);

  startBusy({
    title: "引用文献を照合中",
    message: `「${file.name}」を解析しています`,
    steps: RECHECK_STEPS,
    stepIntervalMs: 2500,
  });

  try {
    await fetchJSON(`/api/citations/${id}/upload-manual`, { method: "POST", body: fd });
    endBusy();
    queueToast("再判定が完了しました");
    if (selectedPaperId) {
      const pid = selectedPaperId;
      setTimeout(() => selectPaper(pid), 450);
    }
  } catch (e) {
    endBusy();
    queueToast("エラー: " + e.message, true);
  }
  input.value = "";
}

async function uploadPaper(file) {
  if (isBusy()) return;

  const fd = new FormData();
  fd.append("file", file);

  startBusy({
    title: "論文を照合中",
    message: `「${file.name}」を処理しています`,
    steps: UPLOAD_STEPS,
    stepIntervalMs: 4000,
  });

  try {
    const paper = await fetchJSON("/api/papers/upload", { method: "POST", body: fd });
    endBusy();
    selectedPaperId = paper.id;
    await loadPapers();
    renderDetail(paper);
    queueToast(`登録完了: 引用 ${paper.citations.length} 件`);
  } catch (e) {
    endBusy();
    queueToast("アップロード失敗: " + e.message, true);
  }
}

browseBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  if (!isBusy()) fileInput.click();
});

dropZone.addEventListener("click", () => {
  if (!isBusy()) fileInput.click();
});

fileInput.addEventListener("change", () => {
  if (fileInput.files[0] && !isBusy()) uploadPaper(fileInput.files[0]);
  fileInput.value = "";
});

["dragenter", "dragover", "dragleave", "drop"].forEach((ev) => {
  dropZone.addEventListener(ev, (e) => {
    e.preventDefault();
    e.stopPropagation();
  });
});

dropZone.addEventListener("dragover", (e) => {
  if (isBusy()) return;
  dropZone.classList.add("dragover");
});

dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));

dropZone.addEventListener("drop", (e) => {
  dropZone.classList.remove("dragover");
  if (isBusy()) return;
  const file = e.dataTransfer.files[0];
  if (file) uploadPaper(file);
});

document.addEventListener(
  "keydown",
  (e) => {
    if (!isBusy()) return;
    if (e.key === "Tab" || e.key === "Enter" || e.key === " ") {
      const inOverlay = busyOverlay.contains(document.activeElement);
      if (!inOverlay) e.preventDefault();
    }
  },
  true
);

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(s) {
  return escapeHtml(s).replace(/'/g, "&#39;");
}

function truncate(s, n) {
  return s.length > n ? s.slice(0, n) + "…" : s;
}

loadPapers().catch((e) => showToast("一覧取得失敗: " + e.message, true));
