# 詳細インストールガイド (Detailed Installation Guide)

RICSのインストール、特にローカルLLM（AI）を動かすための `llama-cpp-python` のセットアップに関する詳細ガイドです。

## 1. 基本ライブラリのインストール
まず、共通で使用するライブラリをインストールします。
```powershell
pip install -r requirements.txt
```

## 2. llama-cpp-python のセットアップ
このライブラリは、使用するハードウェア（GPUの有無）によってインストール方法が異なります。

### Windows (NVIDIA GPU / CUDA を使う場合)
GPU加速を有効にするには、あらかじめ [CUDA Toolkit](https://developer.nvidia.com/cuda-downloads) をインストールしておく必要があります。
```powershell
$env:CMAKE_ARGS="-DGGML_CUDA=on"
pip install llama-cpp-python --force-reinstall --no-cache-dir
```

### Windows (CPUのみ / GPUなしの場合)
```powershell
pip install llama-cpp-python --no-cache-dir
```

### Mac (Apple Silicon / M1, M2, M3 等)
Metal加速を有効にするために以下のフラグを指定します。
```bash
CMAKE_ARGS="-DGGML_METAL=on" pip install llama-cpp-python --force-reinstall --no-cache-dir
```

### Linux (CUDA対応)
```bash
CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python --force-reinstall --no-cache-dir
```

## 3. トラブルシューティング
- **ビルドエラーが発生する場合**: Windowsでは [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) (C++によるデスクトップ開発) がインストールされているか確認してください。
- **dll missing エラー**: `verifier.py` 内で自動的にCUDAのパスを探すようにしていますが、手動で `CUDA_PATH` 環境変数を設定すると解決する場合があります。
- **モデルの読み込み失敗**: 使用する `.gguf` モデルが破損していないか、パスが正しいかを確認してください。
