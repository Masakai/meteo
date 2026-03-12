# 流星検出システム インストールマニュアル (macOS)

## 前提条件

インストールを開始する前に、以下のソフトウェアをインストールしてください：

### 1. Docker Desktop

Docker Desktop for Mac をインストールします。

1. [Docker Desktop](https://www.docker.com/products/docker-desktop) にアクセス
2. "Download for Mac" をクリック
3. ダウンロードした `.dmg` ファイルを開いてインストール
4. Docker Desktop を起動し、メニューバーにDockerアイコンが表示されることを確認

**確認方法:**
```bash
docker --version
docker compose version
```

### 2. Python 3

macOS には Python 2 がプリインストールされていますが、Python 3 が必要です。

**Homebrew経由でのインストール（推奨）:**
```bash
# Homebrewがインストールされていない場合
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Python 3をインストール
brew install python3
```

**確認方法:**
```bash
python3 --version
```

Python 3.8 以上が推奨されます。

---

## インストール方法

### オプション A: 自動インストール（推奨）

ターミナルで以下のコマンドを実行します：

```bash
curl -fsSL https://raw.githubusercontent.com/[YOUR-USERNAME]/meteor-detector/master/install.sh | bash
```

※ `[YOUR-USERNAME]` は実際のGitHubユーザー名に置き換えてください

インストーラが対話的に以下の情報を尋ねます：

1. **観測地点の情報**
   - 緯度（例: 35.6895）
   - 経度（例: 139.6917）
   - タイムゾーン（デフォルト: Asia/Tokyo）

2. **カメラの台数**（1〜10台）

3. **各カメラの情報**
   - カメラ名（英数字、例: camera1）
   - 表示名（日本語可、例: カメラ1）
   - RTSP URL（例: rtsp://admin:password@192.168.1.100/live）

### オプション B: 手動インストール

#### 1. リポジトリのクローン

```bash
cd ~
git clone https://github.com/[YOUR-USERNAME]/meteor-detector.git
cd meteor-detector
```

#### 2. Python仮想環境のセットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

#### 3. Docker Compose設定ファイルの作成

サンプルファイルをコピーして編集します：

```bash
cp docker-compose.yml.sample docker-compose.yml
```

エディタで `docker-compose.yml` を開き、以下の項目を編集します：

- `LATITUDE`: 観測地点の緯度
- `LONGITUDE`: 観測地点の経度
- `TIMEZONE`: タイムゾーン（例: Asia/Tokyo）
- `RTSP_URL`: 各カメラのRTSP URL
- `CAMERA_NAME`: 各カメラの識別名
- `CAMERA_NAME_DISPLAY`: 各カメラの表示名

**カメラを増減する場合:**
- カメラを追加する場合は、既存のカメラセクションをコピーして設定を変更
- ポート番号を重複しないように変更（8081, 8082, 8083...）
- `dashboard` の `depends_on` と環境変数にも追加

#### 4. 必要なディレクトリの作成

```bash
mkdir -p detections masks
```

---

## 起動方法

### 1. インストールディレクトリに移動

```bash
cd ~/meteor-detector
```

### 2. Dockerコンテナの起動

```bash
docker compose up -d
```

初回起動時はDockerイメージのビルドに5〜10分程度かかります。

### 3. 動作確認

ブラウザで以下のURLにアクセスします：

- **ダッシュボード**: http://localhost:8080
- **カメラ1**: http://localhost:8081
- **カメラ2**: http://localhost:8082
- **カメラ3**: http://localhost:8083

---

## 基本的な操作

### システムの停止

```bash
cd ~/meteor-detector
docker compose down
```

### システムの再起動

```bash
cd ~/meteor-detector
docker compose restart
```

### ログの確認

```bash
# 全コンテナのログを確認
docker compose logs -f

# 特定のカメラのログのみ確認
docker compose logs -f camera1
```

### 検出結果の確認

検出された流星の画像と動画は `detections/` ディレクトリに保存されます：

```bash
cd ~/meteor-detector
ls -lh detections/
```

### YouTubeアップロードの有効化

検出一覧から YouTube へアップロードするには、Google OAuth のクライアントシークレットとトークンを用意します。

```bash
source .venv/bin/activate
pip install -r requirements.txt
python authorize_youtube.py \
  --client-secrets ./client_secret.json \
  --token-file ./youtube_token.json
```

その後、ダッシュボード起動前に次を設定します。

```bash
export YOUTUBE_CLIENT_SECRETS_FILE=./client_secret.json
export YOUTUBE_TOKEN_FILE=./youtube_token.json
export YOUTUBE_PRIVACY_STATUS=unlisted
export YOUTUBE_CATEGORY_ID=22
```

---

## マスク画像の設定（オプション）

カメラに映り込む固定の障害物（木の枝、建物など）をマスクして、誤検出を減らすことができます。

### 1. マスク画像の作成

```bash
cd ~/meteor-detector
source .venv/bin/activate

# カメラ1のマスク作成モードで起動
MASK_SAVE=masks/camera1_mask.png python meteor_detector.py
```

マスク作成手順：
1. ウィンドウが表示されたら、マスクしたい領域をマウスでクリック
2. 複数の点をクリックして領域を囲む
3. `Enter` キーを押して確定
4. `q` キーを押して終了

### 2. マスク画像の確認

```bash
open masks/camera1_mask.png
```

白い部分が検出対象、黒い部分がマスク（検出対象外）になります。

---

## トラブルシューティング

### Docker Desktop が起動しない

1. Docker Desktop を完全に終了
2. macOS を再起動
3. Docker Desktop を再度起動

### カメラに接続できない

1. RTSP URLが正しいか確認
2. カメラがネットワークに接続されているか確認
3. ファイアウォール設定を確認

```bash
# RTSPストリームのテスト
ffprobe rtsp://admin:password@192.168.1.100/live
```

### ポートが既に使用されている

他のアプリケーションがポート8080-8083を使用している場合、`docker-compose.yml` のポート番号を変更してください：

```yaml
ports:
  - "9080:8080"  # ホスト側のポート番号を変更
```

### コンテナが起動しない

```bash
# ログを確認
docker compose logs

# コンテナの状態を確認
docker compose ps

# コンテナを再ビルド
docker compose build --no-cache
docker compose up -d
```

---

## アンインストール

### 1. コンテナとイメージの削除

```bash
cd ~/meteor-detector
docker compose down --rmi all --volumes
```

### 2. ファイルの削除

```bash
rm -rf ~/meteor-detector
```

---

## 設定のカスタマイズ

### 感度の調整

`docker-compose.yml` の `SENSITIVITY` を変更：

- `low`: 低感度（大きな動きのみ検出）
- `medium`: 中感度（デフォルト）
- `high`: 高感度（小さな動きも検出）

### 検出時間帯の制限

デフォルトでは夜間のみ検出を行います。これを変更するには：

```yaml
environment:
  - ENABLE_TIME_WINDOW=false  # 24時間検出
```

### その他のパラメータ

詳細は `docker-compose.yml.sample` のコメントを参照してください。

---

## サポート

問題が発生した場合は、GitHubのIssuesで報告してください：

https://github.com/[YOUR-USERNAME]/meteor-detector/issues

---

## ライセンス

Copyright (c) 2026 Masanori Sakai
All rights reserved.
