# One-off (2026-10-23): OTF is being generalised for the four domains, so Gemma's and Qwen's OTF runs are held.
# The old orchestrator was stopped while Gemma's RAG pass (run.py, PID given as -RagPid) kept running. This
# script waits for that pass to exit, then starts a new orchestrator for the non-OTF systems only: Gemma first
# (its RAG retries), then Qwen. Every action is logged to runs\logs\resume_after_reboot.log.
param([int]$RagPid)

$Root   = "C:\Users\aashraf\Desktop\Work\2026\MLSystem 2027\implementation-1"
$Python = "C:\Users\aashraf\AppData\Local\Python\pythoncore-3.14-64\python.exe"
$Log    = Join-Path $Root "runs\logs\resume_after_reboot.log"

function Write-Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $Log -Value $line -Encoding UTF8
}

Write-Log "hold: waiting for Gemma RAG pass (PID $RagPid) to exit"
Wait-Process -Id $RagPid -ErrorAction SilentlyContinue
Write-Log "hold: RAG pass exited; starting orchestrator without OTF"
Start-Process -FilePath $Python -WorkingDirectory $Root -ArgumentList @(
    "scripts\run_baselines.py", "--split", "e1",
    "--models", "gemma-4-31b-think", "qwen3.6-27b",
    "--systems", "full_context_text", "pageindex", "rag")
Write-Log "hold: orchestrator started (gemma-4-31b-think, qwen3.6-27b; full_context_text pageindex rag)"
