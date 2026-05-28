# scripts/smoke.ps1
#
# Production-readiness smoke test for Alpha Engine.
#
# Run from repo root:
#     pwsh -File scripts/smoke.ps1
#
# What it does (each stage gates the next):
#   1. Frontend type-check     (tsc --noEmit)
#   2. Frontend production build (next build)
#         catches issues tsc misses: SSR errors, missing deps,
#         module-resolution problems, Tailwind config breaks
#   3. Backend py_compile      (every .py under backend/)
#   4. Backend module imports  (every quant/data/agents/db module)
#   5. Backend boot smoke      (FastAPI starts, /api/health 200,
#                                /api/system/info 200,
#                                /api/me/profile 401 unauth,
#                                user_profiles table created)
#
# Exits non-zero on the first failure. Designed to run in ~2 minutes.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$start = Get-Date

function Section($name) {
    Write-Host ""
    Write-Host ("=" * 72) -ForegroundColor DarkGray
    Write-Host "  $name" -ForegroundColor Cyan
    Write-Host ("=" * 72) -ForegroundColor DarkGray
}

function Pass($name) {
    Write-Host "  [PASS] $name" -ForegroundColor Green
}

function Fail($name, $detail) {
    Write-Host "  [FAIL] $name" -ForegroundColor Red
    if ($detail) { Write-Host "         $detail" -ForegroundColor DarkRed }
    exit 1
}

# ───── 1. Frontend tsc ─────────────────────────────────────────────────
Section "1/5 Frontend type-check (tsc --noEmit)"
Push-Location (Join-Path $root "frontend")
try {
    $out = & npx --no-install tsc --noEmit 2>&1
    if ($LASTEXITCODE -ne 0) {
        Fail "tsc" ($out -join "`n")
    }
    Pass "tsc clean"
}
finally {
    Pop-Location
}

# ───── 2. Frontend Next.js build ───────────────────────────────────────
Section "2/5 Frontend production build (next build)"
Push-Location (Join-Path $root "frontend")
try {
    # Capture output for failure case but stream to console for live feedback
    $env:NEXT_TELEMETRY_DISABLED = "1"
    $buildOut = & npx --no-install next build 2>&1 | Tee-Object -Variable tee
    if ($LASTEXITCODE -ne 0) {
        Fail "next build" ($buildOut | Select-Object -Last 30 | Out-String)
    }
    Pass "next build succeeded"
}
finally {
    Pop-Location
}

# ───── 3. Backend py_compile ───────────────────────────────────────────
Section "3/5 Backend py_compile (all .py files)"
Push-Location (Join-Path $root "backend")
try {
    $pyFiles = Get-ChildItem -Path . -Recurse -Filter "*.py" |
        Where-Object { $_.FullName -notmatch "\\__pycache__\\" } |
        Select-Object -ExpandProperty FullName
    $compileOut = & python -m py_compile @pyFiles 2>&1
    if ($LASTEXITCODE -ne 0) {
        Fail "py_compile" ($compileOut -join "`n")
    }
    Pass "py_compile clean across $($pyFiles.Count) files"
}
finally {
    Pop-Location
}

# Detect whether the active Python has backend deps installed. The full
# dep set lives in the Railway Docker image; locally we typically only have
# py_compile available unless a venv is activated. If deps are missing we
# skip the runtime stages (4 + 5) but still surface a clear note so the
# operator knows what didn't run.
Section "Backend runtime checks (optional)"
$hasBackendDeps = $false
try {
    python -c "import fastapi, sqlalchemy" 2>$null
    if ($LASTEXITCODE -eq 0) { $hasBackendDeps = $true }
} catch { }

if (-not $hasBackendDeps) {
    Write-Host "  [SKIP] Backend runtime checks (4 + 5)" -ForegroundColor Yellow
    Write-Host "         Active Python has no backend deps installed." -ForegroundColor DarkYellow
    Write-Host "         These checks run on Railway via the Docker image; locally," -ForegroundColor DarkYellow
    Write-Host "         activate a venv with: pip install -r backend/requirements.txt" -ForegroundColor DarkYellow
    Write-Host "         to enable them." -ForegroundColor DarkYellow
} else {
    # ───── 4. Backend module imports ───────────────────────────────────────
    Section "4/5 Backend module imports"
    Push-Location (Join-Path $root "backend")
    try {
        $importCheck = @"
import sys
sys.path.insert(0, '.')
errors = []
for mod in (
    'config',
    'db.models', 'db.database', 'db.repositories',
    'data.fred_client', 'data.market_client', 'data.news_client',
    'data.sec_client', 'data.alpha_vantage_client',
    'data.smart_money', 'data.screens', 'data.events', 'data.sector_map',
    'quant.limits', 'quant.risk', 'quant.performance', 'quant.regime',
    'quant.backtester', 'quant.factors', 'quant.signal_validation',
    'quant.optimizer', 'quant.options_analytics', 'quant.computations',
    'quant.stress', 'quant.pairs', 'quant.curve',
    'agents.base_agent', 'agents.query_interpreter', 'agents.research_analyst',
    'agents.risk_manager', 'agents.portfolio_strategist', 'agents.cio_synthesizer',
    'agents.orchestrator', 'agents.scorer', 'agents.universe',
    'infra.cache', 'infra.lineage',
):
    try:
        __import__(mod)
    except Exception as e:
        errors.append(f'{mod}: {e}')
if errors:
    print('IMPORT ERRORS:')
    for e in errors: print('  ' + e)
    sys.exit(1)
print('All modules import cleanly.')
"@
        $importOut = python -c $importCheck 2>&1
        if ($LASTEXITCODE -ne 0) {
            Fail "module imports" ($importOut -join "`n")
        }
        Pass ($importOut -join " ")
    }
    finally {
        Pop-Location
    }
}

