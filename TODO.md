# TODO

更新日: 2026-09-27

## 方針

- 利用条件で明示的に許可されたデータだけを使う。購入・問い合わせはしない
- 課金・規約への同意・アカウント作成・外部への投稿は、あなたの確認なしに行わない

## あなたの操作が必要な項目

- [ ] 公開するかどうか、するならどこに出すかを決める（まだ急がない）

## 実装

- [x] 走者×アウトのマルコフ連鎖による得点分布（[runs.py](src/saikaku/runs.py)）
- [x] NPBルール（12回打ち切り・引き分け・サヨナラ）込みの勝率モデル（[model.py](src/saikaku/model.py)）
- [x] Retrosheetの読み込みと分布の作成コマンド（[retrosheet.py](src/saikaku/retrosheet.py)、[fit.py](src/saikaku/fit.py)）
- [x] 2022〜2024年のRetrosheet公式戦（56.7万遷移）で得点分布を作成（`src/saikaku/data/run_distribution.json`）
- [x] 代替案の自動評価：送りバント・盗塁・敬遠（[tactics.py](src/saikaku/tactics.py)）
- [x] 全場面を触れるデモ画面（`python -m saikaku.demo`）
- [ ] 打者の力量差の扱い（バントする打者は平均より弱い。選択バイアスの補正）
- [ ] 観戦記録の入力形式を決める（1試合1ファイル、Obsidianで書ける形）
- [ ] 試合ごとのレポートをObsidianのノートとして出力する
- [ ] 得点環境をNPB寄りに補正する方法の検討（許可されたNPBの集計値が見つかった場合のみ）

## 保留

- X投稿（公開方針が決まってから）
- 打者・投手個別の補正（推定できるデータがない）
