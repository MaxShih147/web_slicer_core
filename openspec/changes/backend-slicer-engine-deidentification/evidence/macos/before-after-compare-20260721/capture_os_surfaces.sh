#!/usr/bin/env bash
# Capture real macOS UI surfaces for before/after de-identification evidence.
# Requires: Screen Recording permission for the terminal / Cursor host.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SHOTS="$ROOT/shots"
SOURCE="$ROOT/source"
mkdir -p "$SHOTS"

BEFORE_DIR="$ROOT/staging/BEFORE_install_surface/prusaslicer_build/src"  # install-surface only（no Makefile/cmake/libs）
AFTER_ROOT="/Applications/Bundle Launcher.app/Contents/Resources/bundle/slicer-engine"
AFTER_BIN="$AFTER_ROOT/bin"
DIAG_RETIRED="$HOME/Library/Logs/DiagnosticReports/Retired"
BEFORE_BIN="$BEFORE_DIR/PrusaSlicer"
AFTER_EXE="$AFTER_BIN/slicer-engine"
BEFORE_IPS="$SOURCE/BEFORE_PrusaSlicer_overflow_brand_stack.ips"
AFTER_IPS="$SOURCE/AFTER_slicer-engine_segfault.ips"
AFTER_IPS_CLEAN="$SOURCE/AFTER_exception_clean.ips"

log() { printf '[capture] %s\n' "$*"; }

capture_front_window() {
  local out="$1"
  local app="${2:-Finder}"
  local bounds
  if [[ "$app" == "Finder" ]]; then
    bounds="$(osascript <<'OSA'
tell application "Finder"
  activate
  delay 0.25
  if (count of windows) is 0 then error "no Finder windows"
  set b to bounds of front window
  set x to item 1 of b
  set y to item 2 of b
  set w to (item 3 of b) - x
  set h to (item 4 of b) - y
  return (x as text) & "," & (y as text) & "," & (w as text) & "," & (h as text)
end tell
OSA
)"
  else
    bounds="$(osascript <<OSA
tell application "$app" to activate
delay 0.3
tell application "System Events"
  tell process "$app"
    set frontmost to true
    delay 0.2
    if (count of windows) is 0 then error "no windows for $app"
    set p to position of window 1
    set s to size of window 1
    set x to item 1 of p
    set y to item 2 of p
    set w to item 1 of s
    set h to item 2 of s
    return (x as text) & "," & (y as text) & "," & (w as text) & "," & (h as text)
  end tell
end tell
OSA
)" || {
      log "WARN: System Events unavailable for $app — full-screen capture"
      screencapture -x -t png "$out"
      return 0
    }
  fi
  screencapture -x -R "$bounds" -t png "$out"
  log "saved $out (region $bounds from $app)"
}

open_finder_list() {
  local dir="$1"
  local title="$2"
  osascript <<OSA
tell application "Finder"
  activate
  set theFolder to (POSIX file "$dir") as alias
  set w to make new Finder window to theFolder
  set current view of w to list view
  set bounds of w to {80, 60, 1180, 780}
  try
    set toolbar visible of w to true
    set sidebar width of w to 160
    set statusbar visible of w to true
  end try
  delay 0.8
end tell
OSA
}

close_finder_windows() {
  osascript <<'OSA' || true
tell application "Finder"
  close every window
end tell
OSA
}

# --- 01 Finder BEFORE install folder ---
log "01 BEFORE Finder install folder"
close_finder_windows
open_finder_list "$BEFORE_DIR" "BEFORE prusaslicer_build src"
sleep 0.8
capture_front_window "$SHOTS/01_BEFORE_finder_install_folder.png" "Finder"

# --- 02 Finder AFTER slicer-engine/bin ---
log "02 AFTER Finder bin"
close_finder_windows
open_finder_list "$AFTER_BIN" "AFTER slicer-engine bin"
sleep 0.8
capture_front_window "$SHOTS/02_AFTER_finder_install_folder.png" "Finder"

# --- 03 Finder AFTER slicer-engine root ---
log "03 AFTER Finder root"
close_finder_windows
open_finder_list "$AFTER_ROOT" "AFTER slicer-engine root"
sleep 0.8
capture_front_window "$SHOTS/03_AFTER_finder_slicer-engine_root.png" "Finder"

# --- 08/09 Get Info ---
log "08 BEFORE Get Info"
close_finder_windows
osascript <<OSA
tell application "Finder"
  activate
  set f to (POSIX file "$BEFORE_BIN") as alias
  open information window of f
  delay 0.8