if (-not $hasBackendDeps) {
    # Stages 4 + 5 already skipped above; jump straight to summary.
} else {
# ───── 5. Backend boot + endpoint smoke ────────────────────────────────
Section "5/5 Backend boot + endpoint smoke"
Push-Location (Join-Path $root "backend")
try {
    # Use a sqlite file so the test is self-contained and does not require Postgres
    $env:DATABASE_URL = "sqlite+aiosqlite:///./smoke_test.db"
    # Clear any prior test db
    if (Test-Path "smoke_test.db") { Remove-Item "smoke_test.db" -Force }

    Write-Host "  Starting uvicorn..." -ForegroundColor DarkGray
    $proc = Start-Process -FilePath "python" `
        -ArgumentList "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8765", "--log-level", "warning" `
        -PassThru -WindowStyle Hidden -RedirectStandardOutput "smoke_uvicorn.log" -RedirectStandardError "smoke_uvicorn.err"

    try {
        # Wait up to 30s for boot
        $ready = $false
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 1
            try {
                $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8765/api/health" -UseBasicParsing -TimeoutSec 2
                if ($resp.StatusCode -eq 200) { $ready = $true; break }
            } catch { }
        }
        if (-not $ready) {
            $log = if (Test-Path "smoke_uvicorn.err") { Get-Content "smoke_uvicorn.err" -Tail 30 } else { "(no error log)" }
            Fail "uvicorn boot" ($log -join "`n")
        }
        Pass "uvicorn booted in <30s"

        # /api/health
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8765/api/health" -UseBasicParsing
        if ($resp.StatusCode -ne 200) { Fail "/api/health" "Status $($resp.StatusCode)" }
        Pass "/api/health 200"

        # /api/system/info
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8765/api/system/info" -UseBasicParsing -TimeoutSec 5
            if ($resp.StatusCode -ne 200) { Fail "/api/system/info" "Status $($resp.StatusCode)" }
            Pass "/api/system/info 200"
        } catch {
            Fail "/api/system/info" $_.Exception.Message
        }

        # /api/me/profile (unauth) — should 401
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8765/api/me/profile" -UseBasicParsing -TimeoutSec 5
            Fail "/api/me/profile unauth" "Expected 401 but got $($resp.StatusCode)"
        } catch {
            $status = $_.Exception.Response.StatusCode.value__
            if ($status -eq 401 -or $status -eq 403) {
                Pass "/api/me/profile unauth -> $status (correctly rejected)"
            } else {
                Fail "/api/me/profile unauth" "Expected 401/403, got $status"
            }
        }

        # /api/auth/me (unauth) — should 401
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8765/api/auth/me" -UseBasicParsing -TimeoutSec 5
            Fail "/api/auth/me unauth" "Expected 401 but got $($resp.StatusCode)"
        } catch {
            $status = $_.Exception.Response.StatusCode.value__
            if ($status -eq 401 -or $status -eq 403) {
                Pass "/api/auth/me unauth -> $status (correctly rejected)"
            } else {
                Fail "/api/auth/me unauth" "Expected 401/403, got $status"
            }
        }

        # DB schema check — user_profiles table exists
        $schemaCheck = python -c "import sqlite3; conn = sqlite3.connect('smoke_test.db'); cur = conn.cursor(); cur.execute(`"SELECT name FROM sqlite_master WHERE type='table' AND name='user_profiles'`"); r = cur.fetchone(); print('exists' if r else 'missing'); conn.close()" 2>&1
        if ($schemaCheck -notmatch "exists") {
            Fail "user_profiles table" "Schema check returned: $schemaCheck"
        }
        Pass "user_profiles table created"

        # DB schema check — intelligence_memos thread columns exist
        $columnsCheck = python -c "import sqlite3; conn = sqlite3.connect('smoke_test.db'); cur = conn.cursor(); cur.execute(`"PRAGMA table_info(intelligence_memos)`"); cols = [r[1] for r in cur.fetchall()]; required = {'thread_id', 'parent_memo_id', 'sequence_in_thread', 'lineage', 'query_class'}; missing = required - set(cols); print('ok' if not missing else f'missing: {missing}'); conn.close()" 2>&1
        if ($columnsCheck -notmatch "^ok") {
            Fail "intelligence_memos schema" $columnsCheck
        }
        Pass "intelligence_memos has thread + lineage columns"
    }
    finally {
        if ($proc -and -not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
        Remove-Item "smoke_test.db" -Force -ErrorAction SilentlyContinue
        Remove-Item "smoke_uvicorn.log" -Force -ErrorAction SilentlyContinue
        Remove-Item "smoke_uvicorn.err" -Force -ErrorAction SilentlyContinue
        Remove-Item "alphaengine.db" -Force -ErrorAction SilentlyContinue
    }
}
finally {
    Pop-Location
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
}
}  # end if $hasBackendDeps

# ───── Summary ─────────────────────────────────────────────────────────
$elapsed = (Get-Date) - $start
Write-Host ""
Write-Host ("=" * 72) -ForegroundColor DarkGreen
Write-Host "  ALL SMOKE TESTS PASSED" -ForegroundColor Green
Write-Host "  Elapsed: $($elapsed.ToString('mm\:ss'))" -ForegroundColor DarkGray
Write-Host ("=" * 72) -ForegroundColor DarkGreen
