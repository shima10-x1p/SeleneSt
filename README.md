# SeleneSt

技術調査、原因分析、文書作成、作業改善のスキルとワークフローをまとめた、個人用の開発支援プラグインです。
Codexのプロジェクト設定で有効化し、使用するコミットをプロジェクトごとに固定します。

## 収録内容

| スキル | 用途 |
| --- | --- |
| [technical-discovery](plugins/selenest/skills/technical-discovery/SKILL.md) | 技術や実現方式を調べ、比較して選ぶ |
| [nazenaze](plugins/selenest/skills/nazenaze/SKILL.md) | 問題の原因を枝ごとに掘り下げる |
| [causal-reasoning](plugins/selenest/skills/causal-reasoning/SKILL.md) | 原因・条件・対策・結果のつながりを検証する |
| [document-composition](plugins/selenest/skills/document-composition/SKILL.md) | 文書の目的に沿って情報と構成を決める |
| [writing](plugins/selenest/skills/writing/SKILL.md) | 誤解の生じにくい文に整える |
| [improve-workflow](plugins/selenest/skills/improve-workflow/SKILL.md) | 明示的な依頼に応じて改善候補を記録・試行・採用する |

[技術調査](plugins/selenest/docs/workflows/01_technical-discovery.md)と[文書作成](plugins/selenest/docs/workflows/02_document-writing.md)のワークフローも同梱しています。
対応するスキルから参照できます。

## 配布と適用の仕組み

[プラグイン本体](plugins/selenest/)は、ルートの[plugin.json](plugins/selenest/plugin.json)と、その直下のスキル・ワークフローで構成します。
MCPサーバーやAPIキーは必要ありません。

```text
plugins/selenest/
├── plugin.json
├── skills/
│   ├── technical-discovery/
│   ├── nazenaze/
│   ├── causal-reasoning/
│   ├── document-composition/
│   ├── writing/
│   └── improve-workflow/
└── docs/workflows/
```

[導入スクリプト](scripts/manage_plugin.py)は、導入先に次の3ファイルを作成・更新します。

| 導入先からの相対パス | 内容 |
| --- | --- |
| `.agents/plugins/marketplace.json` | プロジェクト固有のカタログ名、配布元URL、固定SHA |
| `.codex/config.toml` | このプロジェクトでSeleneStを有効にする設定ブロック |
| `.agents/plugins/selenest-install.json` | 導入した版と、管理対象ファイルの変更検出情報 |

カタログ名には初回導入時に生成したUUIDを含めます。更新時にも同じ名前を使います。
Codex 0.163.0では、同じプラグイン名とカタログ名を使うと、別プロジェクトでも後から導入した版を参照しました。
そのため、SHAの固定とカタログ名の分離を併用します。

プラグイン本体のキャッシュはCodexがユーザー領域に保存します。
ユーザー共通の有効化設定は、このスクリプトでは変更しません。
改善記録や成果物は各プロジェクトに保存し、プラグインのキャッシュ内には書きません。

## 導入

必要なものはPython 3.11以降、Git、ローカルのプラグインカタログに対応したCodexです。
導入先は既存のディレクトリを指定します。スクリプトはGitリポジトリの作成やコミットを行いません。
Codex側ではプロジェクトを信頼済みにする必要があります。

配布元のSeleneStをcloneし、そのディレクトリから実行します。
以下の`/absolute/path/to/project`は実際の導入先に置き換えてください。

```bash
git clone https://github.com/shima10-x1p/SeleneSt.git
cd SeleneSt
python3 scripts/manage_plugin.py install /absolute/path/to/project --revision HEAD --dry-run
python3 scripts/manage_plugin.py install /absolute/path/to/project --revision HEAD
```

`--revision`は、このチェックアウト内のタグやコミットを40桁のSHAへ解決します。
未コミットのファイルは配布されません。指定したコミットにはプラグイン本体が含まれ、配布元にpushされている必要があります。
この構成を初めて導入する際も、先に変更をコミットして配布元へpushしてください。
スクリプトはローカルの内容を検査しますが、リモートから取得できるかまでは確認しません。

配布元URLの既定値は、このチェックアウトの`origin`です。
必要な場合は`--repository <Git URL>`で指定できます。認証はGitとCodexの通常の設定を使用し、URLに資格情報を含めないでください。