end tell
tell application "System Events"
  tell process "Finder"
    set frontmost to true
    delay 0.3
    -- enlarge info window if possible
    try
      set position of window 1 to {120, 80}
      set size of window 1 to {520, 720}
    end try
  end tell
end tell
OSA
sleep 0.5
capture_front_window "$SHOTS/08_BEFORE_GetInfo.png" "Finder"

log "09 AFTER Get Info"
osascript <<OSA
tell application "Finder"
  close every information window
  set f to (POSIX file "$AFTER_EXE") as alias
  open information window of f
  delay 0.8
end tell
tell application "System Events"
  tell process "Finder"
    set frontmost to true
    delay 0.3
    try
      set position of window 1 to {120, 80}
      set size of window 1 to {520, 720}
    end try
  end tell
end tell
OSA
sleep 0.5
capture_front_window "$SHOTS/09_AFTER_GetInfo.png" "Finder"
osascript -e 'tell application "Finder" to close every information window' || true

# --- 15 DiagnosticReports Retired (OS crash folder = WER equivalent) ---
log "15 DiagnosticReports Retired"
close_finder_windows
open_finder_list "$DIAG_RETIRED" "DiagnosticReports Retired"
sleep 1.0
capture_front_window "$SHOTS/15_OS_DiagnosticReports_Retired.png" "Finder"

# Focused crops: open filtered search windows via mdfind copies into temp evidence dirs
BEFORE_DIAG_TMP="$ROOT/tmp-diag-before"
AFTER_DIAG_TMP="$ROOT/tmp-diag-after"
rm -rf "$BEFORE_DIAG_TMP" "$AFTER_DIAG_TMP"
mkdir -p "$BEFORE_DIAG_TMP" "$AFTER_DIAG_TMP"
# Hardlink/copy recent branded + clean reports for a clean Finder list (real .ips bytes)
cp -c "$DIAG_RETIRED"/PrusaSlicer-2026-07-14-091744.ips "$BEFORE_DIAG_TMP/" 2>/dev/null || cp "$DIAG_RETIRED"/PrusaSlicer-2026-07-14-091744.ips "$BEFORE_DIAG_TMP/"
cp -c "$DIAG_RETIRED"/PrusaSlicer-2026-07-17-103236.ips "$BEFORE_DIAG_TMP/" 2>/dev/null || cp "$DIAG_RETIRED"/PrusaSlicer-2026-07-17-103236.ips "$BEFORE_DIAG_TMP/"
cp -c "$DIAG_RETIRED"/slicer-engine-2026-07-20-045446.ips "$AFTER_DIAG_TMP/" 2>/dev/null || cp "$DIAG_RETIRED"/slicer-engine-2026-07-20-045446.ips "$AFTER_DIAG_TMP/"
cp -c "$DIAG_RETIRED"/slicer-engine-2026-07-20-045347.ips "$AFTER_DIAG_TMP/" 2>/dev/null || cp "$DIAG_RETIRED"/slicer-engine-2026-07-20-045347.ips "$AFTER_DIAG_TMP/"
# Also place authoritative clean AFTER ips used in report
cp "$AFTER_IPS" "$AFTER_DIAG_TMP/slicer-engine-m1-close-segfault.ips"
cp "$AFTER_IPS_CLEAN" "$AFTER_DIAG_TMP/slicer-engine-5.1b-exception-clean.ips"

log "17 BEFORE AppCrash-like .ips filenames"
close_finder_windows
open_finder_list "$BEFORE_DIAG_TMP" "BEFORE DiagnosticReports PrusaSlicer"
sleep 0.8
capture_front_window "$SHOTS/17_OS_DiagnosticReports_PrusaSlicer.png" "Finder"

log "16 AFTER AppCrash-like .ips filenames"
close_finder_windows
open_finder_list "$AFTER_DIAG_TMP" "AFTER DiagnosticReports slicer-engine"
sleep 0.8
capture_front_window "$SHOTS/16_OS_DiagnosticReports_slicer-engine.png" "Finder"

