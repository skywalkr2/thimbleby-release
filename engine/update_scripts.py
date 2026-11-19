"""The small program outside the app that hands the app over to its new version (design 11.7: an update is all or
nothing).

A running app cannot replace itself, so when the update is downloaded, checked and ready, the app writes one of these
scripts, starts it detached and ends. The script waits for the app to be gone, puts the new version in its place with
the old one kept beside it, opens the new version and waits for it to say it is running. If any step fails, or the new
version does not answer in time, it puts the old version back, writes why, and opens the old version, which shows the
failed-update screen. The script writes the outcome to the result file in the form `engine.app_update` reads:
`{"status":"failed","reason":<kind>,"restore":<bool>,"from":<version>}`; the new version writes `"status":"ok"` itself
once it is running, with the id of this attempt, and the script takes no other answer for it. A version that is not
the one expected writes `"status":"wrong"` with that id, and the script puts the old version back at once.

What the app checked is checked again here, just before it is used: on Windows the setup program's SHA-256, with the
file held open against changes while it runs; on the Mac every file and link of the new app against the list the app
made from the disk image. Something else in their place is never run or put in place. On the Mac the new version is
stopped by its own program's path, compared as text and never read as a pattern, and the old version is put back
only once it has gone.

The Mac script is `sh` and the Windows one PowerShell: both ship with the system, so nothing is installed for this.
Every value is put in as a quoted literal here, never built from other text by the script.
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Hand:
    """What a hand-over needs, all as plain values."""

    pid: int
    #: The installed program: the Mac app bundle, or the folder the Windows setup installs into.
    app: str
    #: Where the installed program waits while the new one is in place.
    old: str
    #: Mac: the new app bundle, already beside the installed one. Windows: the downloaded setup program.
    new: str
    result: str
    log: str
    #: The command that opens the program at `app` (the Mac `open` with its arguments; unused on Windows).
    launch: Sequence[str]
    from_version: str
    close_wait: int
    answer_wait: int
    install_wait: int = 1800
    #: Windows only: the setup's own log, kept for the details.
    setup_log: str = ""
    #: The id of this attempt (letters and digits): the only answer taken is one that carries it.
    attempt: str = ""
    #: Windows: the setup program's SHA-256, checked again just before it runs.
    sha256: str = ""
    #: Mac: the file of the new app's checksums (`shasum -c` lines from the app's folder), how many files it has, and
    #: the SHA-256 of its links' list; the new app is checked against them just before the swap.
    sums: str = ""
    files: int = 0
    links: str = ""


def _sh(value: object) -> str:
    return shlex.quote(str(value))


def _ps(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _hex(value: str, size: int | None, what: str) -> str:
    """A value that must be plain hexadecimal text (of `size` characters when given), as it goes into a script."""
    text = str(value).lower()
    if not text or any(c not in "0123456789abcdef" for c in text) or (size is not None and len(text) != size):
        raise ValueError(f"the hand-over needs {what}")
    return text


SH_NAME = "hand-over.sh"
PS_NAME = "hand-over.ps1"

_SH = """#!/bin/sh
PID={pid}
APP={app}
OLD={old}
NEW={new}
FAILED={failed}
RESULT={result}
LOG={log}
FROM={from_version}
CLOSE_WAIT={close_wait}
ANSWER_WAIT={answer_wait}
ATTEMPT={attempt}
SUMS={sums}
FILES={files}
LINKS={links}

