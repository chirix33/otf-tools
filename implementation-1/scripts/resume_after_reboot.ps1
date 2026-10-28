# Run at Windows logon (scheduled task "MLSys2027-ResumeRuns"): relaunch the unattended E1 jobs if a reboot
# killed them. Starts each job only if it is not already running and not already finished, so logging off and
# on again never creates duplicates. Every action is logged to runs\logs\resume_after_reboot.log.
#
# Remove the task when the experiments are done:
#   Unregister-ScheduledTask -TaskName "MLSys2027-ResumeRuns" -Confirm:$false

$Root   = "C:\Users\aashraf\Desktop\Work\2026\MLSystem 2027\implementation-1"
$Python = "C:\Users\aashraf\AppData\Local\Python\pythoncore-3.14-64\python.exe"
$Log    = Join-Path $Root "runs\logs\resume_after_reboot.log"

function Write-Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $Log -Value $line -Encoding UTF8
}

function Test-Running($pattern) {
    $procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*$pattern*" }
    return [bool]$procs
}

# 2026-10-26: hosted (OpenRouter) runs. A logon restarts the hosted runners unless runs\logs\HOSTED_RUNS_HALTED exists
# or a runner is already running; the runners skip finished jobs and resume answered questions.
if (Test-Path (Join-Path $Root "runs\logs\HOSTED_RUNS_HALTED")) {
    Write-Log "logon: hosted runs halted (runs\logs\HOSTED_RUNS_HALTED present), not started"
} elseif (Test-Running "run_hosted.py") {
    Write-Log "logon: hosted runner already running, not started"
} else {
    $out = & $Python (Join-Path $Root "scripts\repair_predictions.py") 2>&1 | Out-String
    Write-Log ("hosted repair: " + $out.Trim().Replace("`r`n", " | "))
    if (-not (Test-Running "net_watch.py")) {
        Start-Process -FilePath $Python -WorkingDirectory $Root -WindowStyle Hidden -ArgumentList @("-u", "scripts\net_watch.py")
    }
    $stamp = Get-Date -Format "yyyyMMdd_HHmm"
    # 2026-10-27 priorities (deadline): Qwen finishes its ablations; Gemma runs its main OTF (+ small leftovers) and
    # main PageIndex first; Gemma's E1 full context / RAG, E2 and ablations are left out (Crusoe throughput)
    $runners = @(
        @("qwen", @("-u", "scripts/run_hosted.py", "--phase", "dev", "main", "e2", "ablations", "--models", "or-qwen3.6-27b",
                    "--exclude", "pageindex", "--model-limits", "or-qwen3.6-27b=8,6")),
        @("gemma", @("-u", "scripts/run_hosted.py", "--phase", "main", "--models", "or-gemma-4-31b-think",
                     "--exclude", "pageindex", "--model-limits", "or-gemma-4-31b-think=6,4")),
        @("pi", @("-u", "scripts/run_hosted.py", "--phase", "main", "e2", "--systems", "pageindex", "--exclude", '"^e2_d01__or-gemma"',
                  "--model-limits", "or-gpt-oss-20b=2,1", "or-qwen3.6-27b=24,1", "or-gemma-4-31b-think=16,1"))
    )
    foreach ($r in $runners) {
        Start-Process -FilePath $Python -WorkingDirectory $Root -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $Root "runs\logs\hosted__runner_resume_$($r[0])_$stamp.out") `
            -RedirectStandardError (Join-Path $Root "runs\logs\hosted__runner_resume_$($r[0])_$stamp.err") -ArgumentList $r[1]
    }
    Write-Log "logon: hosted runners started (main + PageIndex)"
}

# 2026-10-25: the local GPU runs are halted (the work moves to OpenRouter). While this marker file exists, a logon
# restarts nothing else; delete it to resume the local jobs.
if (Test-Path (Join-Path $Root "runs\logs\LOCAL_RUNS_HALTED")) {
    Write-Log "logon: local runs halted (runs\logs\LOCAL_RUNS_HALTED present), nothing started"
    exit 0
}

Start-Sleep -Seconds 90            # give WSL and the GPU driver time to come up after logon
Write-Log "logon: checking E1 jobs"

# 1) E1 baseline orchestrator
$status = Join-Path $Root "runs\logs\e1__status.jsonl"
$allDone = (Test-Path $status) -and (Select-String -Path $status -Pattern '"event": "all_done"' -Quiet)
if ($allDone) {
    Write-Log "orchestrator: E1 already finished (all_done), not started"
} elseif (Test-Running "run_baselines.py") {
    Write-Log "orchestrator: already running, not started"
} else {
    $out = & $Python (Join-Path $Root "scripts\repair_predictions.py") 2>&1 | Out-String
    Write-Log ("repair: " + $out.Trim().Replace("`r`n", " | "))
    # 2026-10-23: OTF and otf_oracle are held while OTF is generalised for the four domains (see
    # docs/domains/otf_review.md); only the non-OTF systems run until the new OTF is frozen.
    Start-Process -FilePath $Python -WorkingDirectory $Root -ArgumentList @(
        "scripts\run_baselines.py", "--split", "e1",
        "--models", "gemma-4-31b-think", "qwen3.6-27b",
        "--systems", "full_context_text", "pageindex", "rag")
    Write-Log "orchestrator: started"
}

# 1b) OTF v3 for Qwen on E1, sharing the Qwen server with the orchestrator (2026-10-23, tag otf-v3)
$otfDone = (Test-Path $status) -and (Select-String -Path $status -Pattern '"event": "otf_alongside_done", "model": "qwen3.6-27b"' -Quiet)
if ($otfDone) {
    Write-Log "otf alongside (qwen): already finished, not started"
} elseif (Test-Running "run_otf_alongside.py") {
    Write-Log "otf alongside (qwen): already running, not started"
} else {
    Start-Process -FilePath $Python -WorkingDirectory $Root -ArgumentList @(
        "scripts\run_otf_alongside.py", "--split", "e1", "--model", "qwen3.6-27b")
    Write-Log "otf alongside (qwen): started"
}

# 1c) GPU queue after the E1 baselines (scripts\run_queue.py waits for the orchestrator, then runs its stages)
$qStatus = Join-Path $Root "runs\logs\queue__status.jsonl"
$qDone = (Test-Path $qStatus) -and (Select-String -Path $qStatus -Pattern '"event": "queue_done"' -Quiet)
if ($qDone) {
    Write-Log "queue: already finished, not started"
} elseif (Test-Running "run_queue.py") {
    Write-Log "queue: already running, not started"
} else {
    Start-Process -FilePath $Python -WorkingDirectory $Root -ArgumentList @("scripts\run_queue.py")
    Write-Log "queue: started (waits for the E1 orchestrator)"
}

# 2) OTF generation watcher (Gemma and Qwen tests run when their servers come up)
# 2026-10-23: held with OTF (it would test the old OTF on Qwen and share the GPU with Qwen's runs).
$models = @("gpt-oss-20b", "gemma-4-31b-think", "qwen3.6-27b")
$pending = $models | Where-Object { -not (Test-Path (Join-Path $Root "runs\logs\otf_generation__$_.txt")) }
if ($true) {
    Write-Log "watcher: held while OTF is generalised, not started"
} elseif (-not $pending) {
    Write-Log "watcher: all generation tests finished, not started"
} elseif (Test-Running "test_generation_when_up.py") {
    Write-Log "watcher: already running, not started"
} else {
    Start-Process -FilePath $Python -WorkingDirectory $Root -ArgumentList (@("scripts\test_generation_when_up.py") + $models)
    Write-Log ("watcher: started (pending: " + ($pending -join ", ") + ")")
}
