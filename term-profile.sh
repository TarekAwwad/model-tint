#!/bin/bash

# Hooks stay quiet by default. Enable diagnostics only for manual troubleshooting.
# No log files are created or opened.
exec 3>/dev/null
if [ "${TERM_PROFILE_DEBUG:-}" = 1 ]; then
  exec 3>&2
fi

log_message() {
  printf '%s\n' "$*" >&3
}

profile_for_model() {
  case "$1" in
    *sonnet*) printf '%s\n' 'Claude Low' ;;
    *opus*)   printf '%s\n' 'Claude Mid' ;;
    *fable*)  printf '%s\n' 'Claude High' ;;
    *luna*)   printf '%s\n' 'Codex Low' ;;
    *sol*)    printf '%s\n' 'Codex Mid' ;;
    *astra*)  printf '%s\n' 'Codex High' ;;
    *)        printf '%s\n' '' ;;
  esac
}

# Claude hooks can run without a controlling tty. Walk up to the first parent
# with one, then find the Terminal tab that owns it.
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

set_selected_profile() {
  osascript - "$1" >/dev/null 2>&3 <<'APPLESCRIPT'
on run argv
  set wantedProfile to item 1 of argv
  tell application "Terminal"
    if (count of windows) = 0 then
      log "CODEX: no Terminal windows"
      return
    end if

    set tb to selected tab of front window
    try
      set targetSettings to settings set wantedProfile
    on error errMsg number errNum
      log "CODEX: profile not found: " & wantedProfile & " (" & errNum & ": " & errMsg & ")"
      return
    end try

    try
      set current settings of tb to targetSettings
      log "CODEX: tty=" & (tty of tb) & " profile=" & (name of current settings of tb)
    on error errMsg number errNum
      log "CODEX: unable to change profile (" & errNum & ": " & errMsg & ")"
    end try
  end tell
end run
APPLESCRIPT
}

set_tty_profile() {
  osascript - "$1" "$2" >/dev/null 2>&3 <<'APPLESCRIPT'
on run argv
  set fullTTY to "/dev/" & (item 1 of argv)
  set wantedProfile to item 2 of argv

  tell application "Terminal"
    try
      set targetSettings to settings set wantedProfile
    on error errMsg number errNum
      log "CLAUDE: profile not found: " & wantedProfile & " (" & errNum & ": " & errMsg & ")"
      return
    end try

    repeat with w in windows
      repeat with tb in tabs of w
        try
          if (tty of tb) is fullTTY then
            set current settings of tb to targetSettings
            log "CLAUDE: tty=" & fullTTY & " profile=" & (name of current settings of tb)
            return
          end if
        on error errMsg number errNum
          log "CLAUDE: unable to inspect or change tab (" & errNum & ": " & errMsg & ")"
        end try
      end repeat
    end repeat
    log "CLAUDE: no Terminal tab matched " & fullTTY
  end tell
end run
APPLESCRIPT
}

apply_profile() {
  local app=$1 profile=$2 tty
  if [ "$app" = claude ]; then
    tty=$(ancestor_tty)
    if [ -z "$tty" ]; then
      log_message "CLAUDE: no tty found; profile='$profile'"
      return
    fi
    set_tty_profile "$tty" "$profile"
  else
    set_selected_profile "$profile"
  fi
}

if [ "${1:-}" = reset ]; then
  if [ "$#" -gt 2 ]; then
    log_message 'invalid arguments; skipped'
    exit 0
  fi
  case "${2:-codex}" in
    claude|codex) ;;
    *) log_message 'invalid reset app; skipped'; exit 0 ;;
  esac
  # Claude's end hook passes "claude" so its own tab is reset. Codex uses
  # the selected tab, just as it does for model changes.
  log_message "reset app='${2:-codex}' profile='Basic'"
  apply_profile "${2:-codex}" Basic || log_message 'Terminal automation failed during reset'
  exit 0
fi

if [ "$#" -ne 0 ]; then
  log_message 'invalid arguments; skipped'
  exit 0
fi

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

profile=$(profile_for_model "$model")
if [ -z "$profile" ]; then
  log_message "unmatched model='$model'"
  exit 0
fi

case "$model" in
  *sonnet*|*opus*|*fable*) app=claude ;;
  *)                       app=codex ;;
esac

log_message "model='$model' app='$app' profile='$profile'"
apply_profile "$app" "$profile" || log_message 'Terminal automation failed during profile change'
exit 0
