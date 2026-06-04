# RICS (Reference Integrity Check System)

RICSは、学術論文の引用整合性を自動で検証するシステムです。論文内の引用箇所（本文）と、オンラインから取得したメタデータや要約を照らし合わせ、ローカルLLM（AI）またはルールベースの判定により、引用が学術的に妥当かどうかをチェックします。

## 主な機能

- **メタデータの自動取得**: Semantic ScholarやCrossrefから論文情報を自動で取得。
- **ローカルLLMによる精密判定**: `llama-cpp-python`を介して、GGUF形式のローカルLLM（Gemma 2等）を使用し、深い文脈理解に基づいた検証を行います。
- **CUDA/GPU加速**: NVIDIA GPUを活用した高速な推論をサポート。
- **参考文献セクションの自動解析**: 本文中の引用番号（[1], [2-5]等）と参考文献リストを自動的に紐付けます。
- **外部アクセス対応**: ローカルネットワーク経由での外部ブラウザからの利用が可能です。

## プロジェクト構造

```text
RICS/
├── backend/            # FastAPI バックエンド
│   ├── services/       # PDF解析、文献取得、LLM判定ロジック
│   └── models.py       # データベース定義
├── frontend/           # HTML/JS/CSS フロントエンド
├── models/             # (Git除外) ここに .gguf モデルを配置します
├── data/               # データベースとアップロードファイルの一時保存
├── RICS_Start.bat      # Windows用かんたん起動バッチ
├── setup_mac.sh        # Mac (Apple Silicon) 用セットアップスクリプト
└── run.ps1             # PowerShell エントリポイント
```

## インストール方法

詳細な手順やトラブルシューティングは [INSTALL.md](INSTALL.md) も参照してください。

### Windows (NVIDIA GPU 推奨)

1. **事前準備**:
   - Python 3.10以上
   - CUDA Toolkit 12.x (GPU加速を利用する場合)

2. **セットアップと起動**:
   - `RICS_Start.bat` をダブルクリックします。
   - ※ 初回起動時に必要なライブラリが自動的にインストールされます。

### Linux (NVIDIA GPU 対応)

1. セットアップスクリプトを実行:
   ```bash
   bash setup_linux.sh
   ```
2. サーバーを起動:
   ```bash
   source .venv/bin/activate
   python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
   ```

### Mac (Apple Silicon)

1. セットアップスクリプトを実行:
   ```bash
   bash setup_mac.sh
   ```
2. サーバーを起動:
   ```bash
   source .venv/bin/activate
   python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
   ```

## 設定 (.env)

| 変数名 | 説明 | デフォルト値 |
|----------|-------------|---------|
| `LLM_MODEL_PATH` | GGUFモデルへのパス | (空の場合は簡易判定) |
| `LLM_N_GPU_LAYERS` | GPUにオフロードするレイヤー数 (-1で全レイヤー) | `-1` |
| `LLM_N_CTX` | コンテキストウィンドウ（記憶可能量） | `8192` |

## ライセンス

MIT
