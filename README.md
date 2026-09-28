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

## 采配の評価

選んだ作戦と代替案それぞれについて、直後の場面の分布から期待勝率を出して比べます（[tactics.py](src/saikaku/tactics.py)）。実際の結果は評価に使いません。

| 采配 | 選んだ作戦 | 代替案 |
| --- | --- | --- |
| 送りバント | バントを試みた打席の結果（バント安打・失敗を含む） | 通常打撃 |
| 二盗・三盗 | 単独の盗塁企図の結果 | 自重（その場面のまま） |
| 敬遠 | 打者が一塁へ、押し出される走者だけ進む | 勝負（通常打撃） |

継投と代打は、選手ごとの能力を推定できないため対象外です。観測が50件未満の場面は推定しません。バントをするのは打撃の弱い打者が多いため、平均的な打者の通常打撃と比べるとバント側にやや甘く出ます。

## 実行

Python 3.11以上が必要です。

```powershell
# 得点分布を作る（初回とデータ更新時）。zipは %LOCALAPPDATA%\Saikaku\retrosheet に置く
$env:PYTHONPATH = "src"
python -m saikaku.fit "$env:LOCALAPPDATA\Saikaku\retrosheet\2024plays.zip"

# 采配を1件採点する
python -m saikaku.cli samples/decision.json

# デモ画面を作る（demo/index.html。ブラウザで直接開ける）
python -m saikaku.demo

python -m pytest
```

## 出典

The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at "www.retrosheet.org".
