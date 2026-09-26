"""Exercise the actual hook script with Terminal automation replaced by a stub."""

import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "term-profile.sh"


def readme_hook_configs():
    readme = (ROOT / "README.md").read_text()
    return {
        "codex": tomllib.loads(re.search(r"```toml\n(.*?)\n```", readme, re.S)[1]),
        "claude": json.loads(re.search(r"```json\n(.*?)\n```", readme, re.S)[1]),
    }


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="term-profile-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.home = self.root / "home with spaces"
        self.home.mkdir()
        self.capture = self.root / "automation-args"
        self.env = {
            "PATH": str(self.bin) + ":/usr/bin:/bin",
            "HOME": str(self.home),
            "TMPDIR": str(self.root),
            "REVIEW_CAPTURE": str(self.capture),
        }
        jq = shutil.which("jq")
        if not jq:
            self.fail("jq is required to run these tests")
        (self.bin / "jq").symlink_to(jq)
        self.write_command("osascript", '''#!/bin/bash
printf '%s\\n' "$@" > "$REVIEW_CAPTURE"
/bin/cat >/dev/null
printf 'automation stdout\\n'
printf 'automation diagnostic\\n' >&2
exit "${AUTOMATION_STATUS:-0}"
''')
        self.write_command("ps", '''#!/bin/bash
printf '%s\\n' "${TEST_TTY:-ttys999}"
''')

    def write_command(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o700)

    def run_hook(self, payload="{}", args=(), debug=False):
        self.capture.unlink(missing_ok=True)
        env = dict(self.env)
        if debug:
            env["TERM_PROFILE_DEBUG"] = "1"
        result = subprocess.run(
            ["/bin/bash", str(SCRIPT), *args], input=payload,
            text=True, capture_output=True, env=env, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        if not debug:
            self.assertEqual(result.stderr, "")
        return result

    def test_model_mappings_and_switch_priority(self):
        cases = [
            ({"model": "CLAUDE-SONNET-5"}, ["ttys999", "Claude Low"]),
            ({"model": "claude-opus-5[1m]"}, ["ttys999", "Claude Mid"]),
            ({"model": "claude-fable"}, ["ttys999", "Claude High"]),
            ({"model": "gpt-6-luna"}, ["Codex Low"]),
            ({"model": "gpt-6-sol"}, ["Codex Mid"]),
            ({"model": "gpt-6-astra"}, ["Codex High"]),
            ({"model": "sonnet", "to_model": "opus"}, ["ttys999", "Claude Mid"]),
        ]
        for payload, expected in cases:
            with self.subTest(payload=payload):
                self.run_hook(json.dumps(payload))
                self.assertEqual(self.capture.read_text().splitlines(), ["-", *expected])

    def test_invalid_json_never_applies_a_profile(self):
        for payload in (
            "", "{", "null", "[]", '"sol"', "42",
            '{"model":"sol"} trailing-invalid',
            '{"model":"astra"}\n{"model":"sonnet"}',
            '{"model":"sol"}\nnull',
        ):
            with self.subTest(payload=payload):
                self.run_hook(payload, debug=True)
                self.assertFalse(self.capture.exists())

    def test_invalid_models_never_reach_automation_or_diagnostics(self):
        for model in (
            None, False, 1, [], {}, "", "sol\nFORGED", "sol\rFORGED",
            "sol\x1b[2J", "sol\x00", "sol\x7f", "sol name", "solé",
            "sol;$(id)", "sol`id`", "sol" + "x" * 254,
        ):
            with self.subTest(model=model):
                result = self.run_hook(json.dumps({"model": model}), debug=True)
                self.assertFalse(self.capture.exists())
                self.assertEqual(result.stderr, "invalid payload or missing model; skipped\n")

    def test_parser_errors_do_not_expose_payload(self):
        result = self.run_hook('{"model":"sol"} PRIVATE_PROMPT_CONTENT', debug=True)
        self.assertNotIn("PRIVATE_PROMPT_CONTENT", result.stderr)

    def test_missing_or_unknown_model_is_noop(self):
        for payload in ({}, {"model": "unknown"}, {"prompt": "PRIVATE_PROMPT_CONTENT"}):
            self.run_hook(json.dumps(payload))
            self.assertFalse(self.capture.exists())

    def test_debug_is_opt_in_and_uses_stderr(self):
        payload = json.dumps({"model": "sol", "prompt": "PRIVATE_PROMPT_CONTENT"})
        self.run_hook(payload)
        result = self.run_hook(payload, debug=True)
        self.assertIn("profile='Codex Mid'", result.stderr)
        self.assertIn("automation diagnostic", result.stderr)
        self.assertNotIn("PRIVATE_PROMPT_CONTENT", result.stderr)
        self.assertNotIn("automation stdout", result.stderr)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_reset_and_invalid_arguments(self):
        for args, expected in (
            (("reset",), ["Basic"]),
            (("reset", "codex"), ["Basic"]),
            (("reset", "claude"), ["ttys999", "Basic"]),
        ):
            self.run_hook(args=args)
            self.assertEqual(self.capture.read_text().splitlines(), ["-", *expected])
        for args in (("bad",), ("reset", "bad\nFORGED"), ("reset", "codex", "extra")):
            result = self.run_hook(args=args, debug=True)
            self.assertFalse(self.capture.exists())
            self.assertNotIn("FORGED", result.stderr)

    def test_missing_jq_and_automation_failure_stay_quiet(self):
        self.env["AUTOMATION_STATUS"] = "1"
        self.run_hook('{"model":"sol"}')
        (self.bin / "jq").unlink()
        self.env["PATH"] = str(self.bin)
        self.run_hook('{"model":"sol"}')
        self.assertFalse(self.capture.exists())

    def test_claude_without_a_tty_does_not_change_another_tab(self):
        self.write_command("ps", '''#!/bin/bash
case "$2" in
  tty=) printf '??\\n' ;;
  ppid=) printf '1\\n' ;;
esac
''')
        for args in ((), ("reset", "claude")):
            with self.subTest(args=args):
                self.run_hook('{"model":"sonnet"}', args=args)
                self.assertFalse(self.capture.exists())

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

    def test_readme_commands_work_with_spaces_in_home(self):
        installed = self.home / "term-profile.sh"
        shutil.copyfile(SCRIPT, installed)
        installed.chmod(0o700)
        for config in readme_hook_configs().values():
            for event, groups in config["hooks"].items():
                for group in groups:
                    for hook in group["hooks"]:
                        with self.subTest(event=event, command=hook["command"]):
                            self.capture.unlink(missing_ok=True)
                            result = subprocess.run(
                                ["/bin/bash", "-c", hook["command"]],
                                input='{"model":"sol"}', text=True,
                                capture_output=True, env=self.env, timeout=5,
                            )
                            self.assertEqual(result.returncode, 0, result.stderr)
                            self.assertEqual(result.stdout + result.stderr, "")
                            self.assertTrue(self.capture.exists())


if __name__ == "__main__":
    unittest.main()
