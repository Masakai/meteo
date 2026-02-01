#!/usr/bin/env python3
"""
Astrometry.net APIを使った星座線描画プログラム

広角レンズの歪みも自動補正して正確な星座線を描画します。

使い方:
    python constellation_drawer_astrometry.py input.jpg --output output.jpg --api-key YOUR_API_KEY
"""

import argparse
import requests
import time
import json
import cv2
import numpy as np
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass


# Astrometry.net API設定
ASTROMETRY_API_URL = "http://nova.astrometry.net/api/"
ASTROMETRY_API_KEY = 'kadwqsituqkdexme'

@dataclass
class CelestialCoord:
    """天球座標（赤経・赤緯）"""
    ra: float   # 赤経（度）
    dec: float  # 赤緯（度）


@dataclass
class ConstellationStar:
    """星座を構成する星"""
    name: str
    ra: float   # 赤経（度）
    dec: float  # 赤緯（度）


@dataclass
class ConstellationData:
    """星座データ（実際の天球座標）"""
    name: str
    name_jp: str
    stars: List[ConstellationStar]
    lines: List[Tuple[int, int]]


# 星座データベース（実際の天球座標 J2000.0）
CONSTELLATIONS: Dict[str, ConstellationData] = {
    "orion": ConstellationData(
        name="Orion",
        name_jp="オリオン座",
        stars=[
            ConstellationStar("Betelgeuse", 88.79, 7.41),    # 0: ベテルギウス（α）
            ConstellationStar("Bellatrix", 81.28, 6.35),     # 1: ベラトリックス（γ）
            ConstellationStar("Alnitak", 85.19, -1.94),      # 2: アルニタク（ζ）
            ConstellationStar("Alnilam", 84.05, -1.20),      # 3: アルニラム（ε）
            ConstellationStar("Mintaka", 83.00, -0.30),      # 4: ミンタカ（δ）
            ConstellationStar("Saiph", 86.94, -9.67),        # 5: サイフ（κ）
            ConstellationStar("Rigel", 78.63, -8.20),        # 6: リゲル（β）
            ConstellationStar("Meissa", 83.78, 9.93),        # 7: メイサ（λ）
        ],
        lines=[
            (0, 1),        # 両肩
            (0, 3), (1, 3),  # 肩から三ツ星中央へ
            (2, 3), (3, 4),  # 三ツ星
            (2, 5), (4, 6),  # 三ツ星から足へ
            (0, 7), (1, 7),  # 肩から頭へ
        ]
    ),
    "bigdipper": ConstellationData(
        name="Big Dipper",
        name_jp="北斗七星",
        stars=[
            ConstellationStar("Dubhe", 165.93, 61.75),      # 0: ドゥーベ（α UMa）
            ConstellationStar("Merak", 165.46, 56.38),      # 1: メラク（β UMa）
            ConstellationStar("Phecda", 178.46, 53.69),     # 2: フェクダ（γ UMa）
            ConstellationStar("Megrez", 183.86, 57.03),     # 3: メグレズ（δ UMa）
            ConstellationStar("Alioth", 193.51, 55.96),     # 4: アリオト（ε UMa）
            ConstellationStar("Mizar", 200.98, 54.93),      # 5: ミザール（ζ UMa）
            ConstellationStar("Alkaid", 206.89, 49.31),     # 6: アルカイド（η UMa）
        ],
        lines=[
            (0, 1), (1, 2), (2, 3), (3, 0),  # 柄杓の器
            (3, 4), (4, 5), (5, 6),          # 柄杓の柄
        ]
    ),
    "cassiopeia": ConstellationData(
        name="Cassiopeia",
        name_jp="カシオペア座",
        stars=[
            ConstellationStar("Schedar", 10.13, 56.54),     # 0: シェダル（α）
            ConstellationStar("Caph", 2.29, 59.15),         # 1: カフ（β）
            ConstellationStar("Gamma Cas", 14.18, 60.72),   # 2: γ星
            ConstellationStar("Ruchbah", 21.45, 60.24),     # 3: ルクバー（δ）
            ConstellationStar("Segin", 28.60, 63.67),       # 4: セギン（ε）
        ],
        lines=[
            (1, 0), (0, 2), (2, 3), (3, 4),  # W字型
        ]
    ),
    "cygnus": ConstellationData(
        name="Cygnus",
        name_jp="はくちょう座",
        stars=[
            ConstellationStar("Deneb", 310.36, 45.28),      # 0: デネブ（α）
            ConstellationStar("Sadr", 305.56, 40.26),       # 1: サドル（γ）
            ConstellationStar("Gienah", 305.02, 33.97),     # 2: ギェナー（ε）
            ConstellationStar("Delta Cyg", 296.24, 45.13),  # 3: δ星
            ConstellationStar("Albireo", 292.68, 27.96),    # 4: アルビレオ（β）
            ConstellationStar("Zeta Cyg", 318.23, 30.23),   # 5: ζ星
        ],
        lines=[
            (0, 1), (1, 2), (2, 4),    # 縦線（体）
            (3, 1), (1, 5),            # 横線（翼）
        ]
    ),
    "scorpius": ConstellationData(
        name="Scorpius",
        name_jp="さそり座",
        stars=[
            ConstellationStar("Antares", 247.35, -26.43),     # 0: アンタレス（α）
            ConstellationStar("Graffias", 241.36, -19.81),   # 1: グラフィアス（β）
            ConstellationStar("Dschubba", 240.08, -22.62),   # 2: ジュバ（δ）
            ConstellationStar("Pi Sco", 239.71, -26.11),     # 3: π星
            ConstellationStar("Sigma Sco", 245.30, -25.59),  # 4: σ星
            ConstellationStar("Tau Sco", 248.97, -28.22),    # 5: τ星
            ConstellationStar("Epsilon Sco", 252.54, -34.29),# 6: ε星
            ConstellationStar("Shaula", 263.40, -37.10),     # 7: シャウラ（λ）
            ConstellationStar("Lesath", 262.69, -37.30),     # 8: レサト（υ）
        ],
        lines=[
            (1, 2), (2, 3), (3, 0), (0, 4),  # 頭部から体
            (4, 5), (5, 6), (6, 7), (7, 8),  # 尾
        ]
    ),
    "lyra": ConstellationData(
        name="Lyra",
        name_jp="こと座",
        stars=[
            ConstellationStar("Vega", 279.23, 38.78),        # 0: ベガ（α）
            ConstellationStar("Sheliak", 282.52, 33.36),     # 1: シェリアク（β）
            ConstellationStar("Sulafat", 284.74, 32.69),     # 2: スラファト（γ）
            ConstellationStar("Delta1 Lyr", 281.08, 36.90),  # 3: δ1星
            ConstellationStar("Zeta1 Lyr", 280.16, 37.61),   # 4: ζ1星
        ],
        lines=[
            (0, 1), (1, 2), (2, 3), (3, 4), (4, 0),  # 五角形
            (1, 3),  # 対角線
        ]
    ),
    "taurus": ConstellationData(
        name="Taurus",
        name_jp="おうし座",
        stars=[
            ConstellationStar("Aldebaran", 68.98, 16.51),    # 0: アルデバラン（α）
            ConstellationStar("Elnath", 81.57, 28.61),       # 1: エルナト（β）
            ConstellationStar("Zeta Tau", 84.41, 21.14),     # 2: ζ星
            ConstellationStar("Theta2 Tau", 67.17, 15.87),   # 3: θ2星（ヒアデス）
            ConstellationStar("Gamma Tau", 64.95, 15.63),    # 4: γ星
            ConstellationStar("Delta1 Tau", 65.73, 17.54),   # 5: δ1星
            ConstellationStar("Epsilon Tau", 67.15, 19.18),  # 6: ε星
        ],
        lines=[
            (0, 3), (3, 4),          # 顔の下
            (3, 5), (5, 6),          # 顔の上
            (0, 2), (2, 1),          # 角
        ]
    ),
    "gemini": ConstellationData(
        name="Gemini",
        name_jp="ふたご座",
        stars=[
            ConstellationStar("Castor", 113.65, 31.89),      # 0: カストル（α）
            ConstellationStar("Pollux", 116.33, 28.03),      # 1: ポルックス（β）
            ConstellationStar("Alhena", 99.43, 16.40),       # 2: アルヘナ（γ）
            ConstellationStar("Mebsuta", 100.98, 25.13),     # 3: メブスタ（ε）
            ConstellationStar("Tejat", 95.74, 22.51),        # 4: テジャト（μ）
            ConstellationStar("Propus", 93.72, 22.51),       # 5: プロプス（η）
        ],
        lines=[
            (0, 3), (3, 4), (4, 5),    # カストル側
            (1, 2),                     # ポルックス側
            (0, 1),                     # 頭を繋ぐ
            (3, 2),                     # 体を繋ぐ
        ]
    ),
}


