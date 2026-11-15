#!/usr/bin/env python3
"""Register a pinned SeleneSt plugin in one project using only standard libraries."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib
import uuid


SOURCE_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PATH = "plugins/selenest"
MARKETPLACE = Path(".agents/plugins/marketplace.json")
STATE = Path(".agents/plugins/selenest-install.json")
CONFIG = Path(".codex/config.toml")
BEGIN = "# BEGIN SELENEST MANAGED PLUGIN"
END = "# END SELENEST MANAGED PLUGIN"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def git(*args):
    result = subprocess.run(
        ["git", "-C", str(SOURCE_ROOT), *args], capture_output=True, text=True
    )
    if result.returncode:
        raise ValueError(f"Gitの確認に失敗しました: {' '.join(args)}\n{result.stderr.strip()}")
    return result.stdout.strip()


def release(revision, repository):
    sha = git("rev-parse", "--verify", "--end-of-options", revision + "^{commit}")
    manifest = json.loads(git("show", f"{sha}:{PLUGIN_PATH}/plugin.json"))
    if manifest.get("name") != "selenest":
        raise ValueError("指定したコミットにSeleneStのプラグインがありません。")
    version = manifest.get("version", "")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", version):
        raise ValueError("プラグインのversionがSemVer形式ではありません。")
    source = repository or git("remote", "get-url", "origin")
    if not source or "\n" in source or source.startswith("-"):
        raise ValueError("有効な配布元リポジトリを指定してください。")
    return sha, version, source


def read_files(target):
    snapshots = {}
    for relative in (MARKETPLACE, STATE, CONFIG):
        path = target
        for part in relative.parts:
            path /= part
            if path.is_symlink():
                raise ValueError(f"導入先のシンボリックリンクは変更しません: {path}")
        if path.exists() and not path.is_file():
            raise ValueError(f"ファイルではありません: {path}")
        snapshots[relative] = path.read_bytes() if path.exists() else None
    return snapshots


def block_bounds(text):
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise ValueError("管理用の設定ブロックが欠けているか重複しています。")
    start = text.index(BEGIN)
    end = text.index(END) + len(END)
    if end <= start:
        raise ValueError("管理用の設定ブロックの順序が不正です。")
    if text[end:end + 1] == "\n":
        end += 1
    return start, end


def load_state(snapshots):
    if snapshots[STATE] is None:
        raise ValueError("このプロジェクトには未導入です。installを使用してください。")
    state = json.loads(snapshots[STATE])
    if state.get("schema_version") != 1:
        raise ValueError("導入記録の形式に対応していません。")
    name = state.get("marketplace_name", "")
    if not re.fullmatch(r"selenest-project-[0-9a-f]{32}", name):
        raise ValueError("導入記録のカタログ名が不正です。")
    if snapshots[MARKETPLACE] is None or digest(snapshots[MARKETPLACE]) != state["marketplace_sha256"]:
        raise ValueError("配布カタログが導入後に編集されています。変更を確認してから再実行してください。")
    text = (snapshots[CONFIG] or b"").decode()
    start, end = block_bounds(text)
    if digest(text[start:end].encode()) != state["config_block_sha256"]:
        raise ValueError("管理用の設定ブロックが編集されています。自動で上書きしません。")
    tomllib.loads(text)
    return state


def plan(target, action, revision=None, repository=None):
    snapshots = read_files(target)
    text = (snapshots[CONFIG] or b"").decode()
    tomllib.loads(text)
    if action == "install":
        if snapshots[STATE] is not None:
            raise ValueError("導入済みです。版の変更にはupdateを使用してください。")
        if snapshots[MARKETPLACE] is not None:
            raise ValueError("既存の配布カタログがあります。統合方法を確認するまで変更しません。")
        if BEGIN in text or END in text:
            raise ValueError("導入記録のない管理用の設定ブロックがあります。")
        name = "selenest-project-" + uuid.uuid4().hex
        config_existed = snapshots[CONFIG] is not None
    else:
        previous = load_state(snapshots)
        name = previous["marketplace_name"]
        config_existed = previous["config_existed"]
        if action == "status":
            return snapshots, {}, previous
        if action == "remove":
            start, end = block_bounds(text)
            remaining = text[:start] + text[end:]
            tomllib.loads(remaining)
            config = remaining.encode() if config_existed or remaining.strip() else None
            return snapshots, {CONFIG: config, MARKETPLACE: None, STATE: None}, previous
        repository = repository or previous["repository"]

    sha, version, repository = release(revision, repository)
    if action == "update" and previous["sha"] != sha and previous["plugin_version"] == version:
        raise ValueError("異なるコミットを同じversionで配布できません。配布元のversionを更新してください。")
    block = f'{BEGIN}\n[plugins."selenest@{name}"]\nenabled = true\n{END}\n'
    if action == "install":
        text = text + ("\n" if text and not text.endswith("\n") else "") + block
    else:
        start, end = block_bounds(text)
        text = text[:start] + block + text[end:]
    parsed = tomllib.loads(text)
    if parsed["plugins"][f"selenest@{name}"] != {"enabled": True}:
        raise ValueError("既存設定とプラグイン設定が競合しています。")
    catalog = json_bytes({
        "name": name,
        "plugins": [{
            "name": "selenest",
            "source": {"source": "git-subdir", "url": repository, "path": "./" + PLUGIN_PATH, "sha": sha},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity",
        }],
    })
    state = {
        "schema_version": 1,
        "marketplace_name": name,
        "repository": repository,
        "sha": sha,
        "plugin_version": version,
        "marketplace_sha256": digest(catalog),
        "config_block_sha256": digest(block.encode()),
        "config_existed": config_existed,
    }
    return snapshots, {MARKETPLACE: catalog, CONFIG: text.encode(), STATE: json_bytes(state)}, state


def replace_file(path, content):
    if content is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, temporary = tempfile.mkstemp(prefix=".selenest-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def apply(target, snapshots, changes):
    if read_files(target) != snapshots:
        raise ValueError("確認中に設定が変更されたため中止しました。")
    completed = []
    try:
        for relative, content in changes.items():
            if snapshots[relative] != content:
                replace_file(target / relative, content)
                completed.append(relative)
    except OSError:
        for relative in reversed(completed):
            replace_file(target / relative, snapshots[relative])
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("install", "update", "status", "remove"):
        command = sub.add_parser(action)
        command.add_argument("target", type=Path, help="既存のプロジェクトディレクトリ")
        if action in ("install", "update"):
            command.add_argument("--revision", required=True, help="このチェックアウトで解決できるタグまたはコミット")
            command.add_argument("--repository", help="配布元Git URL。初回の既定値はorigin")
        if action != "status":
            command.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        target = args.target.resolve(strict=True)
        if not target.is_dir():
            raise ValueError("プロジェクトディレクトリを指定してください。")
        before, changes, state = plan(target, args.action, getattr(args, "revision", None), getattr(args, "repository", None))
        print(f"対象: {target}\nカタログ: {state['marketplace_name']}\n版: {state['plugin_version']}\nSHA: {state['sha']}")
        if args.action == "status":
            print("登録内容と管理ファイルの整合性を確認しました。実行中のCodexへの反映状況は別途確認してください。")
            return 0
        changed = [p for p, content in changes.items() if before[p] != content]
        for path in changed:
            print(f"{'削除' if changes[path] is None else '書き込み'}: {path}")
        if args.dry_run:
            print("dry-run: ファイルは変更していません。")
        else:
            apply(target, before, changes)
            print("登録を更新しました。対象プロジェクトでカタログを再読み込みし、新しいセッションで確認してください。" if changed else "変更はありません。")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
