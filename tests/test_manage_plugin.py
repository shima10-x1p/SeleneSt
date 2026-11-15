import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("manage_plugin", ROOT / "scripts/manage_plugin.py")
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


def make_source(root):
    source = root / "source"
    shutil.copytree(ROOT / "plugins", source / "plugins")
    shutil.copytree(ROOT / "scripts", source / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    def git(*args):
        return subprocess.run(["git", "-C", str(source), *args], check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-q")
    revisions = []
    for version in ("0.1.0", "0.2.0"):
        manifest = source / "plugins/selenest/plugin.json"
        data = json.loads(manifest.read_text())
        data["version"] = version
        manifest.write_text(json.dumps(data))
        marker = source / "plugins/selenest/skills/writing/SKILL.md"
        marker.write_text(marker.read_text() + f"\nFixture release {version}.\n")
        git("add", ".")
        git("-c", "user.name=SeleneSt test", "-c", "user.email=test@example.invalid", "commit", "-qm", version)
        revisions.append(git("rev-parse", "HEAD"))
    return source, revisions


class InstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="selenest-tests-")
        cls.root = Path(cls.directory.name)
        cls.source, cls.revisions = make_source(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.project = Path(tempfile.mkdtemp(dir=self.root))
        self.patcher = patch.object(manager, "SOURCE_ROOT", self.source)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def change(self, action, revision=None, target=None):
        target = target or self.project
        snapshots, changes, state = manager.plan(target, action, revision, self.source.as_uri())
        manager.apply(target, snapshots, changes)
        return state

    def test_project_ids_and_existing_config_are_preserved(self):
        config = self.project / manager.CONFIG
        config.parent.mkdir()
        original = b'# project setting\nmodel = "example-model"\n'
        config.write_bytes(original)
        a = self.change("install", self.revisions[0])
        other = Path(tempfile.mkdtemp(dir=self.root))
        b = self.change("install", self.revisions[1], other)
        self.assertNotEqual(a["marketplace_name"], b["marketplace_name"])
        self.assertTrue(config.read_bytes().startswith(original))
        parsed = tomllib.loads(config.read_text())
        self.assertEqual(parsed["model"], "example-model")
        self.assertTrue(parsed["plugins"]["selenest@" + a["marketplace_name"]]["enabled"])
        self.assertEqual(json.loads((self.project / manager.MARKETPLACE).read_bytes())["plugins"][0]["source"]["sha"], self.revisions[0])

    def test_update_and_remove_preserve_unrelated_edits(self):
        initial = self.change("install", self.revisions[0])
        config = self.project / manager.CONFIG
        config.write_text(config.read_text() + '\n[plugins."other@example"]\nenabled = false\n')
        updated = self.change("update", self.revisions[1])
        self.assertEqual(initial["marketplace_name"], updated["marketplace_name"])
        self.assertEqual(updated["sha"], self.revisions[1])
        snapshots, changes, _ = manager.plan(self.project, "update", self.revisions[1])
        self.assertEqual(snapshots, changes)
        self.change("remove")
        self.assertEqual(tomllib.loads(config.read_text()), {"plugins": {"other@example": {"enabled": False}}})
        self.assertFalse((self.project / manager.STATE).exists())
        self.assertFalse((self.project / manager.MARKETPLACE).exists())

    def test_remove_deletes_new_empty_config(self):
        self.change("install", self.revisions[0])
        self.change("remove")
        self.assertFalse((self.project / manager.CONFIG).exists())

    def test_existing_marketplace_is_not_overwritten(self):
        catalog = self.project / manager.MARKETPLACE
        catalog.parent.mkdir(parents=True)
        catalog.write_text('{"name":"existing","plugins":[]}')
        before = manager.read_files(self.project)
        with self.assertRaisesRegex(ValueError, "既存の配布カタログ"):
            self.change("install", self.revisions[0])
        self.assertEqual(before, manager.read_files(self.project))

    def test_modified_managed_files_block_update_and_remove(self):
        self.change("install", self.revisions[0])
        original = manager.read_files(self.project)
        for relative in (manager.CONFIG, manager.MARKETPLACE):
            with self.subTest(relative=relative):
                (self.project / relative).write_bytes(original[relative].replace(b"true", b"false") if relative == manager.CONFIG else original[relative] + b"\n")
                before = manager.read_files(self.project)
                for action in ("update", "remove"):
                    with self.assertRaises(ValueError):
                        self.change(action, self.revisions[1])
                self.assertEqual(before, manager.read_files(self.project))
                (self.project / relative).write_bytes(original[relative])

    def test_invalid_revision_and_toml_do_not_write(self):
        with self.assertRaises(ValueError):
            self.change("install", "missing-revision")
        self.assertEqual(list(self.project.iterdir()), [])
        config = self.project / manager.CONFIG
        config.parent.mkdir()
        config.write_text("[invalid")
        with self.assertRaises(ValueError):
            self.change("install", self.revisions[0])
        self.assertFalse((self.project / manager.STATE).exists())

    def test_symlink_destination_is_rejected(self):
        outside = Path(tempfile.mkdtemp(dir=self.root))
        (self.project / ".agents").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "シンボリックリンク"):
            self.change("install", self.revisions[0])
        self.assertEqual(list(outside.iterdir()), [])

    def test_failed_write_rolls_back_files(self):
        before, changes, _ = manager.plan(self.project, "install", self.revisions[0], self.source.as_uri())
        real = manager.replace_file
        def fail_config(path, content):
            if path == self.project / manager.CONFIG:
                raise OSError("simulated write failure")
            real(path, content)
        with patch.object(manager, "replace_file", side_effect=fail_config):
            with self.assertRaises(OSError):
                manager.apply(self.project, before, changes)
        self.assertEqual(before, manager.read_files(self.project))

    def test_cli_dry_run_and_install(self):
        args = ["python3", str(self.source / "scripts/manage_plugin.py"), "install", str(self.project), "--revision", self.revisions[0], "--repository", self.source.as_uri()]
        result = subprocess.run(args + ["--dry-run"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.project.iterdir()), [])
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(manager.load_state(manager.read_files(self.project))["sha"], self.revisions[0])

    def test_new_sha_with_same_version_is_rejected(self):
        self.change("install", self.revisions[1])
        subprocess.run(["git", "-C", str(self.source), "-c", "user.name=SeleneSt test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "same version"], check=True, capture_output=True)
        before = manager.read_files(self.project)
        with self.assertRaisesRegex(ValueError, "同じversion"):
            self.change("update", "HEAD")
        self.assertEqual(before, manager.read_files(self.project))


class PackageTests(unittest.TestCase):
    def test_links_are_self_contained(self):
        root = (ROOT / "plugins/selenest").resolve()
        for path in root.rglob("*"):
            self.assertFalse(path.is_symlink(), str(path))
            if path.suffix == ".md":
                for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
                    if "://" in target or target.startswith("#"):
                        continue
                    resolved = (path.parent / target.split("#")[0]).resolve()
                    self.assertTrue(resolved.is_relative_to(root), f"{path}: {target}")
                    self.assertTrue(resolved.exists(), f"{path}: {target}")


if __name__ == "__main__":
    unittest.main()
