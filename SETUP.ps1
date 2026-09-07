# ProseCast - one-shot Windows setup.
#
# Run from the project root, in PowerShell:   .\SETUP.ps1
# Safe to re-run: every step checks before it acts.
#
# If Windows refuses to run it ("running scripts is disabled on this system"),
# allow local scripts once, for your account only:
#     Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#
# What it does, in order - the same steps as SETUP.sh, plus Piper's voices:
#   1. checks Python 3.11+ and ffmpeg, and prints the winget line for each
#   2. creates .venv
#   3. installs the Python dependencies, and piper-tts
#   4. downloads the six Piper voice files into this folder
#   5. downloads the spaCy English model and PROVES it loads
#   6. creates config.json from config.example.json if you don't have one
#   7. runs a silent end-to-end smoke test of the pipeline
#   8. writes start-prosecast.ps1 - the file you double-click from now on
# Nothing here needs a GPU.
#
# Tested by Tyler on Windows 11 (2026-09-06) as a sequence of manual steps:
# the winget installs, the venv, the three pip installs, four voice downloads,
# the config copy and the smoke test. The --isolated flag and the two new
# voices (hfc_female, jenny_dioco) are from this script and have not been run
# on Windows yet.

# Deliberately NOT 'Stop'. Under 'Stop', redirecting a native command's stderr
# (`2>$null`) raises NativeCommandError in Windows PowerShell 5.1, which would
# abort this script the first time `py -3.12` is simply not installed. Every
# step below checks $LASTEXITCODE for itself instead.
$ErrorActionPreference = 'Continue'
Set-Location -Path $PSScriptRoot

$script:Failed = $false
function Ok    { param($m) Write-Host "  [ok] $m"   -ForegroundColor Green }
function Warn  { param($m) Write-Host "  [!]  $m"   -ForegroundColor Yellow }
function Fail  { param($m) Write-Host "  [x]  $m"   -ForegroundColor Red; $script:Failed = $true }
function Die   { param($m) Write-Host "  [x]  $m"   -ForegroundColor Red; exit 1 }

# Piper resolves `<name>.onnx` from the folder it is started in, so the voices
# live beside this script. Keep in step with VoiceAssigner.PIPER_VOICES.
$PiperVoices = @(
  'en_US-lessac-medium',
  'en_US-ryan-medium',
  'en_GB-alan-medium',
  'en_US-kusal-medium',
  'en_US-hfc_female-medium',
  'en_GB-jenny_dioco-medium'
)

Write-Host ""
Write-Host "=== 1. Python and ffmpeg ==="

$py = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
  foreach ($v in @('3.12', '3.11', '3.13')) {
    & py "-$v" -c "import sys" 2>$null
    if ($LASTEXITCODE -eq 0) { $py = "-$v"; break }
  }
}
if (-not $py) {
  Write-Host ""
  Write-Host "  Python 3.11+ was not found. Install it, then close and reopen PowerShell:"
  Write-Host "      winget install -e --id Python.Python.3.12" -ForegroundColor Cyan
  Die "no suitable Python"
}
$pyver = (& py $py -c "import sys; print('%d.%d.%d' % sys.version_info[:3])")
Ok "python $pyver (py $py)"

if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
  Ok "ffmpeg: $((Get-Command ffmpeg).Source)"
} else {
  Warn "ffmpeg not found - REQUIRED for M4B export and voice-clip prep."
  Write-Host "      winget install -e --id Gyan.FFmpeg" -ForegroundColor Cyan
  Warn "then close and reopen PowerShell so the new PATH is picked up, and re-run this script."
}

Write-Host ""
Write-Host "=== 2. Virtual environment ==="
if (Test-Path ".venv\Scripts\python.exe") {
  Ok ".venv already exists"
} else {
  & py $py -m venv .venv
  if ($LASTEXITCODE -ne 0) { Die "could not create .venv" }
  Ok "created .venv"
}
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Write-Host ""
Write-Host "=== 3. Python dependencies ==="
# --isolated ignores machine-wide pip config. A leftover NVIDIA extra-index-url
# in pip.ini made every install on this laptop retry a dead host five times
# before falling back to PyPI; `pip config debug` shows which file has it.
& $venvPy -m pip install --isolated --quiet --upgrade pip
if ($LASTEXITCODE -ne 0) { Die "could not upgrade pip" }
& $venvPy -m pip install --isolated --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) { Die "requirements.txt failed to install" }
Ok "requirements.txt installed"