登録後は、対象プロジェクトでプラグインカタログを再読み込みし、新しいセッションでスキルを確認します。
VS Codeでは対象のCodexセッションを選択し、Agent Customizationsのプラグイン管理画面で確認してください。
画面からユーザー全体へインストール・有効化する操作は、このプロジェクト単位の導入手順には含めません。
画面の利用可否はVS Codeの統合方式に依存します。

Codexでの明示呼び出し例:

```text
$selenest:technical-discovery このプロジェクトの実現方式を比較して
$selenest:document-composition 設計書の構成を見直して
$selenest:improve-workflow 今回の作業を振り返って
```

スキルが一覧に現れない場合、登録完了と読み込み完了を区別してください。
対象プロジェクトの信頼設定、カタログの読み込みエラー、固定SHAへのアクセスを確認します。
既存の同名スキルを直接導入している場合は、二重に使わないよう導入元を確認してください。

## 更新と登録解除

配布元の新しいコミットを取得し、採用する版を指定して更新します。
タグ名は運用時に作成したものを使用できます。以下は取得後のHEADを採用する例です。

```bash
git pull --ff-only
python3 scripts/manage_plugin.py update /absolute/path/to/project --revision HEAD --dry-run
python3 scripts/manage_plugin.py update /absolute/path/to/project --revision HEAD
python3 scripts/manage_plugin.py status /absolute/path/to/project
```

更新後も、対象プロジェクトでカタログを再読み込みして新しいセッションを開始します。
過去の版へ戻す場合は、`update --revision <過去のタグまたはSHA>`を使用します。
`status`は登録ファイルの整合性を確認します。実行中のセッションが使用する版は検査しません。

登録解除は次のコマンドで行います。

```bash
python3 scripts/manage_plugin.py remove /absolute/path/to/project --dry-run
python3 scripts/manage_plugin.py remove /absolute/path/to/project
```

管理対象のカタログ、導入記録、有効化設定ブロックを削除します。
ほかの設定、改善記録、Codexの共有キャッシュは削除しません。

既存の配布カタログがある場合、初回導入は停止します。既存カタログへの自動統合には対応していません。
導入後に管理対象のカタログや設定ブロックが編集されている場合も、更新・解除は停止します。
設定ブロックの外側にあるプロジェクト設定は、そのまま保持します。

導入済み設定をコピーした別ディレクトリやworktreeは、同じカタログ識別名を引き継ぎます。
そこで異なる版を使う場合は、コピー先で登録解除してから再導入し、新しい識別名を作成してください。

## このリポジトリでの開発

スキルを変更するときは、[plugins/selenest/skills](plugins/selenest/skills/)内のファイルを編集します。
[.agents/skills](.agents/skills)は、このディレクトリを指す相対シンボリックリンクです。Codexはこのリンクを通じて開発中のスキルを読み込みます。
このリポジトリ自身には配布版を追加導入しません。
シンボリックリンクを扱わないWindowsのcheckoutでは、WSLを使用するか、Gitのシンボリックリンク対応を有効にしてcheckoutしてください。

配布手順:

1. スキルやワークフローを修正する。
2. [plugin.json](plugins/selenest/plugin.json)の`version`を更新する。
3. テストを実行する。
4. 変更をコミットし、配布元へpushする。必要なら版のタグを付ける。
5. 各プロジェクトで、採用する版へ明示的に更新する。

異なるコミットへの更新で`version`が同じ場合、スクリプトは停止します。
キャッシュ上で同じ版の内容が変わることを避けるためです。

## 検証

標準ライブラリだけで導入スクリプトのテストを実行できます。

```bash
python3 -m unittest discover -s tests -v
```

Codex本体を使う統合テストは、実行ファイルの絶対パスを指定して実行します。

```bash
SELENEST_CODEX_BIN=/absolute/path/to/codex python3 -m unittest discover -s tests -v
```

統合テストは一時的なGitリポジトリとCodex設定を作成し、6スキルの読み込み、ワークフローの同梱、プロジェクトごとの版の分離、片方だけの更新、未導入プロジェクトへの非適用を検証します。
モデルへの推論リクエストや、普段のCodex設定への書き込みは行いません。
Codex 0.163.0のapp-serverで検証しています。VS Code画面の操作を含む自動テストはありません。

仕様の参照先は[OpenAIのプラグイン構成と配布](https://developers.openai.com/plugins/build/plugins)と[VS Codeのプラグイン管理](https://code.visualstudio.com/docs/agent-customization/agent-plugins)です。