say() {{ printf '%s %s\\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$LOG"; }}
launch() {{ {launch} >> "$LOG" 2>&1; }}
result() {{
  printf '{{"status":"%s","reason":"%s","restore":%s,"from":"%s"}}' "$1" "$2" "$3" "$FROM" > "$RESULT.tmp" \\
    && mv "$RESULT.tmp" "$RESULT"
}}
answered() {{
  [ -f "$RESULT" ] && grep -F -q -- "\\"attempt\\":\\"$ATTEMPT\\"" "$RESULT" && grep -F -q -- "$1" "$RESULT"
}}
# The new app is exactly what the app checked: no link in its place, the same number of files, the same links, and
# every file's SHA-256.
new_is_checked() {{
  [ -f "$SUMS" ] && [ -d "$NEW" ] && [ ! -L "$NEW" ] || return 1
  (
    cd "$NEW" || exit 1
    [ "$(find . -type f | wc -l | tr -d ' ')" = "$FILES" ] || exit 1
    found=$(find . -type l | LC_ALL=C sort \\
      | while IFS= read -r l; do printf '%s\\n%s\\n' "$l" "$(readlink "$l")"; done \\
      | shasum -a 256 | cut -d ' ' -f 1)
    [ "$found" = "$LINKS" ] || exit 1
    shasum -a 256 -c "$SUMS" > /dev/null 2>&1 || exit 1
  )
}}
# The processes whose program is inside the installed app: each one's path is compared as text, never as a pattern.
new_pids() {{
  ps -axo pid=,comm= 2>/dev/null | while read -r p path; do
    case "$path" in "$APP/Contents/MacOS/"*) printf '%s\\n' "$p" ;; esac
  done
}}
gone_within() {{
  n=0
  while [ -n "$(new_pids)" ]; do
    [ "$n" -ge "$1" ] && return 1
    sleep 1
    n=$((n + 1))
  done
  return 0
}}
stop_new() {{
  for p in $(new_pids); do kill "$p" 2>/dev/null; done
  if ! gone_within 5; then
    for p in $(new_pids); do kill -9 "$p" 2>/dev/null; done
    gone_within 30 || say "the new version is still running; the old one is put back all the same"
  fi
}}

say "waiting for the app to close"
waited=0
while kill -0 "$PID" 2>/dev/null; do
  if [ "$waited" -ge "$CLOSE_WAIT" ]; then
    say "the app did not close in $CLOSE_WAIT seconds; nothing was changed"
    result failed close false
    exit 1
  fi
  sleep 1
  waited=$((waited + 1))
done

rm -f "$RESULT"
if ! new_is_checked; then
  say "the new version is not the one that was checked; nothing was changed"
  result failed mismatch false
  launch
  exit 1
fi
rm -rf "$OLD" "$FAILED"
say "putting the new version in place"
if ! mv "$APP" "$OLD" >> "$LOG" 2>&1; then
  say "the installed version could not be moved aside; nothing was changed"
  result failed install false
  launch
  exit 1
fi
if ! mv "$NEW" "$APP" >> "$LOG" 2>&1; then
  say "the new version could not be put in place; putting the old one back"
  mv "$OLD" "$APP" >> "$LOG" 2>&1
  result failed install false
  launch
  exit 1
fi

say "opening the new version"
launch
waited=0
reason=no_answer
while [ "$waited" -lt "$ANSWER_WAIT" ]; do
  if answered '"status":"ok"'; then
    say "the new version is running; removing the old one"
    rm -rf "$OLD"
    exit 0
  fi
  if answered '"status":"wrong"'; then
    reason=wrong_version
    break
  fi
  sleep 1
  waited=$((waited + 1))
done

if [ "$reason" = wrong_version ]; then
  say "the version that opened is not the one expected; putting the old one back"
else
  say "the new version did not answer in $ANSWER_WAIT seconds; putting the old one back"
fi
stop_new
if ! mv "$APP" "$FAILED" >> "$LOG" 2>&1; then
  rm -rf "$APP"
fi
mv "$OLD" "$APP" >> "$LOG" 2>&1
rm -rf "$FAILED"
rm -f "$RESULT"
result failed "$reason" true
launch
exit 1
"""


def mac_script(hand: Hand) -> str:
    """The hand-over for the Mac: swap the app bundles, open the new one, wait for it, else swap them back."""
    return _SH.format(
        pid=int(hand.pid),
        app=_sh(hand.app),
        old=_sh(hand.old),
        new=_sh(hand.new),
        failed=_sh(hand.app + ".failed"),
        result=_sh(hand.result),
        log=_sh(hand.log),
        from_version=_sh(hand.from_version),
        close_wait=int(hand.close_wait),
        answer_wait=int(hand.answer_wait),
        launch=" ".join(_sh(a) for a in hand.launch),
        attempt=_sh(_hex(hand.attempt, None, "the attempt's id")),
        sums=_sh(hand.sums) if hand.sums else _refuse("the list of the new app's checksums"),
        files=int(hand.files),
        links=_sh(_hex(hand.links, 64, "the new app's links")),
    )


def _refuse(what: str) -> str:
    raise ValueError(f"the hand-over needs {what}")


_PS = """$ErrorActionPreference = 'Continue'
$AppPid = {pid}
$App = {app}
$Old = {old}
$Setup = {new}
$Failed = {failed}
$Result = {result}
$Log = {log}
$SetupLog = {setup_log}
$From = {from_version}
$CloseWait = {close_wait}
$AnswerWait = {answer_wait}
$InstallWait = {install_wait}
$Attempt = {attempt}
$Sha = {sha256}
$Exe = Join-Path $App 'Thimbleby.exe'

function Say($Text) {{
  Add-Content -LiteralPath $Log -Value ("{{0}} {{1}}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Text)
}}
function Write-Result($Status, $Reason, $Restore) {{
  $Body = '{{"status":"' + $Status + '","reason":"' + $Reason + '","restore":' + $Restore + ',"from":"' + $From + '"}}'
  [System.IO.File]::WriteAllText($Result + '.tmp', $Body, (New-Object System.Text.UTF8Encoding $false))
  Move-Item -LiteralPath ($Result + '.tmp') -Destination $Result -Force
}}
function Launch {{
  if (Test-Path -LiteralPath $Exe) {{
    Start-Process -FilePath $Exe -WorkingDirectory $App
  }}
}}
function Remove-Tree($Path) {{
  for ($i = 0; $i -lt 60; $i++) {{
    if (-not (Test-Path -LiteralPath $Path)) {{ return $true }}
    Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $Path)) {{ return $true }}
    Start-Sleep -Seconds 1
  }}
  return $false
}}
function Move-Tree($From, $To) {{
  for ($i = 0; $i -lt 60; $i++) {{
    try {{
      Move-Item -LiteralPath $From -Destination $To -ErrorAction Stop
      return $true
    }} catch {{
      Start-Sleep -Seconds 1
    }}
  }}
  return $false
}}
function Put-Back {{
  Say 'putting the old version back'
  Remove-Tree $Failed | Out-Null
  if (Test-Path -LiteralPath $App) {{
    if (-not (Move-Tree $App $Failed)) {{ Remove-Tree $App | Out-Null }}
  }}
  if (-not (Move-Tree $Old $App)) {{ Say 'the old version could not be put back' }}
  Remove-Tree $Failed | Out-Null
}}

