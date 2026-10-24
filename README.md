# model-tint

Colour your terminal background by the active Claude Code or OpenAI Codex model, so you can see at a glance which model is running in each tab. Works in macOS Terminal.app and [cmux](https://cmux.com). One Bash script runs from the apps' hooks; no background process is needed.

| App | Active model contains | Default background |
| --- | --- | --- |
| Claude Code | `sonnet` | Green `#0F2A1D` |
| Claude Code | `opus` | Amber `#33260A` |
| Claude Code | `fable` | Red `#3A1010` |
| Codex | `luna` | Green `#0F2A1D` |
| Codex | `sol` | Amber `#33260A` |
| Codex | `astra` | Red `#3A1010` |
| Either | Session ends | The tab's normal background |

The script prints a standard terminal colour code (OSC 11) into the right tab or pane, so it needs no Terminal profiles. Session end sends OSC 111, which restores the background from the tab's profile or your cmux/Ghostty config.

## Requirements

- macOS with Terminal.app or cmux
- Bash and `jq`; Codex in Terminal.app also uses AppleScript (`osascript`)
- Claude Code or Codex with command hooks enabled

## Install

From this repository:

```bash
cp model-tint.sh "$HOME/model-tint.sh"
chmod +x "$HOME/model-tint.sh"
```

Make sure `jq` is installed and available on the `PATH` seen by hooks. The first time Codex runs in Terminal.app, macOS may ask for automation permission; allow the app running the hook to control Terminal.

Then add the hooks for [Codex](#codex-hooks), [Claude Code](#claude-code-hooks), or both.

## Choose your colours

The defaults above work without any setup. To use your own colours or add new models, create a colours file:

```bash
mkdir -p ~/.config/model-tint
cp colors.example ~/.config/model-tint/colors
```

Each line pairs a name with a background colour:

```
opus    #33260A
sonnet  #0F2A1D
```

- The first line whose name appears in the model ID wins. Matching ignores case.
- Colours must be `#RRGGBB`. Lines that don't fit are skipped.
- The file replaces the defaults, so list every model you use.
- When a new model comes out, add a line; no script update is needed.

If `XDG_CONFIG_HOME` is set in the hooks' environment, the file is read from `$XDG_CONFIG_HOME/model-tint/colors` instead.

## Codex hooks

Add these entries to `~/.codex/config.toml`, merging them with any hooks you already have:

```toml
[[hooks.SessionStart]]
[[hooks.SessionStart.hooks]]
type = "command"
command = '"$HOME/model-tint.sh" codex'
timeout = 3

[[hooks.UserPromptSubmit]]
[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = '"$HOME/model-tint.sh" codex'
timeout = 3

[[hooks.SessionEnd]]
[[hooks.SessionEnd.hooks]]
type = "command"
command = '"$HOME/model-tint.sh" codex reset'
timeout = 3
```

Codex may ask you to review or trust these hooks before it runs them. Restart Codex to try the configuration.

## Claude Code hooks

Merge this `hooks` object into `~/.claude/settings.json` (keep any other settings already there):

```json
{
  "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command", "command": "\"$HOME/model-tint.sh\" claude", "timeout": 3 }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "\"$HOME/model-tint.sh\" claude", "timeout": 3 }] }],
    "PostModelSwitch": [{ "hooks": [{ "type": "command", "command": "\"$HOME/model-tint.sh\" claude", "timeout": 3 }] }],
    "SessionEnd": [{ "hooks": [{ "type": "command", "command": "\"$HOME/model-tint.sh\" claude reset", "timeout": 3 }] }]
  }
}
```

Model-switch updates require Claude Code 2.1.251 or later. See the [hook reference](https://code.claude.com/docs/en/hooks).

## Upgrading from v1 (Terminal Model Profile Switcher)

v1 switched Terminal.app profiles and was installed as `term-profile.sh`. To upgrade:

1. Install `model-tint.sh` as above.
2. Update every hook command: `term-profile.sh` becomes `model-tint.sh codex` or `model-tint.sh claude`, and `reset` becomes `codex reset` or `claude reset`. Codex asks you to approve the changed hooks the next time it starts.
3. Restart any Claude Code or Codex sessions that were already running. Sessions keep the hook commands they started with, so until then they still call `term-profile.sh`.
4. Delete `~/term-profile.sh`.
5. The imported Terminal profiles are no longer needed. Tabs that v1 switched keep that profile until you change it back.

v1 remains available at the [`v1.0.0` tag](../../tree/v1.0.0) if you prefer full Terminal profiles (fonts and cursor colours).

## Known limitations

- **Codex `/mode`:** the colour updates on the **next submitted prompt**.
- **Codex targets the focused tab or pane of the front app** (Terminal.app or cmux). Codex can run hooks from a shared background process started in another tab, so its own tty is unreliable. If you switch tabs or apps while its hook runs, the wrong tab can change, including on reset. With any other app in front, Codex hooks change nothing.
- Claude locates its own tab or pane through the hook process's tty ancestry, so it works in any terminal that supports OSC 11.
- Claude's `SessionStart` can omit the model; the colour then waits for `PostModelSwitch`. `UserPromptSubmit` does not supply the model.
- Unknown models leave the colour unchanged.

## Troubleshooting

For diagnostics, run this manual check with the intended Terminal tab or cmux pane focused. With the default colours it applies an amber background:

```bash
printf '%s\n' '{"model":"gpt-6-sol"}' | MODEL_TINT_DEBUG=1 "$HOME/model-tint.sh" codex
```

The script is silent by default and creates no logs. Debug mode prints the validated model ID, the target tty and colour, and Terminal or cmux errors to stderr; it does not print prompts or raw payloads.

If nothing changes, check:

- The script is executable and `jq` is on the hook's `PATH`.
- For Codex in Terminal.app, macOS has allowed Terminal automation.
- Debug output has no `unmatched model`, `no tab found` or `invalid tty` message.

All configured hooks time out after three seconds; retry after granting automation permission. Direct script invocations have no built-in deadline.

## Tests

Run `python3 -m unittest discover -s tests -v` with Python 3.11+ and `jq`. GitHub Actions runs them on every push and pull request.

Verified 2026-10-24: regression tests and Bash syntax passed on macOS 26.5.1 (25F80), Bash 3.2.57(1)-release (arm64), jq 1.6, and Python 3.12.13. Installed apps: Claude Code 2.1.310, Codex CLI 0.164.0, and cmux 0.65.2.

Tests stub the terminals, `lsappinfo`, cmux, and Terminal automation. Claude and Codex hooks were checked by hand in both Terminal.app and cmux.

## Uninstall

Remove the hook entries above from `~/.codex/config.toml` and `~/.claude/settings.json`, then remove the installed script and any colours file:

```bash
rm "$HOME/model-tint.sh"
rm -r ~/.config/model-tint
```

## License

MIT. See [LICENSE](LICENSE).
