#!/bin/bash

# RICS for Mac (Apple Silicon) Setup Script
# This script installs dependencies and configures llama-cpp-python for Metal acceleration.

echo "=========================================="
echo "   RICS (Reference Integrity Check System)"
echo "   Setup for Mac (Apple Silicon)"
echo "=========================================="

# 1. Create virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

# 2. Upgrade pip
pip install --upgrade pip

# 3. Install common dependencies
echo "Installing general dependencies..."
pip install -r requirements.txt

# 4. Re-install llama-cpp-python with Metal support
# This is the "hard part" that requires specific flags for Mac
echo "Installing llama-cpp-python with Metal support (Apple Silicon)..."
CMAKE_ARGS="-DGGML_METAL=on" pip install llama-cpp-python --force-reinstall --no-cache-dir

echo ""
echo "=========================================="
echo "   Setup Complete!"
echo "   To start the server, run:"
echo "   source .venv/bin/activate"
echo "   python -m uvicorn backend.main:app --host 0.0.0.0 --port 57283"
echo "=========================================="
