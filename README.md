# 采配採点

プロ野球（NPB）の采配を、結果ではなく**意思決定の時点で勝利確率をどれだけ動かしたか**で評価します。

## 評価の考え方

`実際に選んだ作戦による勝率変化 − 代替案による勝率変化`

プラスなら、その場面では選んだ作戦のほうが勝利確率を高める方向だった、という意味です。

## 勝率モデル

半イニングを「走者×アウト」の24状態を移るマルコフ連鎖とみなし、状態ごとの残り得点分布を実データから推定します（[runs.py](src/saikaku/runs.py)）。その分布とNPBのルールを組み合わせて、試合終了までを計算します（[model.py](src/saikaku/model.py)）。NPBのルールとは、9回裏はホームがリードしていれば行わない、サヨナラで終了、12回終了で同点なら引き分け、の3点です。

- 両チームをリーグ平均として扱います。打者・投手・球場の補正は、推定できるようになるまで入れません
- 引き分けは勝ち0.5として評価します（NPBの勝率計算は引き分けを除くため）
- 得点分布はMLB（Retrosheet）のデータから推定しており、NPBの得点環境との差は未補正です。詳細は [DATA_SOURCES.md](DATA_SOURCES.md) を参照してください

## 実行

Python 3.11以上が必要です。

```powershell
# 得点分布を作る（初回とデータ更新時）。zipは %LOCALAPPDATA%\Saikaku\retrosheet に置く
$env:PYTHONPATH = "src"
python -m saikaku.fit "$env:LOCALAPPDATA\Saikaku\retrosheet\2024plays.zip"

# 采配を1件採点する
python -m saikaku.cli samples/decision.json

python -m pytest
```

## 出典

The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at "www.retrosheet.org".