Say 'waiting for the app to close'
Wait-Process -Id $AppPid -Timeout $CloseWait -ErrorAction SilentlyContinue
if (Get-Process -Id $AppPid -ErrorAction SilentlyContinue) {{
  Say "the app did not close in $CloseWait seconds; nothing was changed"
  Write-Result 'failed' 'close' 'false'
  exit 1
}}

Remove-Item -LiteralPath $Result -Force -ErrorAction SilentlyContinue
Remove-Tree $Old | Out-Null
Say 'moving the installed version aside'
if (-not (Move-Tree $App $Old)) {{
  Say 'the installed version could not be moved aside; nothing was changed'
  Write-Result 'failed' 'install' 'false'
  Launch
  exit 1
}}

# The setup is the file that was checked: it is held open so it can't be changed or replaced from here on, and its
# SHA-256 is taken again. Anything else is never run.
Say 'checking the setup'
$Hold = $null
try {{
  $Share = [System.IO.FileShare]::Read
  $Hold = [System.IO.File]::Open($Setup, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, $Share)
}} catch {{
  Say ('the setup could not be held open: ' + $_.Exception.Message)
}}
$Found = ''
try {{
  $Found = (Get-FileHash -LiteralPath $Setup -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
}} catch {{
  Say ('the setup could not be read: ' + $_.Exception.Message)
}}
if ($Found -ne $Sha) {{
  Say 'the setup is not the file that was checked; it was not run'
  if ($Hold) {{ $Hold.Dispose() }}
  Put-Back
  Write-Result 'failed' 'mismatch' 'false'
  Launch
  exit 1
}}

Say 'running the setup'
$Process = $null
try {{
  $Process = Start-Process -FilePath $Setup -PassThru -ArgumentList @(
    '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER',
    ('/DIR="' + $App + '"'), ('/LOG="' + $SetupLog + '"')
  )
  # Reading the handle keeps the exit code readable after the process ends.
  $null = $Process.Handle
}} catch {{
  Say ('the setup could not be started: ' + $_.Exception.Message)
}}
$Done = $false
if ($Process) {{
  $Done = $Process.WaitForExit($InstallWait * 1000)
  if (-not $Done) {{
    Say "the setup did not finish in $InstallWait seconds"
    try {{ $Process.Kill() }} catch {{ }}
  }}
}}
if ($Hold) {{ $Hold.Dispose() }}
if (-not $Done -or $Process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $Exe)) {{
  if ($Process -and $Done) {{ Say ('the setup stopped with code ' + $Process.ExitCode) }}
  Put-Back
  Write-Result 'failed' 'install' 'false'
  Launch
  exit 1
}}

