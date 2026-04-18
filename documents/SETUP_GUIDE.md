# セットアップマニュアル（初心者向け）v3.11.1

Windows と macOS で、実行環境の作成から動作確認までの手順をまとめています。

## サンプル画面

初回構築後に最初に確認するトップ画面の例です。

<img src="assets/dashboard-sample_1.png" alt="Meteo ダッシュボードのトップ画面サンプル" width="920">

---

## 1. 事前準備

### 共通

- Python 3.11 以上
- インターネット接続（依存ライブラリのインストールに必要）
- ダッシュボードを使う場合は Docker Desktop

### Windows

1. Python をインストール  
   - 公式サイトから Python 3.11 以上を入手  
   - **「Add Python to PATH」** にチェックを入れる
2. ターミナルを開く  
   - `Windows Terminal` または `PowerShell`
3. Docker Desktop をインストール（ダッシュボード利用時）  
   - 公式サイトからインストール  
   - 初回起動時に案内される設定（WSL2等）を完了  
   - インストール後に起動しておく

### macOS

1. Python をインストール  
   - Homebrew がある場合: `brew install python`
2. ターミナルを開く  
   - `Terminal` または `iTerm2`
3. Docker Desktop をインストール（ダッシュボード利用時）  
   - 公式サイトからインストール  
   - インストール後に起動しておく

---

## 2. プロジェクトの準備

```bash
cd /path/to/meteo
```

※ `meteo` の場所は自分の環境に合わせて変更してください。

---

## 3. 仮想環境の作成

### Windows

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

PowerShell で実行ポリシーの警告が出た場合:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
```

---

## 4. 依存ライブラリのインストール

```bash
pip install -r requirements.txt
```

---

## 5. 動作確認（MP4から検出）

```bash
python meteor_detector.py input.mp4
```

### Web版と同じ検出ロジックで再検証したい場合

```bash
python meteor_detector.py input.mp4 --realtime
```

マスクを使う場合:

```bash
python meteor_detector.py input.mp4 --realtime \
  --mask-image /path/to/mask.png
```

---

## 6. RTSPストリーム（Webプレビュー）

```bash
python meteor_detector_rtsp_web.py rtsp://192.0.2.100:554/stream --web-port 8080
```

ブラウザで開く:

```
http://localhost:8080/
```

---

## 7. ダッシュボードUI（Docker）

複数カメラの検出状況をまとめて表示するダッシュボードは Docker で起動します。

### 7-1. streamers ファイルを設定

`streamers` に RTSP URL を1行1カメラで記載します。
`|` 区切りでマスク画像、表示名、YouTube配信キーも指定可能です。

```
rtsp://user:pass@192.0.2.25/live | camera1.jpg | 東カメラ
rtsp://user:pass@192.0.2.3/live  || 西カメラ
rtsp://user:pass@192.0.2.11/live || 南カメラ | youtube:xxxx-xxxx-xxxx-xxxx
```

!!! warning "認証情報を平文コミットしない"
    `streamers` は RTSP の `user:pass` を平文で含むため、`.gitignore` 対象（`streamers` / `streamers.sample` と別ファイル）のまま運用してください。公開リポジトリへコミットした場合は、カメラ側でパスワードを変更し、Git 履歴から削除してください。環境変数化したい場合は [CONFIGURATION_GUIDE.md](CONFIGURATION_GUIDE.md) の「.env ファイルを使用」節を参照してください。

YouTube Liveに配信したいカメラは、4番目のフィールドに `youtube:` に続けてストリームキーを記載します。ストリームキーはYouTube Studioのライブ配信設定画面で取得できます。

#### カメラ識別子について（v3.11.0+）

v3.11.0 以降、`generate_compose.py` は各カメラの内部名を **`camera1` / `camera2` / `camera3` ... に固定** で書き出します（IP や streamers 記載順序に関わらず記載順で振られるインデックスのみを使用）。

- 保存先ディレクトリは `detections/camera1/` のように `camera{i}` に統一されます
- `streamers` の「表示名」フィールドはダッシュボード UI のラベルにのみ使用され、ディレクトリ名やファイル名には使われません
- 旧バージョン（〜v3.10.x）で作成された IP 含みディレクトリ（例: `camera1_10_0_1_25/`）がある場合は [OPERATIONS_GUIDE.md の「v3.11.0 → カメラ名インデックス化アップデート」節](OPERATIONS_GUIDE.md#v3110--カメラ名インデックス化アップデート) を参照し、`migrate_camera_dirs.py` で移行してください。

### 7-2. docker-compose.yml を生成

```bash
python3 generate_compose.py

# WebRTCライブ表示を使う場合
python3 generate_compose.py --streaming-mode webrtc
```

`--streaming-mode webrtc` を使うと `go2rtc` コンテナ用の設定も同時に生成されます。`go2rtc` の `webrtc.candidates` は既定でローカル IP を自動検出し、必要なら `--go2rtc-candidate-host <host-ip>` で上書きできます。

### 7-3. meteor-docker.sh で起動

```bash
./meteor-docker.sh start
```

### 7-4. ブラウザでダッシュボード表示

```
http://localhost:8080/
```

カメラライブ画面では「録画予約」UIから手動録画（開始時刻・録画秒数を指定）ができます。録画ファイルは `detections/<カメラ名>/manual_recordings/` 以下に MP4 形式で保存され、完了後にサムネイル JPEG が自動生成されます。

終了する場合:

```bash
./meteor-docker.sh stop
```

ログ確認:

```bash
./meteor-docker.sh logs
./meteor-docker.sh logs camera1
```

docker-compose.yml 再生成:

```bash
./meteor-docker.sh generate
```

---

## 8. よくあるエラー

### `ModuleNotFoundError: No module named 'astral'`

依存が入っていない可能性があります。以下を実行してください。

```bash
pip install astral
```

### `No module named 'cv2'`

OpenCV が入っていません。以下を実行してください。

```bash
pip install opencv-python
```

---

## 9. 終了方法

実行中は `Ctrl + C` で終了できます。

---

## 参考ドキュメント

用途別に詳細はこちらを参照してください。

- `README.md` - 全体概要、基本コマンド、Docker構成の全体像
- `documents/CONFIGURATION_GUIDE.md` - 各種設定・環境変数一覧
- `documents/OPERATIONS_GUIDE.md` - 運用手順、ログ確認、ディスク管理
- `documents/DOCKER_ARCHITECTURE.md` - Docker構成・ディレクトリ構造の詳細
- `documents/API_REFERENCE.md` - ダッシュボードAPI仕様
- `documents/DETECTION_TUNING.md` - 検出パラメータの調整方法
