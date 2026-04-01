# 流星検出システム Meteo に YouTube Live 配信機能を追加した話

年間の主要な流星群をまとめるとこんな感じになる。

| 流星群 | 極大日 | ZHR | 放射点 | 月輝面 |
|---|---|---|---|---|
| しぶんぎ座流星群 | 1月3〜4日 | 80 | うしかい座付近 | 99% |
| こと座流星群 | 4月22〜23日 | 18 | こと座 | 38% |
| みずがめ座η流星群 | 5月5〜6日 | 50 | みずがめ座 | 82% |
| みずがめ座δ南流星群 | 7月30〜31日 | 25 | みずがめ座 | 98% |
| ペルセウス座流星群 | 8月12〜13日 | 100 | ペルセウス座 | 0% |
| オリオン座流星群 | 10月20〜21日 | 20 | オリオン座 | 70% |
| しし座流星群 | 11月17〜18日 | 15 | しし座 | 55% |
| ふたご座流星群 | 12月13〜14日 | 150 | ふたご座 | 20% |
| こぐま座流星群 | 12月21〜22日 | 10 | こぐま座 | — |

ZHR（Zenithal Hourly Rate）は天頂付近での1時間あたりの理論値で、月輝面は2026年の極大日の値。

これを眺めていて、「ライブ配信できたら楽しいんじゃないか」と思った。ペルセウス座流星群は月明かりもなく ZHR が 100 を超える。見ている人と「今の見た！！」をリアルタイムで共有できたら、録画を後で見返すのとはまるで違う体験になるはずだ。ということで、Meteo v3.3.0 で YouTube Live 配信機能を追加した。

## 構成のおさらい

Meteo は RTSP カメラから流星をリアルタイム検出する OSS で、複数カメラをまとめるダッシュボードがある。ライブ映像の中継には go2rtc を使っていて、WebRTC でブラウザに映像を届けている。

```
RTSPカメラ → go2rtc → ブラウザ（WebRTC）
```

go2rtc はブラウザへの中継だけでなく、RTMP 出力もできる。つまり YouTube への配信経路はこうなる。

```
RTSPカメラ → go2rtc → YouTube Live（RTMP）
```

既に go2rtc が間に入っているので、追加の仕組みはほとんど要らないはずだった。

## go2rtc の RTMP 出力、最初にハマった

最初、go2rtc のドキュメントをちゃんと読まずに、こう設定して試した。

```yaml
streams:
  camera3:
    - rtsp://user:pass@10.0.1.11/live
    - "rtmp://a.rtmp.youtube.com/live2/xxxx-xxxx-xxxx-xxxx#output"
```

`#output` をつければ出力先になるという情報を見かけたのだが、何も起きなかった。

go2rtc のログを見ると、そもそもストリームが動いていない。go2rtc はオンデマンド型で、誰かがストリームをリクエストするまで接続を開始しない。なので `#output` を書いても、誰も見ていないあいだは何もしないということだった。

`#always` で常時接続にして試したが、今度は RTMP 出力が起動しなかった。v1.9.14 時点では `#output` 単体での動作がどうも怪しい。

---

改めてドキュメントを読むと、YouTube 向けの配信には `publish` セクションを使う設計になっていた。

```yaml
streams:
  camera3_youtube:
    - "ffmpeg:rtsp://user:pass@10.0.1.11/live#video=copy#audio=aac"

publish:
  camera3_youtube:
    - rtmp://a.rtmp.youtube.com/live2/xxxx-xxxx-xxxx-xxxx
```

`publish` セクションに書いた RTMP 先は、ダッシュボードから API を叩くことで配信が始まる。

```
POST http://localhost:1984/api/streams?src=camera3_youtube&dst=rtmp://a.rtmp.youtube.com/live2/xxxx-xxxx-xxxx-xxxx
```

これで実際に YouTube に映像が届いた。

## ffmpeg 経由にしているのはなぜか

YouTube は H.264 映像 + AAC 音声を要求する。うちのカメラは映像は H.264 だが、音声が PCMA（G.711）で来る。そのままでは YouTube 側で弾かれる。

