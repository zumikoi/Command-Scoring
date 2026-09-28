# 采配採点 — 引き継ぎ

作業再開用のメモ。ユーザー向けの説明は `README.md`、残作業は `TODO.md`。

## ゴール

NPBの采配を、意思決定時点の勝利確率の変化で採点する。できる範囲でやる。

## 守ること

- 利用条件で**明示的に許可された**データだけを使う。候補と不採用理由は `DATA_SOURCES.md`。購入・問い合わせはしない（2026-09-27 ユーザー決定）
- NPB.jpやSPAIAなどから自動取得しない
- Retrosheet由来の数値を出すときは帰属表示を必ず付ける（`retrosheet.ATTRIBUTION`）
- 外部への投稿、課金、規約への同意はユーザーの確認を取ってから

## 構成

| ファイル | 役割 |
| --- | --- |
| `src/saikaku/runs.py` | 状態遷移の集計と、半イニングの残り得点分布（マルコフ連鎖） |
| `src/saikaku/model.py` | `GameState`、NPBルールの勝率モデル |
| `src/saikaku/retrosheet.py` | Retrosheet `<年>plays.zip` の読み込み |
| `src/saikaku/fit.py` | `src/saikaku/data/` の `run_distribution.json` と `tactics.json` を作る |
| `src/saikaku/tactics.py` | 作戦ごとの結果の分布（`tactics.json`）と、選んだ作戦と代替案の比較 |
| `src/saikaku/decisions.py`, `cli.py`, `report.py` | 采配1件の採点と表示 |
| `src/saikaku/demo.py`, `demo_template.html` | 全場面を事前計算した単一HTMLのデモ（`demo/` は生成物で git 対象外） |

## データの置き場所

生データはVaultの外に置く（OneDrive同期とObsidianの索引を汚さないため）。

- `%LOCALAPPDATA%\Saikaku\retrosheet\<年>plays.zip`（1年あたり約7MB）
- 派生した得点分布のJSON（小さい）だけをリポジトリにコミットする

## 実行

```
$env:PYTHONPATH = "src"
python -m saikaku.fit "$env:LOCALAPPDATA\Saikaku\retrosheet\2024plays.zip"
python -m saikaku.cli samples/decision.json
python -m saikaku.demo   # プレビューは .claude/launch.json の demo
python -m pytest
```

pytestはキャッシュを作らない設定にしてある（`pyproject.toml`）。
