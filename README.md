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
- Bash and `jq`; hooks from Codex's shared app-server also use AppleScript (`osascript`) in Terminal.app
- Claude Code or Codex with command hooks enabled

## Install

Make sure `jq` is installed and available on the `PATH` seen by hooks. Then install the plugin for Claude Code, Codex, or both.

### Claude Code

```
/plugin install model-tint --marketplace TarekAwwad/model-tint
```

On Claude Code older than 2.1.275, add the marketplace first:

```
/plugin marketplace add TarekAwwad/model-tint
/plugin install model-tint@model-tint
```

Model-switch updates require Claude Code 2.1.251 or later. See the [hook reference](https://code.claude.com/docs/en/hooks).

### Codex

```bash
codex plugin marketplace add TarekAwwad/model-tint
codex plugin add model-tint@model-tint
```

Restart Codex. When **Hooks need review** appears, trust the three model-tint hooks; Codex runs no plugin hook before you do. Codex records trust against each hook's hash, so a plugin update can ask again.

The first time a hook from Codex's shared app-server runs in Terminal.app, macOS may ask for automation permission; allow the app running the hook to control Terminal.

### Manual install

Without plugins, copy the script and add the hooks yourself:

```bash
cp model-tint.sh "$HOME/model-tint.sh"
chmod +x "$HOME/model-tint.sh"
```

For Codex, add these entries to `~/.codex/config.toml`, merging them with any hooks you already have:

```toml
[[hooks.SessionStart]]
[[hooks.SessionStart.hooks]]
type = "command"
command = '"$HOME/model-tint.sh"'
timeout = 3

[[hooks.UserPromptSubmit]]
[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = '"$HOME/model-tint.sh"'
timeout = 3

[[hooks.SessionEnd]]
[[hooks.SessionEnd.hooks]]
type = "command"
command = '"$HOME/model-tint.sh" reset'
timeout = 3
```

For Claude Code, merge this `hooks` object into `~/.claude/settings.json`, keeping any other settings already there:

```json
{
  "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command", "command": "\"$HOME/model-tint.sh\"", "timeout": 3 }] }],
    "PostModelSwitch": [{ "hooks": [{ "type": "command", "command": "\"$HOME/model-tint.sh\"", "timeout": 3 }] }],
    "SessionEnd": [{ "hooks": [{ "type": "command", "command": "\"$HOME/model-tint.sh\" reset", "timeout": 3 }] }]
  }
}
```

Running sessions keep the hook commands they started with, so restart them afterwards.

## Choose your colours

The defaults above work without any setup. To use your own colours or add new models, create a colours file. Download [`colors.example`](colors.example) from this repository, then:

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

## Upgrading from v1 (Terminal Model Profile Switcher)

v1 switched Terminal.app profiles and was installed as `term-profile.sh`. To upgrade:

1. Remove the v1 hook entries from `~/.codex/config.toml` and `~/.claude/settings.json`.
2. Install model-tint as above.
3. Restart any Claude Code or Codex sessions that were already running. Sessions keep the hook commands they started with, so until then they still call `term-profile.sh`.
4. Delete `~/term-profile.sh`.
5. The imported Terminal profiles are no longer needed. Tabs that v1 switched keep that profile until you change it back.

v1 remains available at the [`v1.0.0` tag](../../tree/v1.0.0) if you prefer full Terminal profiles (fonts and cursor colours).

## Known limitations

- **Codex `/mode`:** the colour updates on the **next submitted prompt**.
- **Each hook colours the tab or pane its app runs in.** The script walks up from the hook process to the first parent with a terminal, so this works in any terminal that supports OSC 11.
- **Exception: Codex's shared app-server.** Codex can run hooks from a shared background process (`codex app-server`) started from another tab. Such a hook cannot tell which session it belongs to, so it colours the focused tab or pane of the front app (Terminal.app or cmux) instead. If you switch tabs or apps while it runs, the wrong tab can change, including on reset. With any other app in front, these hooks change nothing.
- Claude's `SessionStart` can omit the model; the colour then waits for `PostModelSwitch`.
- Unknown models leave the colour unchanged.

## Troubleshooting

For diagnostics, run this manual check from a clone of this repository, in the Terminal tab or cmux pane you want to colour. With the default colours it applies an amber background:

```bash
printf '%s\n' '{"model":"gpt-6-sol"}' | MODEL_TINT_DEBUG=1 ./model-tint.sh
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

Tests stub the terminals, `ps`, `lsappinfo`, cmux, and Terminal automation. Checked by hand: Claude and Codex hooks colour and reset their own pane in cmux, even when another pane has focus; Claude and Codex both work in Terminal.app; Codex in Terminal.app ran its hooks from the shared app-server, with the same process chain the tests use; and both plugins, installed from a local checkout, coloured and reset their own cmux pane.

## Uninstall

Plugins:

```bash
claude plugin uninstall model-tint@model-tint
codex plugin remove model-tint@model-tint
```

Manual install: remove the hook entries from `~/.codex/config.toml` and `~/.claude/settings.json`, then delete `~/model-tint.sh`.

Either way, delete your colours file if you made one: `rm -r ~/.config/model-tint`.

## License

MIT. See [LICENSE](LICENSE).
