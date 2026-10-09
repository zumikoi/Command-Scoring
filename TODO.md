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
- [x] 打者・投手の力の反映（型と成績の手入力、打順3人先まで。[abilities.py](src/saikaku/abilities.py)、[events.py](src/saikaku/events.py)）
- [x] 代打・継投の評価
- [x] 左右の相性と、打者×投手の対戦成績（効き具合は翌年予測で測定）
- [ ] 対戦成績の効き具合を年数を増やして測り直す（今は2022〜23→2024の1回だけ。追加ダウンロードは保留中）
- [ ] 走者の足の速さ（盗塁・バントの結果を走者別に補正）
- [ ] 継投の評価を3人先より先（その回の残り・次の回）まで広げる
- [ ] 観戦記録の入力形式を決める（1試合1ファイル、Obsidianで書ける形）
- [ ] 試合ごとのレポートをObsidianのノートとして出力する
- [ ] 得点環境をNPB寄りに補正する方法の検討（許可されたNPBの集計値が見つかった場合のみ）

## 保留

- X投稿（公開方針が決まってから）
