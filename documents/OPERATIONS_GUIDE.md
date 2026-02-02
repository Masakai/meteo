# 運用ガイド (Operations Guide)

## 概要

このガイドでは、流星検出システムの日常的な運用方法について説明します。

## 目次

- [起動と停止](#起動と停止)
- [meteor-docker.sh コマンドリファレンス](#meteor-dockersh-コマンドリファレンス)
- [ログの監視](#ログの監視)
- [状態確認](#状態確認)
- [ディスク容量管理](#ディスク容量管理)
- [トラブルシューティング](#トラブルシューティング)
- [バックアップとリストア](#バックアップとリストア)
- [パフォーマンス監視](#パフォーマンス監視)

---

## 起動と停止

### 基本フロー

```mermaid
flowchart TD
    Start["システム起動"]
    Check1{"streamersファイル<br/>存在確認"}
    Generate["docker-compose.yml<br/>生成"]
    Check2{"docker-compose.yml<br/>存在確認"}
    Build["Dockerイメージ<br/>ビルド"]
    Up["コンテナ起動"]
    Monitor["監視・運用"]
    Stop["コンテナ停止"]
    End["システム停止"]

    Start --> Check1
    Check1 -->|"なし"| Generate
    Check1 -->|"あり"| Check2
    Generate --> Check2
    Check2 -->|"初回"| Build
    Check2 -->|"2回目以降"| Up
    Build --> Up
    Up --> Monitor
    Monitor --> Stop
    Stop --> End

    style Generate fill:#2a3f6f
    style Build fill:#16213e
    style Up fill:#1e2a4a
    style Monitor fill:#00ff88
```

### 初回起動

```bash
# 1. streamersファイルを作成
cp streamers.sample streamers
vim streamers  # RTSP URLを設定

# 2. docker-compose.ymlを生成
python generate_compose.py

# 3. Dockerイメージをビルド
./meteor-docker.sh build

# 4. システムを起動
./meteor-docker.sh start

# 5. 状態を確認
./meteor-docker.sh status
```

### 通常起動

```bash
# 起動
./meteor-docker.sh start

# ログをリアルタイム表示
./meteor-docker.sh logs
```

### 停止

```bash
# 通常停止（コンテナを削除）
./meteor-docker.sh stop

# データを保持したまま一時停止（再起動が速い）
docker compose stop
```

### 再起動

```bash
# コンテナを再起動（設定変更時など）
./meteor-docker.sh restart
```

---

## meteor-docker.sh コマンドリファレンス

### start - システム起動

```bash
./meteor-docker.sh start
```

**動作**:
- `docker compose up -d` を実行
- バックグラウンドで全コンテナを起動
- 起動状態を表示

**出力例**:
```
[INFO] 流星検出を起動中...
[+] Running 4/4
 ✔ Container meteor-camera1    Started
 ✔ Container meteor-camera2    Started
 ✔ Container meteor-camera3    Started
 ✔ Container meteor-dashboard  Started
[INFO] 起動完了
NAME                 IMAGE                  STATUS
meteor-camera1       meteo-camera1          Up 2 seconds
meteor-camera2       meteo-camera2          Up 2 seconds
meteor-camera3       meteo-camera3          Up 2 seconds
meteor-dashboard     meteo-dashboard        Up 1 second
```

---

### stop - システム停止

```bash
./meteor-docker.sh stop
```

**動作**:
- `docker compose down` を実行
- 全コンテナを停止・削除
- ネットワークを削除
- **検出結果(./detections/)は保持される**

---

### restart - 再起動

```bash
./meteor-docker.sh restart
```

**動作**:
- `docker compose restart` を実行
- 各コンテナを順次再起動
- イメージは再ビルドしない

**使用場面**:
- 設定変更後
- コンテナの動作が不安定な時
- メモリリーク対策

---

### status - 状態確認

```bash
./meteor-docker.sh status
```

**動作**:
1. コンテナ状態を表示
2. リソース使用状況を表示
3. 各カメラの検出結果数を表示

**出力例**:
```
=== コンテナ状態 ===
NAME                 STATUS          PORTS
meteor-camera1       Up 2 hours      0.0.0.0:8081->8080/tcp
meteor-camera2       Up 2 hours      0.0.0.0:8082->8080/tcp
meteor-camera3       Up 2 hours      0.0.0.0:8083->8080/tcp
meteor-dashboard     Up 2 hours      0.0.0.0:8080->8080/tcp

=== リソース使用状況 ===
CONTAINER         CPU %    MEM USAGE / LIMIT    MEM %
meteor-camera1    45.2%    312.5MiB / 8GiB      3.82%
meteor-camera2    42.8%    305.1MiB / 8GiB      3.73%
meteor-camera3    44.1%    318.2MiB / 8GiB      3.88%
meteor-dashboard  2.5%     78.3MiB / 8GiB       0.95%

=== 検出結果 ===
  camera1_10_0_1_25: 15件 (最新: 2026-02-02 06:55)
  camera2_10_0_1_3: 8件 (最新: 2026-02-02 05:32)
  camera3_10_0_1_11: 12件 (最新: 2026-02-02 07:01)
```

---

### logs - ログ表示

```bash
# 全コンテナのログ（リアルタイム）
./meteor-docker.sh logs

# 特定カメラのログ
./meteor-docker.sh logs camera1

# ダッシュボードのログ
./meteor-docker.sh logs dashboard

# Ctrl+Cで終了
```

**ログの色分け**:
- 白: 通常のメッセージ
- 緑: 情報メッセージ [INFO]
- 黄: 警告メッセージ [WARN]
- 赤: エラーメッセージ [ERROR]

**重要なログメッセージ**:
```
# 正常動作
接続成功: 1920x1080 @ 30.0fps
検出開始 (Ctrl+C で終了)

# 流星検出
[06:55:33] 流星検出 #1
  長さ: 135.6px, 時間: 0.44秒
  保存: meteor_20260202_065533.mp4

# 警告
接続失敗: rtsp://...
```

---

### build - イメージ再ビルド

```bash
./meteor-docker.sh build
```

**動作**:
- `docker compose build --no-cache` を実行
- キャッシュを使わず完全にビルド
- 時間がかかる（5-10分程度）

**使用場面**:
- コードを変更した時
- requirements.txtを変更した時
- Dockerfileを変更した時

---

### generate - docker-compose.yml再生成

```bash
# 基本
./meteor-docker.sh generate

# オプション付き
./meteor-docker.sh generate --sensitivity high --enable-time-window true
```

**動作**:
- `generate_compose.py` を実行
- streamersファイルから docker-compose.yml を生成

**使用場面**:
- カメラを追加・削除した時
- 設定を一括変更したい時

---

### clean - 古い検出結果削除

```bash
./meteor-docker.sh clean
```

**動作**:
- 7日以上前のファイルを削除
- 確認プロンプト表示

**出力例**:
```
[WARN] 古い検出結果を削除しますか？ (y/N)
y
[INFO] 7日以上前のファイルを削除しました
```

---

### cleanup - 未使用リソース削除

```bash
./meteor-docker.sh cleanup
```

**動作**:
1. このプロジェクトの古いDockerイメージを削除
2. 停止中のコンテナを削除
3. ディスク使用状況を表示

**出力例**:
```
[INFO] このプロジェクトの古いイメージを削除します...

=== meteo-camera1 の全バージョン ===
REPOSITORY      TAG       IMAGE ID       SIZE
meteo-camera1   latest    abc123def456   450MB
meteo-camera1   <none>    def789ghi012   445MB

[INFO] 1個の未使用イメージを削除しました
[INFO] このプロジェクトの停止中コンテナを削除します...
[INFO] ディスク使用状況:
TYPE            TOTAL     ACTIVE    SIZE
Images          15        4         2.1GB
Containers      4         4         150MB
Local Volumes   2         2         1.5GB
```

**使用場面**:
- ディスク容量が不足している時
- イメージを何度もビルドした後
- 定期メンテナンス

---

## ログの監視

### ログレベルと内容

#### 検出コンテナのログ

```bash
./meteor-docker.sh logs camera1
```

**主要メッセージ**:

| メッセージ | 意味 | 対応 |
|-----------|------|------|
| `接続中...` | RTSP接続試行中 | 正常 |
| `接続成功: 1920x1080 @ 30.0fps` | ストリーム接続成功 | 正常 |
| `検出開始 (Ctrl+C で終了)` | 検出処理開始 | 正常 |
| `接続失敗: rtsp://...` | RTSP接続失敗 | 要確認 |
| `[06:55:33] 流星検出 #1` | 流星検出 | 正常 |
| `稼働: 60.0分, 検出: 5個` | 1時間ごとの統計 | 正常 |

#### ダッシュボードのログ

```bash
./meteor-docker.sh logs dashboard
```

**主要メッセージ**:
```
Dashboard starting on port 8080
Cameras: 3
  - camera1 (10.0.1.25): http://localhost:8081
  - camera2 (10.0.1.3): http://localhost:8082
  - camera3 (10.0.1.11): http://localhost:8083

Open http://localhost:8080/ in your browser
```

### ログのフィルタリング

```bash
# エラーのみ表示
./meteor-docker.sh logs camera1 2>&1 | grep ERROR

# 流星検出のみ表示
./meteor-docker.sh logs camera1 2>&1 | grep "流星検出"

# 最新100行のみ表示
docker compose logs camera1 --tail=100
```

---

## 状態確認

### Webブラウザで確認

最も簡単な確認方法:

```
http://localhost:8080/  (ダッシュボード)
```

**確認項目**:
- ストリーム接続状態（緑●: 正常、赤●: 異常）
- 検出処理状態（緑●: 待機中、赤●点滅: 検出中）
- 総検出数
- 最近の検出リスト

### コマンドラインで確認

```bash
# 簡易確認
./meteor-docker.sh status

# 詳細確認
docker compose ps -a
docker stats --no-stream
```

### APIで確認

```bash
# カメラ1の統計情報
curl http://localhost:8081/stats | jq

# ダッシュボードの検出一覧
curl http://localhost:8080/detections | jq
```

---

## ディスク容量管理

### 検出結果のサイズ見積もり

| 項目 | サイズ（1件あたり） |
|-----|-------------------|
| MP4動画（4秒@30fps） | 約2-5MB |
| コンポジット画像 | 約200-500KB |
| JSON行 | 約200B |

**1日の見積もり**（検出数10件/日の場合）:
- MP4あり: 約30-50MB/日
- MP4なし: 約2-5MB/日

### 容量確認

```bash
# 検出結果のディスク使用量
du -sh ./detections/

# カメラ別の使用量
du -sh ./detections/*/

# ファイル数
find ./detections -type f | wc -l
```

### 自動クリーンアップの設定

#### 方法1: cronで定期実行

```bash
# crontabに追加
crontab -e

# 毎週日曜日の深夜2時に古いファイルを削除
0 2 * * 0 cd /path/to/meteo && find ./detections -type f -mtime +7 -delete
```

#### 方法2: systemdタイマーで実行

```bash
# /etc/systemd/system/meteor-cleanup.service
[Unit]
Description=Meteor Detection Cleanup

[Service]
Type=oneshot
WorkingDirectory=/path/to/meteo
ExecStart=/usr/bin/find ./detections -type f -mtime +7 -delete

# /etc/systemd/system/meteor-cleanup.timer
[Unit]
Description=Meteor Detection Cleanup Timer

[Timer]
OnCalendar=weekly
Persistent=true

[Install]
WantedBy=timers.target

# 有効化
sudo systemctl enable meteor-cleanup.timer
sudo systemctl start meteor-cleanup.timer
```

### 手動クリーンアップ

```bash
# 7日以上前のファイルを削除（対話型）
./meteor-docker.sh clean

# MP4のみ削除（コンポジット画像は残す）
find ./detections -name "*.mp4" -mtime +7 -delete

# 特定カメラのみ削除
find ./detections/camera1_10_0_1_25 -type f -mtime +7 -delete
```

---

## トラブルシューティング

### トラブルシューティングフロー

```mermaid
flowchart TD
    Start["問題発生"]
    CheckContainer{"コンテナが<br/>起動している？"}
    CheckLogs["ログを確認"]
    CheckRTSP{"RTSP接続<br/>エラー？"}
    CheckDisk{"ディスク容量<br/>不足？"}
    CheckMemory{"メモリ不足？"}

    FixContainer["docker compose up -d"]
    FixRTSP["RTSP URLとネットワークを確認"]
    FixDisk["古いファイル削除<br/>cleanup実行"]
    FixMemory["コンテナ再起動<br/>スケール調整"]

    Resolved["解決"]
    Support["サポートに連絡"]

    Start --> CheckContainer
    CheckContainer -->|"No"| FixContainer
    CheckContainer -->|"Yes"| CheckLogs
    CheckLogs --> CheckRTSP
    CheckRTSP -->|"Yes"| FixRTSP
    CheckRTSP -->|"No"| CheckDisk
    CheckDisk -->|"Yes"| FixDisk
    CheckDisk -->|"No"| CheckMemory
    CheckMemory -->|"Yes"| FixMemory
    CheckMemory -->|"No"| Support

    FixContainer --> Resolved
    FixRTSP --> Resolved
    FixDisk --> Resolved
    FixMemory --> Resolved

    style Start fill:#ff4444
    style Resolved fill:#00ff88
    style Support fill:#ff8844
```

### よくある問題と解決方法

#### 1. コンテナが起動しない

**症状**:
```bash
./meteor-docker.sh status
# コンテナが表示されない
```

**原因と対策**:

| 原因 | 確認方法 | 対策 |
|-----|---------|------|
| docker-compose.ymlがない | `ls docker-compose.yml` | `python generate_compose.py` |
| Dockerデーモン未起動 | `docker ps` | `sudo systemctl start docker` |
| ポート競合 | `lsof -i :8080` | ポート番号を変更 |
| イメージ未ビルド | `docker images` | `./meteor-docker.sh build` |

**解決手順**:
```bash
# 1. docker-compose.ymlを確認
ls -la docker-compose.yml

# 2. Dockerデーモンを確認
docker ps

# 3. エラーログを確認
docker compose up

# 4. 再ビルドして起動
./meteor-docker.sh build
./meteor-docker.sh start
```

---

#### 2. RTSP接続エラー

**症状**:
```
接続失敗: rtsp://...
```

**原因と対策**:

```bash
# 1. カメラにpingが通るか確認
ping 10.0.1.25

# 2. RTSPポートが開いているか確認
nc -zv 10.0.1.25 554

# 3. ffmpegで直接接続テスト
ffmpeg -i "rtsp://user:pass@10.0.1.25/live" -frames:v 1 test.jpg

# 4. streamersファイルを確認
cat streamers

# 5. 認証情報を確認
# ユーザー名・パスワードが正しいか
```

**チェックリスト**:
- [ ] カメラの電源が入っているか
- [ ] ネットワークケーブルが接続されているか
- [ ] IPアドレスが正しいか
- [ ] ユーザー名・パスワードが正しいか
- [ ] ファイアウォールでポート554が開いているか
- [ ] カメラ側のRTSP機能が有効か

---

#### 3. ディスク容量不足

**症状**:
```
Error: No space left on device
```

**確認**:
```bash
# ディスク使用量を確認
df -h

# 検出結果のサイズ
du -sh ./detections/

# Dockerのディスク使用量
docker system df
```

**対策**:
```bash
# 1. 古い検出結果を削除
./meteor-docker.sh clean

# 2. 未使用Dockerリソースを削除
./meteor-docker.sh cleanup

# 3. MP4を無効化（設定変更）
# docker-compose.ymlで EXTRACT_CLIPS=false

# 4. より積極的なクリーンアップ
docker system prune -a --volumes
```

---

#### 4. メモリ不足・CPUが高い

**症状**:
```bash
./meteor-docker.sh status
# CPU %が常時90%以上
# MEM %が常時80%以上
```

**対策**:

```bash
# 1. コンテナを再起動（メモリリーク対策）
./meteor-docker.sh restart

# 2. 処理スケールを下げる
python generate_compose.py --scale 0.25

# 3. カメラ数を減らす
# streamersファイルからカメラを削除

# 4. リソース制限を設定
# docker-compose.ymlに追加:
#   deploy:
#     resources:
#       limits:
#         cpus: '0.5'
#         memory: 512M
```

---

#### 5. ストリームが表示されない

**症状**:
- ダッシュボードでカメラ映像が「接続中...」のまま

**確認**:
```bash
# カメラコンテナが動いているか
./meteor-docker.sh status

# カメラのログを確認
./meteor-docker.sh logs camera1

# ブラウザで直接アクセス
open http://localhost:8081/
```

**対策**:
```bash
# カメラコンテナを再起動
docker compose restart camera1

# ブラウザのキャッシュをクリア
# Ctrl+Shift+R (強制リロード)
```

---

## バックアップとリストア

### バックアップ対象

1. **検出結果**: `./detections/`
2. **設定ファイル**: `streamers`, `docker-compose.yml`
3. **カスタマイズしたコード**: `*.py`

### バックアップ手順

```bash
# 日付付きバックアップ
DATE=$(date +%Y%m%d)
tar -czf meteor-backup-${DATE}.tar.gz \
    detections/ \
    streamers \
    docker-compose.yml

# リモートサーバーにコピー
scp meteor-backup-${DATE}.tar.gz user@backup-server:/backups/

# クラウドストレージにアップロード（例: AWS S3）
aws s3 cp meteor-backup-${DATE}.tar.gz s3://my-bucket/backups/
```

### 自動バックアップ

```bash
# backup.sh
#!/bin/bash
DATE=$(date +%Y%m%d)
BACKUP_DIR="/path/to/backups"
cd /path/to/meteo

tar -czf ${BACKUP_DIR}/meteor-backup-${DATE}.tar.gz \
    detections/ streamers docker-compose.yml

# 30日以上前のバックアップを削除
find ${BACKUP_DIR} -name "meteor-backup-*.tar.gz" -mtime +30 -delete

# crontabに登録
# 0 3 * * * /path/to/backup.sh
```

### リストア手順

```bash
# システムを停止
./meteor-docker.sh stop

# バックアップを展開
tar -xzf meteor-backup-20260202.tar.gz

# システムを起動
./meteor-docker.sh start
```

---

## パフォーマンス監視

### リアルタイム監視

```bash
# Docker stats（リアルタイム）
docker stats

# top風表示
docker stats --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"

# htopで監視
htop

# 検出状況の監視（1分ごと）
watch -n 60 './meteor-docker.sh status'
```

### メトリクス収集

```bash
# リソース使用履歴をログに記録
while true; do
    echo "$(date) $(docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemPerc}}')" \
        >> /var/log/meteor-stats.log
    sleep 300  # 5分ごと
done
```

### アラート設定例

```bash
# alert.sh - CPU使用率90%超えで通知
#!/bin/bash
CPU=$(docker stats --no-stream --format "{{.CPUPerc}}" meteor-camera1 | sed 's/%//')
if (( $(echo "$CPU > 90" | bc -l) )); then
    echo "Alert: Camera1 CPU usage is ${CPU}%" | mail -s "Meteor Alert" admin@example.com
fi
```

---

## 定期メンテナンス

### 日次

```bash
# 状態確認
./meteor-docker.sh status

# ログ確認（エラーの有無）
./meteor-docker.sh logs | grep -i error

# ディスク容量確認
df -h
```

### 週次

```bash
# コンテナ再起動（メモリリーク対策）
./meteor-docker.sh restart

# バックアップ実行
./backup.sh

# ログファイルのローテーション
docker compose logs --tail=1000 > logs-$(date +%Y%m%d).txt
```

### 月次

```bash
# 古い検出結果の削除
./meteor-docker.sh clean

# 未使用Dockerリソースの削除
./meteor-docker.sh cleanup

# 検出統計の確認
find ./detections -name "*.mp4" | wc -l
```

---

## 関連ドキュメント

- [DOCKER_ARCHITECTURE.md](DOCKER_ARCHITECTURE.md) - Docker構成の詳細
- [CONFIGURATION_GUIDE.md](CONFIGURATION_GUIDE.md) - 設定方法
- [SECURITY.md](SECURITY.md) - セキュリティガイド
- [API_REFERENCE.md](API_REFERENCE.md) - API仕様
