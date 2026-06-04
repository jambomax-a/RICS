#!/bin/bash

# RICS for Linux Setup Script
# This script installs dependencies and configures llama-cpp-python for CUDA/GPU acceleration.

echo "=========================================="
echo "   RICS (Reference Integrity Check System)"
echo "   Setup for Linux"
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

# 4. Install llama-cpp-python with CUDA support (for NVIDIA GPUs)
# Note: Requires CUDA Toolkit to be installed on the system.
echo "Attempting to install llama-cpp-python with CUDA support..."
CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python --force-reinstall --no-cache-dir

if [ $? -ne 0 ]; then
    echo "CUDA build failed. Falling back to CPU-only installation..."
    pip install llama-cpp-python --force-reinstall --no-cache-dir
fi

echo ""
echo "=========================================="
echo "   Setup Complete!"
echo "   To start the server, run:"
echo "   source .venv/bin/activate"
echo "   python -m uvicorn backend.main:app --host 0.0.0.0 --port 57283"
echo "=========================================="