`ffmpeg:...#video=copy#audio=aac` と書くことで、go2rtc 内蔵の ffmpeg が音声だけ AAC にトランスコードして送ってくれる。映像はコピーなのでほぼ無劣化。

## ダッシュボードへの組み込み

API を直接叩くだけでも動くが、毎回 curl は面倒なのでダッシュボードに開始/停止ボタンを追加した。

設定は `streamers` ファイルに書くだけ。

```
rtsp://user:pass@10.0.1.11/live || 南カメラ | youtube:xxxx-xxxx-xxxx-xxxx
```

4番目のフィールドに `youtube:` プレフィックスでストリームキーを書く。`generate_compose.py` を実行すると `go2rtc.yaml` と `docker-compose.yml` が自動で更新される。

YouTube キーを設定したカメラだけ「YouTube配信」ボタンが出て、他のカメラには出ない。

配信中は「配信中 LIVE」というボタンになってパルスアニメーションが動く。状態は 10 秒おきに go2rtc の API から取得して同期している。

## ストリームキーをブラウザに渡さない

実装で少し気を使ったのは、YouTube のストリームキーをブラウザに送らないこと。

ダッシュボードはカメラ情報を JavaScript の変数に埋め込んでいるが、そのままにするとストリームキーがページのソースに丸見えになる。

```python
def _sanitize_cameras_for_js(cameras):
    result = []
    for cam in cameras:
        safe = {k: v for k, v in cam.items() if k not in ("youtube_key", "rtsp_url")}
        if cam.get("youtube_key"):
            safe["has_youtube_key"] = True
        result.append(safe)
    return result
```

キー本体は渡さず、`has_youtube_key: true` というフラグだけ渡す。ボタンの表示制御はこのフラグで判断して、実際の配信操作はサーバー側でキーを使う。

## go2rtc のボリュームマウントを変えた

もう1つ変えたのが docker-compose.yml の go2rtc のボリューム設定。もともと読み取り専用でマウントしていた。

```yaml
# 変更前
- ./go2rtc.yaml:/config/go2rtc.yaml:ro

# 変更後
- ./go2rtc.yaml:/config/go2rtc.yaml
```

`:ro` があると go2rtc の DELETE API が失敗する。配信停止のために DELETE を叩く必要があるので、書き込み可能にした。go2rtc は設定ファイルを書き換えることはないので、実害はない。

## 複数カメラを同時に YouTube 配信するには

ここで少し詰まった。YouTube は 1 チャンネルにつき同時配信 1 本のみという制限がある。

ただ、1 つの Google アカウントから複数の YouTube チャンネルを作れる。最大 100 チャンネルまで無料で作成できるので、カメラごとにチャンネルを用意してそれぞれのキーを使えば同時配信できる。

```
同じGoogleアカウントで管理
├── 東カメラ用チャンネル → youtube:aaaa-aaaa-aaaa
├── 西カメラ用チャンネル → youtube:bbbb-bbbb-bbbb
└── 南カメラ用チャンネル → youtube:cccc-cccc-cccc
```

チャンネルの有効化に最大 24 時間かかるのが少し面倒だが、一度やってしまえばあとは普通に使える。

## 動かしてみて

火球クラスのイベントが出たとき、YouTube のライブチャットに「今の見た！！」というコメントが来ると、観測の感触がかなり変わる。記録して後で見返すのとは体験が違う。

配信中の映像は普段の検出映像そのままなので、マスク設定や感度はいじらなくていい。go2rtc が間に入っているおかげで、配信用に別途ストリームを用意する手間もない。

実装としては大きくない変更だったが、観測の楽しみ方が少し広がった。

## まとめ

- go2rtc の `publish` セクション + API トリガーで YouTube Live に配信できる
- 音声は ffmpeg で AAC にトランスコードする（YouTube の要件）
- `streamers` ファイルにキーを書くだけで設定が完結する
- ストリームキーはサーバー側だけで持ち、ブラウザに渡さない
- 複数カメラ同時配信は YouTube チャンネルを複数作れば無償でできる

リポジトリはこちら: https://github.com/Masakai/meteo