class AstrometryClient:
    """Astrometry.net APIクライアント"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session_key = None

    def login(self) -> bool:
        """APIにログイン"""
        response = requests.post(
            ASTROMETRY_API_URL + "login",
            data={"request-json": json.dumps({"apikey": self.api_key})}
        )
        result = response.json()
        if result.get("status") == "success":
            self.session_key = result["session"]
            print(f"ログイン成功")
            return True
        else:
            print(f"ログイン失敗: {result}")
            return False

    def upload_image(self, image_path: str) -> Optional[int]:
        """画像をアップロード"""
        if not self.session_key:
            raise RuntimeError("ログインしていません")

        with open(image_path, "rb") as f:
            response = requests.post(
                ASTROMETRY_API_URL + "upload",
                data={
                    "request-json": json.dumps({
                        "session": self.session_key,
                        "publicly_visible": "n",
                        "allow_modifications": "n",
                        "allow_commercial_use": "n",
                    })
                },
                files={"file": f}
            )

        result = response.json()
        if result.get("status") == "success":
            submission_id = result["subid"]
            print(f"アップロード成功 (submission_id: {submission_id})")
            return submission_id
        else:
            print(f"アップロード失敗: {result}")
            return None

    def get_submission_status(self, submission_id: int) -> dict:
        """サブミッションの状態を取得"""
        response = requests.get(
            ASTROMETRY_API_URL + f"submissions/{submission_id}"
        )
        return response.json()

    def get_job_status(self, job_id: int) -> dict:
        """ジョブの状態を取得"""
        response = requests.get(
            ASTROMETRY_API_URL + f"jobs/{job_id}"
        )
        return response.json()

    def get_job_calibration(self, job_id: int) -> Optional[dict]:
        """キャリブレーション結果を取得"""
        response = requests.get(
            ASTROMETRY_API_URL + f"jobs/{job_id}/calibration"
        )
        if response.status_code == 200:
            return response.json()
        return None

    def get_wcs_file(self, job_id: int) -> Optional[bytes]:
        """WCSファイルを取得"""
        response = requests.get(
            f"http://nova.astrometry.net/wcs_file/{job_id}"
        )
        if response.status_code == 200:
            return response.content
        return None

    def wait_for_job(self, submission_id: int, timeout: int = 300) -> Optional[int]:
        """ジョブ完了を待機"""
        start_time = time.time()
        job_id = None

        print("解析中", end="", flush=True)
        while time.time() - start_time < timeout:
            status = self.get_submission_status(submission_id)
            jobs = status.get("jobs", [])

            if jobs and jobs[0] is not None:
                job_id = jobs[0]
                break

            print(".", end="", flush=True)
            time.sleep(5)

        if job_id is None:
            print("\nジョブが開始されませんでした")
            return None

        print(f"\nジョブID: {job_id}")
        print("解析中", end="", flush=True)

        while time.time() - start_time < timeout:
            job_status = self.get_job_status(job_id)
            status = job_status.get("status")

            if status == "success":
                print("\n解析成功!")
                return job_id
            elif status == "failure":
                print("\n解析失敗: 星が検出できませんでした")
                return None

            print(".", end="", flush=True)
            time.sleep(5)

        print("\nタイムアウト")
        return None


class WCSTransformer:
    """WCS（World Coordinate System）による座標変換"""

    def __init__(self, wcs_data: bytes):
        """
        WCS FITSファイルから変換パラメータを読み込む
        """
        # FITSヘッダーをパース
        self.header = self._parse_fits_header(wcs_data)

        # 基準点
        self.crpix1 = float(self.header.get("CRPIX1", 0))
        self.crpix2 = float(self.header.get("CRPIX2", 0))
        self.crval1 = float(self.header.get("CRVAL1", 0))
        self.crval2 = float(self.header.get("CRVAL2", 0))

        # CD行列（ピクセル→天球座標の変換）
        self.cd11 = float(self.header.get("CD1_1", 0))
        self.cd12 = float(self.header.get("CD1_2", 0))
        self.cd21 = float(self.header.get("CD2_1", 0))
        self.cd22 = float(self.header.get("CD2_2", 0))

        # SIPゆがみ係数（あれば）
        self.sip_a = self._parse_sip_coeffs("A")
        self.sip_b = self._parse_sip_coeffs("B")
        self.sip_ap = self._parse_sip_coeffs("AP")
        self.sip_bp = self._parse_sip_coeffs("BP")

        # CD行列の逆行列を計算
        det = self.cd11 * self.cd22 - self.cd12 * self.cd21
        if abs(det) > 1e-10:
            self.cdinv11 = self.cd22 / det
            self.cdinv12 = -self.cd12 / det
            self.cdinv21 = -self.cd21 / det
            self.cdinv22 = self.cd11 / det
        else:
            raise ValueError("CD行列が特異です")

        print(f"WCS読み込み完了:")
        print(f"  基準点: ({self.crpix1:.1f}, {self.crpix2:.1f})")
        print(f"  天球座標: RA={self.crval1:.2f}°, Dec={self.crval2:.2f}°")
        print(f"  スケール: {abs(self.cd11)*3600:.2f} arcsec/pixel")

    def _parse_fits_header(self, data: bytes) -> dict:
        """FITSヘッダーをパース"""
        header = {}
        # FITSヘッダーは80バイト固定長のカード
        text = data.decode('ascii', errors='ignore')

        for i in range(0, len(text), 80):
            card = text[i:i+80]
            if card.startswith("END"):
                break
            if "=" in card:
                key = card[:8].strip()
                value_part = card[9:].split("/")[0].strip()
                # 文字列か数値か判定
                if value_part.startswith("'"):
                    value = value_part.strip("' ")
                else:
                    try:
                        value = float(value_part)
                    except:
                        value = value_part
                header[key] = value

        return header

    def _parse_sip_coeffs(self, prefix: str) -> dict:
        """SIP係数をパース"""
        coeffs = {}
        for key, value in self.header.items():
            if key.startswith(prefix + "_") and isinstance(value, (int, float)):
                parts = key.split("_")
                if len(parts) == 3:
                    try:
                        i, j = int(parts[1]), int(parts[2])
                        coeffs[(i, j)] = value
                    except:
                        pass
        return coeffs

    def _apply_sip_forward(self, u: float, v: float) -> Tuple[float, float]:
        """SIP順変換（ピクセル→中間座標のゆがみ補正）"""
        f = g = 0.0
        for (i, j), coeff in self.sip_a.items():
            f += coeff * (u ** i) * (v ** j)
        for (i, j), coeff in self.sip_b.items():
            g += coeff * (u ** i) * (v ** j)
        return u + f, v + g

    def _apply_sip_inverse(self, u: float, v: float) -> Tuple[float, float]:
        """SIP逆変換（中間座標→ピクセルのゆがみ補正）"""
        f = g = 0.0
        for (i, j), coeff in self.sip_ap.items():
            f += coeff * (u ** i) * (v ** j)
        for (i, j), coeff in self.sip_bp.items():
            g += coeff * (u ** i) * (v ** j)
        return u + f, v + g

    def radec_to_pixel(self, ra: float, dec: float) -> Optional[Tuple[float, float]]:
        """
        天球座標（赤経・赤緯）からピクセル座標に変換

        Args:
            ra: 赤経（度）
            dec: 赤緯（度）

        Returns:
            (x, y) ピクセル座標、視野外ならNone
        """
        # 度をラジアンに
        ra_rad = np.radians(ra)
        dec_rad = np.radians(dec)
        crval1_rad = np.radians(self.crval1)
        crval2_rad = np.radians(self.crval2)

        # 球面三角法で投影
        # gnomonic (TAN) projection
        cos_c = (np.sin(crval2_rad) * np.sin(dec_rad) +
                 np.cos(crval2_rad) * np.cos(dec_rad) * np.cos(ra_rad - crval1_rad))

        if cos_c <= 0:
            return None  # 視野の反対側

        xi = (np.cos(dec_rad) * np.sin(ra_rad - crval1_rad)) / cos_c
        eta = (np.cos(crval2_rad) * np.sin(dec_rad) -
               np.sin(crval2_rad) * np.cos(dec_rad) * np.cos(ra_rad - crval1_rad)) / cos_c

        # ラジアンから度に
        xi = np.degrees(xi)
        eta = np.degrees(eta)

        # CD行列の逆変換
        u = self.cdinv11 * xi + self.cdinv12 * eta
        v = self.cdinv21 * xi + self.cdinv22 * eta

        # SIP逆変換（ゆがみ補正）
        if self.sip_ap or self.sip_bp:
            u, v = self._apply_sip_inverse(u, v)

        # ピクセル座標
        x = u + self.crpix1
        y = v + self.crpix2

        return x, y


def draw_constellation_lines(
    image: np.ndarray,
    wcs: WCSTransformer,
    constellation: ConstellationData,
    line_color: Tuple[int, int, int] = (0, 255, 255),
    line_thickness: int = 2,
    draw_labels: bool = True,
    label_color: Tuple[int, int, int] = (255, 255, 255)
) -> np.ndarray:
    """
    星座線を描画

    Args:
        image: 入力画像
        wcs: WCS変換器
        constellation: 星座データ
        line_color: 線の色 (B, G, R)
        line_thickness: 線の太さ
        draw_labels: 星名を描画するか
        label_color: ラベルの色

    Returns:
        描画後の画像
    """
    result = image.copy()
    height, width = image.shape[:2]

    # 各星のピクセル座標を計算
    star_positions = []
    for star in constellation.stars:
        pos = wcs.radec_to_pixel(star.ra, star.dec)
        if pos:
            x, y = pos
            # 画像範囲内かチェック（少し余裕を持たせる）
            if -width * 0.1 <= x <= width * 1.1 and -height * 0.1 <= y <= height * 1.1:
                star_positions.append((int(x), int(y), star.name))
            else:
                star_positions.append(None)
        else:
            star_positions.append(None)

    # 星座線を描画
    lines_drawn = 0
    for start_idx, end_idx in constellation.lines:
        start_pos = star_positions[start_idx]
        end_pos = star_positions[end_idx]

        if start_pos and end_pos:
            cv2.line(result,
                    (start_pos[0], start_pos[1]),
                    (end_pos[0], end_pos[1]),
                    line_color, line_thickness, cv2.LINE_AA)
            lines_drawn += 1

    # 星の位置にマーカーと名前を描画
    for pos in star_positions:
        if pos:
            x, y, name = pos
            if 0 <= x < width and 0 <= y < height:
                # 星のマーカー
                cv2.circle(result, (x, y), 5, line_color, 2, cv2.LINE_AA)

                # 星名（オプション）
                if draw_labels:
                    cv2.putText(result, name, (x + 8, y - 5),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                               label_color, 1, cv2.LINE_AA)

    # 星座名を描画
    if lines_drawn > 0:
        # 描画された星の中心を計算
        valid_positions = [p for p in star_positions if p]
        if valid_positions:
            center_x = int(np.mean([p[0] for p in valid_positions]))
            center_y = int(np.min([p[1] for p in valid_positions])) - 30
            center_y = max(25, center_y)

            label = f"{constellation.name_jp}"
            cv2.putText(result, label, (center_x - 30, center_y),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                       line_color, 2, cv2.LINE_AA)

    visible_stars = sum(1 for p in star_positions if p)
    print(f"  {constellation.name_jp}: {visible_stars}/{len(constellation.stars)}星, {lines_drawn}本の線を描画")

    return result


def process_with_astrometry(
    input_path: str,
    output_path: str,
    api_key: str,
    constellation_names: List[str],
    line_color: Tuple[int, int, int] = (0, 255, 255),
    draw_labels: bool = True,
    timeout: int = 300
) -> bool:
    """
    Astrometry.netを使って画像を処理

    Args:
        input_path: 入力画像パス
        output_path: 出力画像パス
        api_key: Astrometry.net APIキー
        constellation_names: 描画する星座名のリスト
        line_color: 線の色
        draw_labels: 星名を描画するか
        timeout: タイムアウト（秒）

    Returns:
        成功したらTrue
    """
    # 画像を読み込み
    image = cv2.imread(input_path)
    if image is None:
        print(f"エラー: 画像を読み込めません: {input_path}")
        return False

    print(f"画像サイズ: {image.shape[1]}x{image.shape[0]}")

    # Astrometry.netにログイン
    client = AstrometryClient(api_key)
    if not client.login():
        return False

    # 画像をアップロード
    submission_id = client.upload_image(input_path)
    if submission_id is None:
        return False

    # 解析完了を待機
    job_id = client.wait_for_job(submission_id, timeout)
    if job_id is None:
        return False

    # キャリブレーション情報を表示
    calibration = client.get_job_calibration(job_id)
    if calibration:
        print(f"\nキャリブレーション結果:")
        print(f"  中心座標: RA={calibration.get('ra', 0):.2f}°, Dec={calibration.get('dec', 0):.2f}°")
        print(f"  視野角: {calibration.get('radius', 0):.2f}°")
        print(f"  回転角: {calibration.get('orientation', 0):.1f}°")
        print(f"  ピクセルスケール: {calibration.get('pixscale', 0):.2f} arcsec/pixel")

    # WCSファイルを取得
    wcs_data = client.get_wcs_file(job_id)
    if wcs_data is None:
        print("エラー: WCSファイルを取得できません")
        return False

    # WCS変換器を初期化
    try:
        wcs = WCSTransformer(wcs_data)
    except Exception as e:
        print(f"エラー: WCS解析に失敗: {e}")
        return False

    # 星座を描画
    result = image.copy()
    print("\n星座線を描画中...")

    for name in constellation_names:
        name_lower = name.lower()
        if name_lower not in CONSTELLATIONS:
            print(f"  警告: 星座 '{name}' はデータベースにありません")
            continue

        constellation = CONSTELLATIONS[name_lower]
        result = draw_constellation_lines(
            result, wcs, constellation,
            line_color=line_color,
            draw_labels=draw_labels
        )

    # 結果を保存
    cv2.imwrite(output_path, result)
    print(f"\n出力: {output_path}")

    return True


def process_with_local_wcs(
    input_path: str,
    output_path: str,
    wcs_path: str,
    constellation_names: List[str],
    line_color: Tuple[int, int, int] = (0, 255, 255),
    draw_labels: bool = True
) -> bool:
    """
    ローカルのWCSファイルを使って処理
    """
    image = cv2.imread(input_path)
    if image is None:
        print(f"エラー: 画像を読み込めません: {input_path}")
        return False

    with open(wcs_path, "rb") as f:
        wcs_data = f.read()

    wcs = WCSTransformer(wcs_data)

    result = image.copy()
    print("星座線を描画中...")

    for name in constellation_names:
        name_lower = name.lower()
        if name_lower not in CONSTELLATIONS:
            print(f"  警告: 星座 '{name}' はデータベースにありません")
            continue

        constellation = CONSTELLATIONS[name_lower]
        result = draw_constellation_lines(
            result, wcs, constellation,
            line_color=line_color,
            draw_labels=draw_labels
        )

    cv2.imwrite(output_path, result)
    print(f"\n出力: {output_path}")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Astrometry.netを使った星座線描画",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # 基本的な使い方（APIキーが必要）
  python constellation_drawer_astrometry.py starfield.jpg -o output.jpg -k YOUR_API_KEY

  # 特定の星座を描画
  python constellation_drawer_astrometry.py starfield.jpg -o output.jpg -k YOUR_API_KEY -c orion taurus

  # 全ての星座を試す
  python constellation_drawer_astrometry.py starfield.jpg -o output.jpg -k YOUR_API_KEY -c all

  # ローカルWCSファイルを使用
  python constellation_drawer_astrometry.py starfield.jpg -o output.jpg --wcs solution.wcs -c orion

APIキーの取得:
  1. https://nova.astrometry.net/ にアクセス
  2. アカウントを作成
  3. My Profile → API Key でキーを取得

利用可能な星座:
  orion, bigdipper, cassiopeia, cygnus, scorpius, lyra, taurus, gemini
        """
    )

    parser.add_argument("input", help="入力画像ファイル")
    parser.add_argument("-o", "--output", default="output.jpg",
                       help="出力画像ファイル")
    parser.add_argument("-k", "--api-key",
                       help="Astrometry.net APIキー")
    parser.add_argument("--wcs", help="ローカルWCSファイル（APIを使わない場合）")
    parser.add_argument("-c", "--constellation", nargs="+", default=["all"],
                       help="描画する星座 (default: all)")
    parser.add_argument("--line-color", nargs=3, type=int, default=[0, 255, 255],
                       metavar=("B", "G", "R"),
                       help="線の色 BGR (default: 黄色)")
    parser.add_argument("--no-labels", action="store_true",
                       help="星名を表示しない")
    parser.add_argument("--timeout", type=int, default=300,
                       help="APIタイムアウト秒 (default: 300)")
    parser.add_argument("--list", action="store_true",
                       help="利用可能な星座一覧を表示")

    args = parser.parse_args()

    if args.list:
        print("利用可能な星座:")
        for key, data in CONSTELLATIONS.items():
            print(f"  {key:12} - {data.name_jp} ({data.name})")
        return

    # 星座リストを準備
    if "all" in args.constellation:
        constellation_names = list(CONSTELLATIONS.keys())
    else:
        constellation_names = args.constellation

    # 処理実行
    if args.wcs:
        # ローカルWCSファイルを使用
        success = process_with_local_wcs(
            args.input,
            args.output,
            args.wcs,
            constellation_names,
            line_color=tuple(args.line_color),
            draw_labels=not args.no_labels
        )
    elif args.api_key:
        # Astrometry.net APIを使用
        success = process_with_astrometry(
            args.input,
            args.output,
            args.api_key,
            constellation_names,
            line_color=tuple(args.line_color),
            draw_labels=not args.no_labels,
            timeout=args.timeout
        )
    else:
        print("エラー: --api-key または --wcs を指定してください")
        print("APIキーは https://nova.astrometry.net/ で取得できます")
        return

    if not success:
        exit(1)


if __name__ == "__main__":
    main()
