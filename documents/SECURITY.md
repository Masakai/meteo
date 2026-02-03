# セキュリティガイド (Security Guide)

---

**Copyright (c) 2026 Masanori Sakai**

Licensed under the MIT License

---


## 概要

流星検出システムを安全に運用するためのセキュリティガイドラインです。

## 目次

- [セキュリティリスク](#セキュリティリスク)
- [RTSP認証情報の保護](#rtsp認証情報の保護)
- [ネットワークセキュリティ](#ネットワークセキュリティ)
- [ファイルシステムのセキュリティ](#ファイルシステムのセキュリティ)
- [Dockerセキュリティ](#dockerセキュリティ)
- [アクセス制御](#アクセス制御)
- [セキュリティチェックリスト](#セキュリティチェックリスト)

---

## セキュリティリスク

### リスク評価

```mermaid
graph TB
    subgraph "高リスク"
        Risk1["RTSP認証情報の漏洩<br/>影響: カメラへの不正アクセス"]
        Risk2["Webインターフェースへの不正アクセス<br/>影響: 検出結果の閲覧・削除"]
    end

    subgraph "中リスク"
        Risk3["検出結果ファイルの流出<br/>影響: プライバシー侵害"]
        Risk4["Dockerコンテナの脆弱性<br/>影響: システム侵害"]
    end

    subgraph "低リスク"
        Risk5["ログファイルからの情報漏洩<br/>影響: 設定情報の露出"]
    end

    style Risk1 fill:#ff4444
    style Risk2 fill:#ff4444
    style Risk3 fill:#ff8844
    style Risk4 fill:#ff8844
    style Risk5 fill:#ffcc44
```

### 脅威モデル

| 脅威 | 攻撃者 | 影響 | 対策優先度 |
|-----|--------|------|-----------|
| RTSP認証情報の平文保存 | 内部者、マルウェア | カメラ乗っ取り | 高 |
| Webポートの外部公開 | 外部攻撃者 | データ漏洩 | 高 |
| 検出画像からの位置特定 | 第三者 | プライバシー侵害 | 中 |
| Docker脆弱性の悪用 | 外部攻撃者 | システム侵害 | 中 |
| ログファイルの漏洩 | 内部者 | 設定情報露出 | 低 |

---

## RTSP認証情報の保護

### 問題点

**デフォルト設定**:
```
streamers ファイル（平文）:
rtsp://username:password@10.0.1.25/live
```

補足: `| 昼間画像パス` を行末に付けることも可能ですが、画像ファイルにもアクセス制限を推奨します。

⚠️ **リスク**:
- 認証情報が平文で保存
- Gitにコミットすると公開される
- ファイルシステムアクセスで閲覧可能

---

### 対策1: .envファイルの使用 ★推奨

#### ステップ1: .envファイルを作成

```bash
# .env ファイルを作成
cat > .env << 'EOF'
# RTSP認証情報
RTSP_USER_CAMERA1=username1
RTSP_PASS_CAMERA1=password1

RTSP_USER_CAMERA2=username2
RTSP_PASS_CAMERA2=password2

RTSP_USER_CAMERA3=username3
RTSP_PASS_CAMERA3=password3

# カメラIPアドレス
CAMERA1_IP=10.0.1.25
CAMERA2_IP=10.0.1.3
CAMERA3_IP=10.0.1.11
EOF

# パーミッション制限（重要！）
chmod 600 .env
```

#### ステップ2: .gitignoreに追加

```bash
echo ".env" >> .gitignore
```

#### ステップ3: streamersファイルを環境変数参照に変更

```bash
# streamers ファイル（認証情報なし）
cat > streamers << 'EOF'
${CAMERA1_IP}
${CAMERA2_IP}
${CAMERA3_IP}
EOF
```

※ 昼間画像を指定する場合は `| camera1.jpg` のように行末に追加します（画像ファイルの権限にも注意）。

#### ステップ4: generate_compose.pyを修正

カスタムスクリプトで.envから読み込み:

```python
# generate_compose_secure.py
import os
from dotenv import load_dotenv

load_dotenv()  # .envファイルを読み込み

# RTSP URLを構築
rtsp_url1 = f"rtsp://{os.getenv('RTSP_USER_CAMERA1')}:{os.getenv('RTSP_PASS_CAMERA1')}@{os.getenv('CAMERA1_IP')}/live"
```

または、docker-compose.ymlで直接参照:

```yaml
services:
  camera1:
    environment:
      - RTSP_URL=rtsp://${RTSP_USER_CAMERA1}:${RTSP_PASS_CAMERA1}@${CAMERA1_IP}/live
```

---

### 対策2: Docker Secrets（本番環境推奨）

#### ステップ1: Secretsファイルを作成

```bash
# secretsディレクトリを作成
mkdir -p secrets
chmod 700 secrets

# 各カメラの認証情報を作成
echo "username1:password1" > secrets/camera1_auth
echo "username2:password2" > secrets/camera2_auth
echo "username3:password3" > secrets/camera3_auth

# パーミッション制限
chmod 600 secrets/*
```

#### ステップ2: .gitignoreに追加

```bash
echo "secrets/" >> .gitignore
```

#### ステップ3: docker-compose.ymlに設定

```yaml
services:
  camera1:
    secrets:
      - camera1_auth
    environment:
      - RTSP_URL_FILE=/run/secrets/camera1_auth
      - CAMERA_IP=10.0.1.25

secrets:
  camera1_auth:
    file: ./secrets/camera1_auth
  camera2_auth:
    file: ./secrets/camera2_auth
  camera3_auth:
    file: ./secrets/camera3_auth
```

#### ステップ4: エントリーポイントスクリプトで読み込み

```bash
# entrypoint.sh
#!/bin/bash
AUTH=$(cat /run/secrets/camera1_auth)
USERNAME=$(echo $AUTH | cut -d: -f1)
PASSWORD=$(echo $AUTH | cut -d: -f2)
RTSP_URL="rtsp://${USERNAME}:${PASSWORD}@${CAMERA_IP}/live"

exec python meteor_detector_rtsp_web.py "$RTSP_URL" "$@"
```

---

### 対策3: 認証情報のローテーション

```bash
# 定期的にパスワードを変更（推奨: 3ヶ月ごと）

# 1. カメラ側のパスワードを変更
# 2. .envファイルを更新
# 3. コンテナを再起動
./meteor-docker.sh restart
```

---

### 対策4: 読み取り専用ファイルシステム

```yaml
services:
  camera1:
    read_only: true  # コンテナを読み取り専用に
    tmpfs:
      - /tmp
      - /var/tmp
```

---

## ネットワークセキュリティ

### ポート公開の最小化

#### デフォルト（全ポート公開）

```yaml
ports:
  - "8080:8080"  # ダッシュボード
  - "8081:8080"  # カメラ1
  - "8082:8080"  # カメラ2
  - "8083:8080"  # カメラ3
```

⚠️ **リスク**: すべてのポートが外部に公開

---

#### 推奨: ダッシュボードのみ公開

```yaml
services:
  dashboard:
    ports:
      - "8080:8080"  # ダッシュボードのみ公開

  camera1:
    # ポート公開なし（内部ネットワークのみ）
    expose:
      - "8080"
```

**効果**:
- カメラコンテナに外部から直接アクセス不可
- ダッシュボード経由のアクセスのみ

---

#### 高セキュリティ: localhostのみ

```yaml
ports:
  - "127.0.0.1:8080:8080"  # localhostのみ
```

**効果**:
- 同一ホストからのみアクセス可能
- リモートアクセスはSSHポートフォワーディング経由

**SSHポートフォワーディング**:
```bash
# リモートからアクセス
ssh -L 8080:localhost:8080 user@meteor-server

# ブラウザで http://localhost:8080/ にアクセス
```

---

### ファイアウォール設定

#### UFW（Ubuntu）

```bash
# デフォルトポリシー
sudo ufw default deny incoming
sudo ufw default allow outgoing

# SSH許可（重要！ロックアウト注意）
sudo ufw allow 22/tcp

# ダッシュボードポート（信頼できるIPのみ）
sudo ufw allow from 192.168.1.0/24 to any port 8080

# 有効化
sudo ufw enable
sudo ufw status
```

#### firewalld（CentOS/RHEL）

```bash
# ダッシュボードポート（信頼できるIPのみ）
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="192.168.1.0/24" port port="8080" protocol="tcp" accept'

sudo firewall-cmd --reload
sudo firewall-cmd --list-all
```

---

### VPN経由のアクセス（高セキュリティ）

```mermaid
graph LR
    User["ユーザー"]
    VPN["VPNサーバー"]
    Meteor["流星検出システム"]

    User -->|"暗号化トンネル"| VPN
    VPN -->|"プライベートネットワーク"| Meteor

    style VPN fill:#2a3f6f
    style Meteor fill:#16213e
```

**推奨VPNソリューション**:
- WireGuard（高速・軽量）
- OpenVPN（汎用性高い）
- Tailscale（簡単設定）

---

### HTTPSの導入（リバースプロキシ）

#### Nginxでリバースプロキシ

```nginx
# /etc/nginx/sites-available/meteor
server {
    listen 443 ssl http2;
    server_name meteor.example.com;

    ssl_certificate /etc/letsencrypt/live/meteor.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/meteor.example.com/privkey.pem;

    # セキュリティヘッダー
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;

    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket対応（MJPEGストリーム用）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}

# HTTP -> HTTPS リダイレクト
server {
    listen 80;
    server_name meteor.example.com;
    return 301 https://$server_name$request_uri;
}
```

#### Let's Encrypt証明書の取得

```bash
# Certbotのインストール
sudo apt install certbot python3-certbot-nginx

# 証明書の取得
sudo certbot --nginx -d meteor.example.com

# 自動更新の設定
sudo systemctl enable certbot.timer
```

---

## ファイルシステムのセキュリティ

### ディレクトリパーミッション

```bash
# プロジェクトディレクトリ
chmod 755 /path/to/meteo

# streamersファイル（認証情報あり）
chmod 600 /path/to/meteo/streamers

# .envファイル
chmod 600 /path/to/meteo/.env

# 検出結果ディレクトリ
chmod 755 /path/to/meteo/detections

# スクリプト
chmod 700 /path/to/meteo/meteor-docker.sh
```

### 検出結果の匿名化

#### 位置情報の削除

```bash
# EXIFデータを削除（位置情報など）
sudo apt install exiftool

# 画像からメタデータを削除
find ./detections -name "*.jpg" -exec exiftool -all= {} \;
```

#### 自動匿名化スクリプト

```bash
# anonymize.sh
#!/bin/bash
DETECTIONS_DIR="./detections"

# 新しい画像を検索
find "$DETECTIONS_DIR" -name "*.jpg" -mmin -5 | while read img; do
    # EXIFデータを削除
    exiftool -all= "$img"
    # 元のファイルを削除
    rm "${img}_original"
done
```

---

## Dockerセキュリティ

### イメージのスキャン

```bash
# Trivyのインストール
sudo apt install trivy

# イメージの脆弱性スキャン
trivy image meteo-camera1:latest
trivy image meteo-dashboard:latest

# 重大度HIGH以上のみ表示
trivy image --severity HIGH,CRITICAL meteo-camera1:latest
```

### イメージの署名と検証

```bash
# Docker Content Trust有効化
export DOCKER_CONTENT_TRUST=1

# イメージのビルド（署名付き）
docker build --tag myregistry.com/meteo-camera1:latest .
docker push myregistry.com/meteo-camera1:latest
```

### 最小権限の原則

```yaml
services:
  camera1:
    user: "1000:1000"  # 非rootユーザーで実行
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE  # 必要な権限のみ追加
    security_opt:
      - no-new-privileges:true
```

### リソース制限

```yaml
services:
  camera1:
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
        reservations:
          cpus: '0.5'
          memory: 256M
```

---

## アクセス制御

### Basic認証の追加

#### Nginxで実装

```bash
# パスワードファイルの作成
sudo apt install apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd admin

# Nginx設定
# /etc/nginx/sites-available/meteor
location / {
    auth_basic "Meteor Detection System";
    auth_basic_user_file /etc/nginx/.htpasswd;

    proxy_pass http://localhost:8080;
}
```

#### ダッシュボードに認証を追加

dashboard.pyを拡張:

```python
import base64
from functools import wraps

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = self.headers.get('Authorization')
        if not auth:
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="Login Required"')
            self.end_headers()
            return

        # "Basic dXNlcjpwYXNz" から認証情報を取得
        encoded = auth.split(' ')[1]
        decoded = base64.b64decode(encoded).decode('utf-8')
        username, password = decoded.split(':')

        # 認証チェック（環境変数から取得推奨）
        if username == os.getenv('DASHBOARD_USER') and \
           password == os.getenv('DASHBOARD_PASS'):
            return f(*args, **kwargs)

        self.send_response(403)
        self.end_headers()
        return

    return decorated

class DashboardHandler(BaseHTTPRequestHandler):
    @require_auth
    def do_GET(self):
        # ... 既存のコード
```

---

### IPアドレス制限

#### docker-compose.ymlでの制限

```yaml
services:
  dashboard:
    networks:
      meteor-net:
        ipv4_address: 172.20.0.10
    # iptablesルールと組み合わせて制限
```

#### iptablesでの制限

```bash
# 特定IPからのみ許可
sudo iptables -A INPUT -p tcp --dport 8080 -s 192.168.1.0/24 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 8080 -j DROP

# 永続化
sudo iptables-save > /etc/iptables/rules.v4
```

---

## セキュリティチェックリスト

### デプロイ前

- [ ] RTSP認証情報を.envファイルに移動
- [ ] .envファイルのパーミッションを600に設定
- [ ] .gitignoreに.envとsecretsを追加
- [ ] streamersファイルから認証情報を削除
- [ ] docker-compose.ymlから平文パスワードを削除
- [ ] 不要なポートを閉じる
- [ ] ファイアウォール設定を確認
- [ ] Dockerイメージの脆弱性スキャン

### 運用中

- [ ] 定期的なパスワード変更（3ヶ月ごと）
- [ ] ログファイルの監視（不正アクセスの検知）
- [ ] Dockerイメージの定期更新
- [ ] 検出結果のバックアップ
- [ ] ディスク容量の監視
- [ ] セキュリティパッチの適用

### インシデント対応

- [ ] 不正アクセスの兆候を確認
- [ ] ログファイルを保全
- [ ] 影響範囲を特定
- [ ] パスワードを変更
- [ ] システムを一時停止
- [ ] 原因を調査
- [ ] 再発防止策を実施

---

## セキュリティインシデント対応

### 不正アクセスの検知

```bash
# アクセスログの確認
docker compose logs dashboard | grep -E "GET|POST|DELETE"

# 異常なアクセスパターンを検索
# 例: 大量のDELETEリクエスト
docker compose logs dashboard | grep DELETE | wc -l

# 外部IPからのアクセス
docker compose logs dashboard | grep -v "127.0.0.1"
```

### インシデント発生時の対応

```mermaid
flowchart TD
    Detect["不正アクセス検知"]
    Stop["システム停止"]
    Preserve["ログ保全"]
    Analyze["影響範囲分析"]
    Change["認証情報変更"]
    Patch["脆弱性修正"]
    Restart["システム再開"]
    Report["インシデントレポート作成"]

    Detect --> Stop
    Stop --> Preserve
    Preserve --> Analyze
    Analyze --> Change
    Change --> Patch
    Patch --> Restart
    Restart --> Report

    style Detect fill:#ff4444
    style Stop fill:#ff8844
    style Restart fill:#00ff88
```

#### ステップ1: 即座に停止

```bash
# すべてのコンテナを停止
./meteor-docker.sh stop

# ネットワークを切断（緊急時）
docker network disconnect meteor-net meteor-dashboard
```

#### ステップ2: ログの保全

```bash
# ログをバックアップ
docker compose logs > incident-$(date +%Y%m%d-%H%M%S).log

# システムログも保存
sudo journalctl -u docker > system-incident-$(date +%Y%m%d-%H%M%S).log
```

#### ステップ3: 認証情報の変更

```bash
# すべてのRTSPパスワードを変更
vim .env

# Dockerイメージを再ビルド
./meteor-docker.sh build
```

#### ステップ4: 脆弱性の修正

```bash
# システムの更新
sudo apt update && sudo apt upgrade -y

# Dockerイメージの更新
docker compose pull
./meteor-docker.sh build
```

---

## セキュリティ監査

### 定期監査スクリプト

```bash
#!/bin/bash
# security-audit.sh

echo "=== セキュリティ監査 ==="
echo "実行日時: $(date)"
echo ""

# 1. ファイルパーミッション確認
echo "[1] ファイルパーミッション"
ls -la .env streamers 2>/dev/null || echo "  .env または streamers が見つかりません"
echo ""

# 2. 平文パスワードの検索
echo "[2] 平文パスワードの検索"
grep -r "rtsp://.*:.*@" . --exclude-dir=.git 2>/dev/null && \
    echo "  ⚠️  平文パスワードが見つかりました" || \
    echo "  ✓ 平文パスワードは見つかりませんでした"
echo ""

# 3. 公開ポートの確認
echo "[3] 公開ポート"
docker compose ps --format "table {{.Name}}\t{{.Ports}}"
echo ""

# 4. 脆弱性スキャン
echo "[4] Dockerイメージの脆弱性"
if command -v trivy &> /dev/null; then
    trivy image --severity HIGH,CRITICAL --quiet meteo-camera1:latest
else
    echo "  trivyがインストールされていません"
fi
echo ""

# 5. ログの異常確認
echo "[5] ログの異常確認（過去24時間）"
ERROR_COUNT=$(docker compose logs --since 24h | grep -i error | wc -l)
echo "  エラー件数: $ERROR_COUNT"
if [ $ERROR_COUNT -gt 10 ]; then
    echo "  ⚠️  エラーが多発しています"
fi
echo ""

echo "=== 監査完了 ==="
```

---

## 関連ドキュメント

- [OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md) - 運用ガイド
- [CONFIGURATION_GUIDE.md](CONFIGURATION_GUIDE.md) - 設定ガイド
- [DOCKER_ARCHITECTURE.md](DOCKER_ARCHITECTURE.md) - Docker構成
