#!/bin/bash

# model-tint: colour the terminal background by the active Claude Code or Codex model.
# Usage: model-tint.sh <claude|codex> [reset], with the hook payload on stdin.

# Hooks stay quiet by default. Enable diagnostics only for manual troubleshooting.
# No log files are created or opened.
exec 3>/dev/null
if [ "${MODEL_TINT_DEBUG:-}" = 1 ]; then
  exec 3>&2
fi

COLORS_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/model-tint/colors"

log_message() {
  printf '%s\n' "$*" >&3
}

# Used when no colours file exists: green for Low, amber for Mid, red for High.
default_colors() {
  cat <<'COLORS'
sonnet  #0F2A1D
opus    #33260A
fable   #3A1010
luna    #0F2A1D
sol     #33260A
astra   #3A1010
COLORS
}

color_table() {
  if [ -f "$COLORS_FILE" ]; then
    cat "$COLORS_FILE" 2>&3
  else
    default_colors
  fi
}

# Print the colour of the first "name colour" line whose name appears in the
# model ID. Malformed lines are skipped, so a bad file never reaches a terminal.
color_for_model() {
  local model=$1 name color
  while read -r name color _; do
    case "$name" in ''|'#'*) continue ;; esac
    [[ $color =~ ^#[0-9a-f]{6}$ ]] || continue
    case "$model" in
      *"$name"*) printf '%s\n' "$color"; return 0 ;;
    esac
  done < <(color_table | tr '[:upper:]' '[:lower:]')
  return 1
}

# Claude hooks can run without a controlling tty. Walk up to the first parent
# with one; that is the tab or pane Claude runs in.
ancestor_tty() {
  local pid=$PPID current_tty

  while [ -n "$pid" ] && [ "$pid" -gt 1 ] 2>/dev/null; do
    current_tty=$(ps -o tty= -p "$pid" 2>/dev/null | tr -d '[:space:]')
    if [ -n "$current_tty" ] && [ "$current_tty" != '??' ]; then
      printf '%s\n' "$current_tty"
      return 0
    fi
    pid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d '[:space:]')
  done
  return 1
}

cmux_cli() {
  if command -v cmux >/dev/null 2>&1; then
    cmux "$@"
  else
    /Applications/cmux.app/Contents/Resources/bin/cmux "$@"
  fi
}

# Codex can run hooks from a shared background process started in another tab,
# so its own tty and environment are unreliable. Use the focused tab or pane of
# the front app instead.
focused_tty() {
  local tty
  case "$(lsappinfo info -only bundleid "$(lsappinfo front)" 2>/dev/null)" in
    *'"com.cmuxterm.app"'*)
      cmux_cli tree --json 2>&3 | jq -r '
        first(.. | objects | select(.active == true and (.tty | type) == "string") | .tty) // empty
      ' 2>&3
      ;;
    *'"com.apple.Terminal"'*)
      tty=$(osascript -e 'tell application "Terminal" to get tty of selected tab of front window' 2>&3) || return 1
      printf '%s\n' "${tty#/dev/}"
      ;;
    *)
      return 1
      ;;
  esac
}

# OSC 11 sets the background colour; OSC 111 restores the configured one.
# MODEL_TINT_DEV_DIR exists only so tests can capture the output.
set_background() {
  local tty=$1 color=$2
  if ! [[ $tty =~ ^ttys[0-9]+$ ]]; then
    log_message 'invalid tty; skipped'
    return 1
  fi
  if [ -n "$color" ]; then
    printf '\033]11;%s\a' "$color"
  else
    printf '\033]111\a'
  fi 2>&3 >"${MODEL_TINT_DEV_DIR:-/dev}/$tty"
}

apply_color() {
  local app=$1 color=$2 tty
  if [ "$app" = claude ]; then
    tty=$(ancestor_tty)
  else
    tty=$(focused_tty)
  fi
  if [ -z "$tty" ]; then
    log_message "$app: no tab found"
    return 0
  fi
  log_message "app='$app' tty='$tty' color='${color:-default}'"
  set_background "$tty" "$color"
}

app=${1:-}
case "$app" in
  claude|codex) ;;
  *) log_message 'usage: model-tint.sh <claude|codex> [reset]'; exit 0 ;;
esac

case "$#:${2:-}" in
  1:) ;;
  2:reset)
    apply_color "$app" '' || log_message 'colour reset failed'
    exit 0
    ;;
  *)
    log_message 'invalid arguments; skipped'
    exit 0
    ;;
esac

if ! command -v jq >/dev/null 2>&1; then
  log_message 'jq is missing; install jq and ensure it is on PATH'
  exit 0
fi

# SessionStart and PostModelSwitch carry Claude's model. Claude's
# UserPromptSubmit currently does not, so that event is a harmless no-op.
# Slurp so extra objects or trailing parse errors cannot yield a partial result.
# Allow only model ID characters before they reach diagnostics.
# Discard parser errors: they can contain fragments of the hook payload.
if ! model=$(jq -ers '
  select(length == 1) | .[0] | select(type == "object") |
  (.to_model // .model) | select(type == "string") |
  select(length > 0 and length <= 256) |
  select(test("[^A-Za-z0-9._:/+@\\[\\]-]") | not) |
  ascii_downcase
' 2>/dev/null); then
  log_message 'invalid payload or missing model; skipped'
  exit 0
fi

if ! color=$(color_for_model "$model"); then
  log_message "unmatched model='$model'"
  exit 0
fi

log_message "model='$model' app='$app'"
apply_color "$app" "$color" || log_message 'colour change failed'
exit 0
