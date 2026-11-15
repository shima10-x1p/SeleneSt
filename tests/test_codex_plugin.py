"""Optional offline integration test against an installed Codex app-server."""

import json
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from test_manage_plugin import make_source, manager


class AppServer:
    def __init__(self, binary, profile, cwd):
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(profile)
        self.log = tempfile.TemporaryFile()
        self.process = subprocess.Popen([binary, "app-server", "--stdio"], cwd=cwd, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True, bufsize=1)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.sequence = 0
        try:
            self.call("initialize", {"clientInfo": {"name": "selenest-test", "version": "0.1.0"}, "capabilities": {"experimentalApi": True}})
            self.process.stdin.write('{"method":"initialized"}\n')
            self.process.stdin.flush()
        except Exception:
            self.close()
            raise

    def call(self, method, params):
        self.sequence += 1
        self.process.stdin.write(json.dumps({"id": self.sequence, "method": method, "params": params}) + "\n")
        self.process.stdin.flush()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if not self.selector.select(1):
                continue
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError("Codex app-server exited")
            response = json.loads(line)
            if response.get("id") == self.sequence:
                if "error" in response:
                    raise RuntimeError(response["error"])
                return response["result"]
        raise TimeoutError(method)

    def close(self):
        self.process.terminate()
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()
        self.selector.close()
        self.log.close()


@unittest.skipUnless(os.environ.get("SELENEST_CODEX_BIN"), "SELENEST_CODEX_BIN is not set")
class CodexIntegrationTests(unittest.TestCase):
    def test_project_scopes_versions_and_update(self):
        with tempfile.TemporaryDirectory(prefix="selenest-codex-test-") as temporary:
            root = Path(temporary)
            source, revisions = make_source(root)
            projects = [root / name for name in ("a", "b", "unused")]
            for project in projects:
                project.mkdir()
                if project.name != "b":
                    subprocess.run(["git", "init", "-q", str(project)], check=True)
            with patch.object(manager, "SOURCE_ROOT", source):
                for project in projects[:2]:
                    before, changes, _ = manager.plan(project, "install", revisions[0], source.as_uri())
                    manager.apply(project, before, changes)
                profile = root / "profile"
                profile.mkdir()
                config = "\n".join(f'[projects.{json.dumps(str(p))}]\ntrust_level = "trusted"\n' for p in projects)
                (profile / "config.toml").write_text(config)
                server = AppServer(os.environ["SELENEST_CODEX_BIN"], profile, projects[0])
                try:
                    def refresh(project):
                        result = server.call("plugin/list", {"cwds": [str(project)], "marketplaceKinds": ["local"], "forceRefetch": True})
                        self.assertEqual(result["marketplaceLoadErrors"], [])
                    def skills(project):
                        result = server.call("skills/list", {"cwds": [str(project)], "forceReload": True})
                        self.assertEqual(result["data"][0]["errors"], [])
                        return [s for s in result["data"][0]["skills"] if s.get("pluginId")]
                    for project in projects[:2]:
                        refresh(project)
                        self.assertEqual(len(skills(project)), 6)
                    before, changes, _ = manager.plan(projects[1], "update", revisions[1])
                    manager.apply(projects[1], before, changes)
                    refresh(projects[1])
                    for project, version in zip(projects[:2], ("0.1.0", "0.2.0")):
                        loaded = skills(project)
                        self.assertEqual(len(loaded), 6)
                        self.assertTrue(all(f"/{version}/" in s["path"] for s in loaded))
                        writing = next(s for s in loaded if s["name"] == "selenest:writing")
                        self.assertIn(f"Fixture release {version}.", Path(writing["path"]).read_text())
                        plugin_root = Path(writing["path"]).parents[2]
                        self.assertTrue((plugin_root / "docs/workflows/01_technical-discovery.md").is_file())
                    self.assertEqual(skills(projects[2]), [])
                    self.assertEqual((profile / "config.toml").read_text(), config)
                finally:
                    server.close()


if __name__ == "__main__":
    unittest.main()
