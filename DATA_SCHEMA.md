# データ設計の初期案

無料データだけで先に作れる、試合後の采配評価用レコードです。元サイトの文章やHTMLを保存せず、分析に必要な構造化項目と出典情報だけを保存します。

## `games`

| 項目 | 型 | 内容 |
| --- | --- | --- |
| `game_id` | string | 公式試合ページに対応する内部ID |
| `game_date` | date | 試合日 |
| `home_team` | string | ホームチーム |
| `away_team` | string | ビジターチーム |
| `home_score` | integer | ホーム得点 |
| `away_score` | integer | ビジター得点 |
| `status` | enum | `速報` / `確定` |
| `source_url` | string | 出典ページ |
| `retrieved_at` | datetime | 取得日時 |

## `decision_events`

| 項目 | 型 | 内容 |
| --- | --- | --- |
| `decision_id` | string | 自作イベントID |
| `game_id` | string | `games.game_id` |
| `team` | string | 判断したチーム |
| `inning` | integer | イニング |
| `half` | enum | `表` / `裏` |
| `outs` | integer | 判断直前アウト数 |
| `score_diff` | integer | 判断チームから見た点差 |
| `runners` | object | 一塁・二塁・三塁の有無 |
| `decision_type` | enum | バント、盗塁、代打、敬遠、継投など |
| `observed_action` | string | 実際に行ったこと |
| `alternative_action` | string | 比較する代替案 |
| `model_version` | string | 採点モデルのバージョン |
| `review_status` | enum | `未確認` / `確認済み` / `要修正` |

## 保存ルール

- 生HTML、実況文、画像、ロゴは保存しない
- 取得元URLと取得日時を必ず残す
- 速報値は確定値で上書きせず、訂正履歴を残す
- 采配イベントが推定・手入力の場合は、その事実を記録する
- 有料データを導入する場合は、契約で許可された保存項目だけを追加する