# --- Open .ips in Console.app (real OS crash viewer) ---
open_ips_in_console() {
  local ips="$1"
  local out="$2"
  # Prefer Console; fall back to TextEdit if Console fails to show content
  open -a Console "$ips" || open -a TextEdit "$ips"
  sleep 2.0
  # Bring Console front and try to capture its window
  osascript <<'OSA' || true
tell application "Console" to activate
delay 0.8
tell application "System Events"
  tell process "Console"
    set frontmost to true
    try
      set position of window 1 to {40, 40}
      set size of window 1 to {1280, 860}
    end try
  end tell
end tell
OSA
  sleep 0.8
  if ! capture_front_window "$out" "Console" 2>/dev/null; then
    log "Console capture failed — falling back to TextEdit"
    open -a TextEdit "$ips"
    sleep 1.2
    osascript <<'OSA'
tell application "TextEdit" to activate
delay 0.4
tell application "System Events"
  tell process "TextEdit"
    set frontmost to true
    try
      set position of window 1 to {40, 40}
      set size of window 1 to {1100, 820}
    end try
  end tell
end tell
OSA
    sleep 0.5
    capture_front_window "$out" "TextEdit"
  fi
  osascript -e 'tell application "Console" to close every window' 2>/dev/null || true
  osascript -e 'tell application "TextEdit" to close every window saving no' 2>/dev/null || true
}

log "22 BEFORE .ips in Console/TextEdit"
open_ips_in_console "$BEFORE_IPS" "$SHOTS/22_OS_ips_PrusaSlicer_Console.png"

log "18 AFTER .ips in Console/TextEdit"
open_ips_in_console "$AFTER_IPS" "$SHOTS/18_OS_ips_slicer-engine_Console.png"

log "18b AFTER clean exception .ips"
open_ips_in_console "$AFTER_IPS_CLEAN" "$SHOTS/18b_OS_ips_slicer-engine_exception_clean_Console.png"

# --- codesign Terminal capture (macOS identity surface; VERSIONINFO equivalent) ---
log "codesign Terminal captures"
osascript <<OSA
tell application "Terminal"
  activate
  do script "clear; echo '=== BEFORE codesign ==='; codesign -dv --verbose=4 '$BEFORE_BIN' 2>&1 | sed -n '1,25p'; echo; echo '=== AFTER codesign ==='; codesign -dv --verbose=4 '$AFTER_EXE' 2>&1 | sed -n '1,25p'; echo; echo '(leave this window open for screenshot)'"
  delay 2.0
end tell
tell application "System Events"
  tell process "Terminal"
    set frontmost to true
    try
      set position of window 1 to {60, 60}
      set size of window 1 to {980, 640}
    end try
  end tell
end tell
OSA
sleep 2.5
capture_front_window "$SHOTS/COMPARE_03_codesign_before_vs_after_terminal.png" "Terminal" || \
  screencapture -x -t png "$SHOTS/COMPARE_03_codesign_before_vs_after_terminal.png"

# Split codesign into BEFORE / AFTER by running separately
osascript <<OSA
tell application "Terminal"
  activate
  do script "clear; printf '\\n  BEFORE · codesign -dv\\n\\n'; codesign -dv --verbose=4 '$BEFORE_BIN' 2>&1 | egrep -i 'Executable=|Identifier=|Format=|Authority=|TeamIdentifier|Info.plist|Signature=' ; echo; echo 'done.'"
  delay 1.8
end tell
tell application "System Events"
  tell process "Terminal"
    set frontmost to true
    try
      set position of window 1 to {80, 80}
      set size of window 1 to {900, 520}
    end try
  end tell
end tell
OSA
sleep 2.0
capture_front_window "$SHOTS/08b_BEFORE_codesign_Terminal.png" "Terminal"

osascript <<OSA
tell application "Terminal"
  activate
  do script "clear; printf '\\n  AFTER · codesign -dv\\n\\n'; codesign -dv --verbose=4 '$AFTER_EXE' 2>&1 | egrep -i 'Executable=|Identifier=|Format=|Authority=|TeamIdentifier|Info.plist|Signature=' ; echo; echo 'done.'"
  delay 1.8
end tell
tell application "System Events"
  tell process "Terminal"
    set frontmost to true
    try
      set position of window 1 to {80, 80}
      set size of window 1 to {900, 520}
    end try
  end tell
end tell
OSA
sleep 2.0
capture_front_window "$SHOTS/09b_AFTER_codesign_Terminal.png" "Terminal"

# Cleanup Terminal windows (optional)
osascript -e 'tell application "Terminal" to close every window' 2>/dev/null || true
close_finder_windows

log "DONE — shots:"
ls -la "$SHOTS" | sed -n '1,80p'
