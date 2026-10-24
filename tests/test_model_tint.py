"""Exercise the actual hook script with terminals and app lookups replaced by stubs."""

import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "model-tint.sh"

LOW, MID, HIGH = "#0f2a1d", "#33260a", "#3a1010"
RESET = "\x1b]111\x07"


def osc_color(color):
    return f"\x1b]11;{color}\x07"


def readme_hook_configs():
    readme = (ROOT / "README.md").read_text()
    return {
        "codex": tomllib.loads(re.search(r"```toml\n(.*?)\n```", readme, re.S)[1]),
        "claude": json.loads(re.search(r"```json\n(.*?)\n```", readme, re.S)[1]),
    }


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="model-tint-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.dev = self.root / "dev"
        self.dev.mkdir()
        self.home = self.root / "home with spaces"
        self.home.mkdir()
        self.env = {
            "PATH": str(self.bin) + ":/usr/bin:/bin",
            "HOME": str(self.home),
            "TMPDIR": str(self.root),
            "MODEL_TINT_DEV_DIR": str(self.dev),
        }
        jq = shutil.which("jq")
        if not jq:
            self.fail("jq is required to run these tests")
        (self.bin / "jq").symlink_to(jq)
        # Claude's ancestor tty.
        self.write_command("ps", '''#!/bin/bash
printf '%s\\n' "${TEST_TTY:-ttys999}"
''')
        # Front app: Terminal unless a test says otherwise.
        self.write_command("lsappinfo", '''#!/bin/bash
case "$1" in
  front) printf 'ASN:0x0-0x1:\\n' ;;
  info) printf '"CFBundleIdentifier"="%s"\\n' "${FRONT_APP-com.apple.Terminal}" ;;
esac
''')
        # Terminal's selected tab.
        self.write_command("osascript", '''#!/bin/bash
printf 'automation diagnostic\\n' >&2
[ "${AUTOMATION_STATUS:-0}" = 0 ] || exit "$AUTOMATION_STATUS"
printf '/dev/%s\\n' "${TERMINAL_TTY:-ttys777}"
''')
        # cmux's focused pane, next to an unfocused pane and a browser.
        self.write_command("cmux", '''#!/bin/bash
cat <<JSON
{"windows":[{"workspaces":[{"panes":[
  {"surfaces":[{"ref":"surface:1","type":"terminal","tty":"ttys111","active":false}]},
  {"surfaces":[{"ref":"surface:2","type":"browser","tty":null,"active":true},
               {"ref":"surface:3","type":"terminal","tty":"${CMUX_TTY:-ttys888}","active":true}]}
]}]}]}
JSON
''')

    def write_command(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o700)

    def write_colors(self, content, config_home=None):
        path = (config_home or self.home / ".config") / "model-tint" / "colors"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def written(self):
        return {path.name: path.read_text() for path in self.dev.iterdir()}

    def run_hook(self, payload="{}", args=("codex",), debug=False, **env):
        for path in self.dev.iterdir():
            path.unlink()
        run_env = {**self.env, **env}
        if debug:
            run_env["MODEL_TINT_DEBUG"] = "1"
        result = subprocess.run(
            ["/bin/bash", str(SCRIPT), *args], input=payload,
            text=True, capture_output=True, env=run_env, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        if not debug:
            self.assertEqual(result.stderr, "")
        return result

    def test_default_colors_and_switch_priority(self):
        cases = [
            ("claude", {"model": "CLAUDE-SONNET-5"}, {"ttys999": osc_color(LOW)}),
            ("claude", {"model": "claude-opus-5[1m]"}, {"ttys999": osc_color(MID)}),
            ("claude", {"model": "claude-fable"}, {"ttys999": osc_color(HIGH)}),
            ("codex", {"model": "gpt-6-luna"}, {"ttys777": osc_color(LOW)}),
            ("codex", {"model": "gpt-6-sol"}, {"ttys777": osc_color(MID)}),
            ("codex", {"model": "gpt-6-astra"}, {"ttys777": osc_color(HIGH)}),
            ("claude", {"model": "sonnet", "to_model": "opus"}, {"ttys999": osc_color(MID)}),
        ]
        for app, payload, expected in cases:
            with self.subTest(payload=payload):
                self.run_hook(json.dumps(payload), args=(app,))
                self.assertEqual(self.written(), expected)

    def test_colors_file_replaces_defaults(self):
        self.write_colors("# mine\n\nOPUS   #12AB34  trailing note\nnew-model\t#ABCDEF\n")
        self.run_hook('{"model":"claude-opus-5"}', args=("claude",))
        self.assertEqual(self.written(), {"ttys999": osc_color("#12ab34")})
        self.run_hook('{"model":"gpt-7-new-model"}')
        self.assertEqual(self.written(), {"ttys777": osc_color("#abcdef")})
        self.run_hook('{"model":"claude-sonnet-5"}', args=("claude",))
        self.assertEqual(self.written(), {})

    def test_colors_file_honours_xdg_config_home(self):
        config_home = self.root / "xdg"
        self.write_colors("sol #010203\n", config_home)
        self.run_hook('{"model":"gpt-6-sol"}', XDG_CONFIG_HOME=str(config_home))
        self.assertEqual(self.written(), {"ttys777": osc_color("#010203")})

    def test_first_matching_line_wins(self):
        self.write_colors("claude #111111\nopus #222222\n")
        self.run_hook('{"model":"claude-opus-5"}', args=("claude",))
        self.assertEqual(self.written(), {"ttys999": osc_color("#111111")})

    def test_malformed_color_lines_are_skipped(self):
        self.write_colors("\n".join([
            "opus", "opus red", "opus #12345", "opus #1234567", "opus #12345g",
            "opus rgb:12/34/56", "opus $(touch${IFS}pwned)", "opus #123456\x1b]2;x",
            "# opus #999999", "o* #888888", "op?s #777777", "opus #00aa00",
        ]) + "\n")
        result = self.run_hook('{"model":"claude-opus-5"}', args=("claude",), debug=True)
        self.assertEqual(self.written(), {"ttys999": osc_color("#00aa00")})
        self.assertEqual(list(self.root.rglob("pwned")), [])
        self.assertNotIn("\x1b", result.stderr)

    def test_unreadable_colors_file_is_quiet(self):
        self.write_colors("opus #123456\n")
        path = self.home / ".config" / "model-tint" / "colors"
        path.chmod(0)
        self.addCleanup(path.chmod, 0o600)
        self.run_hook('{"model":"claude-opus-5"}', args=("claude",))
        self.assertEqual(self.written(), {})

    def test_codex_uses_the_focused_cmux_pane(self):
        self.run_hook('{"model":"gpt-6-sol"}', FRONT_APP="com.cmuxterm.app")
        self.assertEqual(self.written(), {"ttys888": osc_color(MID)})
        self.run_hook(args=("codex", "reset"), FRONT_APP="com.cmuxterm.app")
        self.assertEqual(self.written(), {"ttys888": RESET})

    def test_codex_skips_other_front_apps(self):
        for front in ("com.googlecode.iterm2", ""):
            with self.subTest(front=front):
                self.run_hook('{"model":"gpt-6-sol"}', FRONT_APP=front)
                self.assertEqual(self.written(), {})

    def test_invalid_ttys_are_never_written(self):
        for tty in ("../escape", "ttys1/../../x", "ttys", "tty.usb", "ttys1 2", "console"):
            with self.subTest(tty=tty):
                self.run_hook('{"model":"opus"}', args=("claude",), TEST_TTY=tty)
                self.run_hook('{"model":"sol"}', TERMINAL_TTY=tty)
                self.run_hook('{"model":"sol"}', FRONT_APP="com.cmuxterm.app", CMUX_TTY=tty)
                self.assertEqual(list(self.root.rglob("*escape*")) + list(self.root.rglob("x")), [])
                self.assertEqual(self.written(), {})

    def test_invalid_json_never_changes_a_color(self):
        for payload in (
            "", "{", "null", "[]", '"sol"', "42",
            '{"model":"sol"} trailing-invalid',
            '{"model":"astra"}\n{"model":"sonnet"}',
            '{"model":"sol"}\nnull',
        ):
            with self.subTest(payload=payload):
                self.run_hook(payload, debug=True)
                self.assertEqual(self.written(), {})

    def test_invalid_models_never_reach_terminals_or_diagnostics(self):
        for model in (
            None, False, 1, [], {}, "", "sol\nFORGED", "sol\rFORGED",
            "sol\x1b[2J", "sol\x00", "sol\x7f", "sol name", "solé",
            "sol;$(id)", "sol`id`", "sol" + "x" * 254,
        ):
            with self.subTest(model=model):
                result = self.run_hook(json.dumps({"model": model}), debug=True)
                self.assertEqual(self.written(), {})
                self.assertEqual(result.stderr, "invalid payload or missing model; skipped\n")

    def test_parser_errors_do_not_expose_payload(self):
        result = self.run_hook('{"model":"sol"} PRIVATE_PROMPT_CONTENT', debug=True)
        self.assertNotIn("PRIVATE_PROMPT_CONTENT", result.stderr)

    def test_missing_or_unknown_model_is_noop(self):
        for payload in ({}, {"model": "unknown"}, {"prompt": "PRIVATE_PROMPT_CONTENT"}):
            self.run_hook(json.dumps(payload))
            self.assertEqual(self.written(), {})

    def test_debug_is_opt_in_and_uses_stderr(self):
        payload = json.dumps({"model": "sol", "prompt": "PRIVATE_PROMPT_CONTENT"})
        self.run_hook(payload)
        result = self.run_hook(payload, debug=True)
        self.assertIn("tty='ttys777' color='#33260a'", result.stderr)
        self.assertIn("automation diagnostic", result.stderr)
        self.assertNotIn("PRIVATE_PROMPT_CONTENT", result.stderr)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_reset_and_invalid_arguments(self):
        for args, expected in (
            (("codex", "reset"), {"ttys777": RESET}),
            (("claude", "reset"), {"ttys999": RESET}),
        ):
            self.run_hook(args=args)
            self.assertEqual(self.written(), expected)
        for args in (
            (), ("bad",), ("reset",), ("reset", "codex"), ("claude", "extra"),
            ("codex", "bad\nFORGED"), ("codex", "reset", "extra"),
        ):
            with self.subTest(args=args):
                result = self.run_hook('{"model":"sol"}', args=args, debug=True)
                self.assertEqual(self.written(), {})
                self.assertNotIn("FORGED", result.stderr)

    def test_missing_jq_and_automation_failure_stay_quiet(self):
        self.run_hook('{"model":"sol"}', AUTOMATION_STATUS="1")
        self.assertEqual(self.written(), {})
        (self.bin / "jq").unlink()
        self.env["PATH"] = str(self.bin)
        self.run_hook('{"model":"sol"}')
        self.assertEqual(self.written(), {})

    def test_unwritable_tty_stays_quiet(self):
        self.dev.chmod(0o500)
        self.addCleanup(self.dev.chmod, 0o700)
        result = self.run_hook('{"model":"opus"}', args=("claude",), debug=True)
        self.assertIn("colour change failed", result.stderr)
        self.run_hook('{"model":"opus"}', args=("claude",))

    def test_claude_without_a_tty_does_not_change_another_tab(self):
        self.write_command("ps", '''#!/bin/bash
case "$2" in
  tty=) printf '??\\n' ;;
  ppid=) printf '1\\n' ;;
esac
''')
        for args in (("claude",), ("claude", "reset")):
            with self.subTest(args=args):
                self.run_hook('{"model":"sonnet"}', args=args)
                self.assertEqual(self.written(), {})

    def test_all_documented_hooks_have_three_second_timeouts(self):
        expected_events = {
            "codex": {"SessionStart", "UserPromptSubmit", "SessionEnd"},
            "claude": {"SessionStart", "UserPromptSubmit", "PostModelSwitch", "SessionEnd"},
        }
        for app, config in readme_hook_configs().items():
            self.assertEqual(set(config["hooks"]), expected_events[app])
            for event, groups in config["hooks"].items():
                self.assertTrue(groups)
                for group in groups:
                    self.assertTrue(group["hooks"])
                    for hook in group["hooks"]:
                        with self.subTest(app=app, event=event):
                            self.assertEqual(hook["timeout"], 3)

    def test_readme_commands_name_their_app_and_work_with_spaces_in_home(self):
        installed = self.home / "model-tint.sh"
        shutil.copyfile(SCRIPT, installed)
        installed.chmod(0o700)
        for app, config in readme_hook_configs().items():
            for event, groups in config["hooks"].items():
                for group in groups:
                    for hook in group["hooks"]:
                        with self.subTest(event=event, command=hook["command"]):
                            self.assertIn(f"model-tint.sh\" {app}", hook["command"])
                            for path in self.dev.iterdir():
                                path.unlink()
                            result = subprocess.run(
                                ["/bin/bash", "-c", hook["command"]],
                                input='{"model":"sol"}', text=True,
                                capture_output=True, env=self.env, timeout=5,
                            )
                            self.assertEqual(result.returncode, 0, result.stderr)
                            self.assertEqual(result.stdout + result.stderr, "")
                            self.assertTrue(self.written())


if __name__ == "__main__":
    unittest.main()
