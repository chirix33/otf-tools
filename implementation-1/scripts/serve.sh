#!/usr/bin/env bash
# Start the vLLM server for one model (run inside WSL). Flags are frozen here; see SPEC.md sec. 1-2.
#   bash scripts/serve.sh gpt-oss-20b
#   bash scripts/serve.sh qwen3.6-27b
# Served on http://localhost:8000/v1 (reachable from Windows through WSL localhost forwarding).
set -euo pipefail
source ~/venvs/vllm/bin/activate

# TRITON_ATTN for every model: FlashInfer would JIT-compile kernels for sm_120 and needs nvcc, which WSL lacks
COMMON=(--port 8000 --max-model-len 131072 --enable-prompt-tokens-details --enable-auto-tool-choice
        --seed 0 --attention-backend TRITON_ATTN
        --no-enable-flashinfer-autotune)   # autotuning made Gemma's startup exceed 30 min (2026-10-22)

case "${1:?model alias}" in
  gpt-oss-20b)
    exec vllm serve openai/gpt-oss-20b "${COMMON[@]}" \
      --gpu-memory-utilization 0.90 \
      --tool-call-parser openai --reasoning-parser openai_gptoss ;;
  qwen3.6-27b)
    exec vllm serve nvidia/Qwen3.6-27B-NVFP4 "${COMMON[@]}" \
      --quantization modelopt --gpu-memory-utilization 0.92 --max-num-seqs 8 \
      --kv-cache-dtype bfloat16 --prefix-cache-retention-interval 0 \
      --limit-mm-per-prompt '{"image": 0, "video": 0}' \
      --tool-call-parser qwen3_coder --reasoning-parser qwen3 ;;
  gemma-4-31b|gemma-4-31b-think|gemma-4-31b-nothink)   # one server; thinking is a per-request switch
    exec vllm serve RedHatAI/gemma-4-31B-it-NVFP4 "${COMMON[@]}" \
      --kv-cache-dtype fp8 --gpu-memory-utilization 0.93 --max-num-seqs 8 \
      --limit-mm-per-prompt '{"image": 0, "audio": 0, "video": 0}' \
      --tool-call-parser gemma4 --reasoning-parser gemma4 ;;
  *) echo "unknown model alias: $1" >&2; exit 2 ;;
esac