Say 'opening the new version'
Launch
$Waited = 0
$Reason = 'no_answer'
while ($Waited -lt $AnswerWait) {{
  $Text = ''
  if (Test-Path -LiteralPath $Result) {{
    try {{ $Text = [string](Get-Content -LiteralPath $Result -Raw -ErrorAction Stop) }} catch {{ $Text = '' }}
  }}
  # Only an answer that carries this attempt's id counts.
  if ($Text.Contains('"attempt":"' + $Attempt + '"')) {{
    if ($Text.Contains('"status":"ok"')) {{
      Say 'the new version is running; removing the old one'
      Remove-Tree $Old | Out-Null
      exit 0
    }}
    if ($Text.Contains('"status":"wrong"')) {{
      $Reason = 'wrong_version'
      break
    }}
  }}
  Start-Sleep -Seconds 1
  $Waited++
}}

if ($Reason -eq 'wrong_version') {{
  Say 'the version that opened is not the one expected'
}} else {{
  Say "the new version did not answer in $AnswerWait seconds"
}}
Get-Process | Where-Object {{ $_.Path -eq $Exe }} | Stop-Process -Force -ErrorAction SilentlyContinue
for ($i = 0; $i -lt 30; $i++) {{
  if (-not (Get-Process | Where-Object {{ $_.Path -eq $Exe }})) {{ break }}
  Start-Sleep -Seconds 1
}}
Put-Back
Remove-Item -LiteralPath $Result -Force -ErrorAction SilentlyContinue
Write-Result 'failed' $Reason 'true'
Launch
exit 1
"""


def windows_script(hand: Hand) -> str:
    """The hand-over for Windows: move the installed folder aside, run the setup silently into its place, open the new
    version and wait for it, else put the old folder back."""
    return _PS.format(
        pid=int(hand.pid),
        app=_ps(hand.app),
        old=_ps(hand.old),
        new=_ps(hand.new),
        failed=_ps(hand.app + ".failed"),
        result=_ps(hand.result),
        log=_ps(hand.log),
        setup_log=_ps(hand.setup_log or hand.log + ".setup"),
        from_version=_ps(hand.from_version),
        close_wait=int(hand.close_wait),
        answer_wait=int(hand.answer_wait),
        install_wait=int(hand.install_wait),
        attempt=_ps(_hex(hand.attempt, None, "the attempt's id")),
        sha256=_ps(_hex(hand.sha256, 64, "the setup's SHA-256")),
    )