& $venvPy -m pip install --isolated --quiet piper-tts
if ($LASTEXITCODE -eq 0) { Ok "piper-tts installed" }
else { Fail "piper-tts failed to install - Piper is the Windows voice engine" }

Write-Host ""
Write-Host "=== 4. Piper voices (about 400 MB total) ==="
foreach ($v in $PiperVoices) {
  if (Test-Path "$v.onnx") {
    Ok "$v already here"
    continue
  }
  Write-Host "  downloading $v ..."
  & $venvPy -m piper.download_voices $v
  if ($LASTEXITCODE -eq 0 -and (Test-Path "$v.onnx")) { Ok $v }
  else { Fail "$v did not download - re-run this script, or: py -m piper.download_voices $v" }
}

Write-Host ""
Write-Host "=== 5. spaCy English model (for 'who is speaking') ==="
& $venvPy -c "import spacy; spacy.load('en_core_web_sm')" 2>$null
if ($LASTEXITCODE -eq 0) {
  Ok "en_core_web_sm already loads"
} else {
  & $venvPy -m spacy download en_core_web_sm | Out-Null
  & $venvPy -c "import spacy; spacy.load('en_core_web_sm')" 2>$null
  if ($LASTEXITCODE -eq 0) { Ok "en_core_web_sm downloaded and loads" }
  else { Fail "spaCy model downloaded but does not load - run: .venv\Scripts\python -m spacy download en_core_web_sm" }
}

Write-Host ""
Write-Host "=== 6. config.json ==="
if (Test-Path "config.json") {
  Ok "config.json exists (left untouched)"
} else {
  Copy-Item "config.example.json" "config.json"
  Ok "created config.json - no engine chosen yet, so the app opens its setup wizard on first run"
}

Write-Host ""
Write-Host "=== 7. Smoke test (silent audio, no network, ~10 s) ==="
& $venvPy main.py --sample --tts stub *> $null
if ($LASTEXITCODE -eq 0) { Ok "pipeline runs end to end" }
else { Fail "smoke test failed - run it by hand to see why: .venv\Scripts\python main.py --sample --tts stub" }

Write-Host ""
Write-Host "=== 8. start-prosecast.ps1 ==="
# PYTHONUTF8 is belt and braces: every text read and write in ProseCast names
# its encoding (tests/test_encoding_guard.py), so this is not load-bearing.
$launcher = @'
# Start ProseCast and open it in your browser. Double-click this file, or run
# it from PowerShell:   .\start-prosecast.ps1
#
# If Windows refuses ("running scripts is disabled on this system"), allow
# local scripts once, for your account only:
#     Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
Set-Location -Path $PSScriptRoot
$env:PYTHONUTF8 = "1"
# Open the browser a few seconds in, so it does not arrive before uvicorn is
# listening. uvicorn itself stays in the foreground: closing this window stops
# the server, which is what someone who double-clicked a file expects.
Start-Job { Start-Sleep -Seconds 3; Start-Process "http://localhost:8000" } | Out-Null
& ".\.venv\Scripts\python.exe" -m uvicorn server:app --port 8000
'@
Set-Content -Path "start-prosecast.ps1" -Value $launcher -Encoding UTF8
Ok "wrote start-prosecast.ps1"

Write-Host ""
if ($script:Failed) {
  Write-Host "=== Finished with problems - see the [x] lines above. ===" -ForegroundColor Red
  exit 1
}
Write-Host "=== Done. Start ProseCast: ===" -ForegroundColor Green
Write-Host "  .\start-prosecast.ps1" -ForegroundColor Cyan
Write-Host ""
Write-Host "  It opens http://localhost:8000 in your browser. The first run walks"
Write-Host "  you through four steps and ends by reading you the sample book."
