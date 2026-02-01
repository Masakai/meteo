#!/usr/bin/env python3
"""
星空画像に星座線を描画するプログラム

使い方:
    python constellation_drawer.py input_image.jpg --output output.jpg --constellation orion
"""

import argparse
import cv2
import numpy as np
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict
import json


@dataclass
class Star:
    """検出された星を表すクラス"""
    x: float
    y: float
    brightness: float
    radius: float


@dataclass
class ConstellationStar:
    """星座を構成する星の相対位置"""
    name: str
    relative_x: float  # 0-1の相対座標
    relative_y: float  # 0-1の相対座標


@dataclass
class ConstellationData:
    """星座データ"""
    name: str
    name_jp: str
    stars: List[ConstellationStar]
    lines: List[Tuple[int, int]]  # 星のインデックスペア


# 星座データベース
CONSTELLATIONS: Dict[str, ConstellationData] = {
    "orion": ConstellationData(
        name="Orion",
        name_jp="オリオン座",
        stars=[
            ConstellationStar("Betelgeuse", 0.2, 0.15),      # 0: ベテルギウス（左肩）
            ConstellationStar("Bellatrix", 0.8, 0.18),       # 1: ベラトリックス（右肩）
            ConstellationStar("Alnitak", 0.35, 0.45),        # 2: アルニタク（三ツ星左）
            ConstellationStar("Alnilam", 0.5, 0.45),         # 3: アルニラム（三ツ星中）
            ConstellationStar("Mintaka", 0.65, 0.45),        # 4: ミンタカ（三ツ星右）
            ConstellationStar("Saiph", 0.25, 0.85),          # 5: サイフ（左足）
            ConstellationStar("Rigel", 0.75, 0.85),          # 6: リゲル（右足）
        ],
        lines=[
            (0, 2), (1, 4),      # 肩から三ツ星へ
            (2, 3), (3, 4),      # 三ツ星
            (2, 5), (4, 6),      # 三ツ星から足へ
            (0, 1),              # 両肩
            (5, 6),              # 両足（オプション）
        ]
    ),
    "bigdipper": ConstellationData(
        name="Big Dipper",
        name_jp="北斗七星",
        stars=[
            ConstellationStar("Dubhe", 0.0, 0.0),        # 0: ドゥーベ
            ConstellationStar("Merak", 0.0, 0.2),        # 1: メラク
            ConstellationStar("Phecda", 0.2, 0.25),      # 2: フェクダ
            ConstellationStar("Megrez", 0.3, 0.1),       # 3: メグレズ
            ConstellationStar("Alioth", 0.5, 0.05),      # 4: アリオト
            ConstellationStar("Mizar", 0.7, 0.0),        # 5: ミザール
            ConstellationStar("Alkaid", 0.95, 0.05),     # 6: アルカイド
        ],
        lines=[
            (0, 1), (1, 2), (2, 3), (3, 0),  # 柄杓の器部分
            (3, 4), (4, 5), (5, 6),          # 柄杓の柄部分
        ]
    ),
    "cassiopeia": ConstellationData(
        name="Cassiopeia",
        name_jp="カシオペア座",
        stars=[
            ConstellationStar("Schedar", 0.0, 0.3),      # 0: シェダル
            ConstellationStar("Caph", 0.2, 0.0),         # 1: カフ
            ConstellationStar("Gamma", 0.4, 0.4),        # 2: γ星
            ConstellationStar("Ruchbah", 0.6, 0.1),      # 3: ルクバー
            ConstellationStar("Segin", 0.85, 0.35),      # 4: セギン
        ],
        lines=[
            (0, 1), (1, 2), (2, 3), (3, 4),  # W字型
        ]
    ),
    "cygnus": ConstellationData(
        name="Cygnus",
        name_jp="はくちょう座",
        stars=[
            ConstellationStar("Deneb", 0.5, 0.0),        # 0: デネブ（尾）
            ConstellationStar("Sadr", 0.5, 0.35),        # 1: サドル（中心）
            ConstellationStar("Gienah", 0.2, 0.5),       # 2: ギェナー（左翼）
            ConstellationStar("Delta", 0.8, 0.5),        # 3: δ星（右翼）
            ConstellationStar("Albireo", 0.5, 0.9),      # 4: アルビレオ（頭）
        ],
        lines=[
            (0, 1), (1, 4),        # 縦線（体）
            (2, 1), (1, 3),        # 横線（翼）
        ]
    ),
    "scorpius": ConstellationData(
        name="Scorpius",
        name_jp="さそり座",
        stars=[
            ConstellationStar("Antares", 0.3, 0.3),      # 0: アンタレス
            ConstellationStar("Graffias", 0.15, 0.1),    # 1: グラフィアス
            ConstellationStar("Dschubba", 0.25, 0.15),   # 2: ジュバ
            ConstellationStar("Pi", 0.1, 0.2),           # 3: π星
            ConstellationStar("Sigma", 0.35, 0.45),      # 4: σ星
            ConstellationStar("Tau", 0.5, 0.55),         # 5: τ星
            ConstellationStar("Epsilon", 0.6, 0.65),     # 6: ε星
            ConstellationStar("Shaula", 0.85, 0.85),     # 7: シャウラ（尾）
            ConstellationStar("Lesath", 0.9, 0.9),       # 8: レサト
        ],
        lines=[
            (3, 1), (1, 2), (2, 0),    # 頭部
            (0, 4), (4, 5), (5, 6), (6, 7), (7, 8),  # 体と尾
        ]
    ),
}


class StarDetector:
    """画像から星を検出するクラス"""

    def __init__(self,
                 min_brightness: int = 200,
                 min_area: int = 3,
                 max_area: int = 500):
        self.min_brightness = min_brightness
        self.min_area = min_area
        self.max_area = max_area

    def detect(self, image: np.ndarray) -> List[Star]:
        """画像から星を検出"""
        # グレースケールに変換
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()

        # ガウシアンブラーでノイズ除去
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)

        # 閾値処理で明るい点を抽出
        _, thresh = cv2.threshold(blurred, self.min_brightness, 255, cv2.THRESH_BINARY)

        # 輪郭検出
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        stars = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if self.min_area <= area <= self.max_area:
                # 重心を計算
                M = cv2.moments(contour)
                if M["m00"] > 0:
                    cx = M["m10"] / M["m00"]
                    cy = M["m01"] / M["m00"]

                    # 明るさを取得
                    mask = np.zeros(gray.shape, dtype=np.uint8)
                    cv2.drawContours(mask, [contour], -1, 255, -1)
                    brightness = cv2.mean(gray, mask=mask)[0]

                    # 半径を計算
                    radius = np.sqrt(area / np.pi)

                    stars.append(Star(cx, cy, brightness, radius))

        # 明るさでソート（明るい順）
        stars.sort(key=lambda s: s.brightness, reverse=True)

        return stars


class ConstellationMatcher:
    """検出された星と星座パターンをマッチング"""

    def __init__(self, tolerance: float = 0.15):
        self.tolerance = tolerance

    def match(self,
              stars: List[Star],
              constellation: ConstellationData,
              image_width: int,
              image_height: int,
              roi: Optional[Tuple[int, int, int, int]] = None) -> Optional[List[Tuple[int, int]]]:
        """
        星座パターンをマッチング

        Args:
            stars: 検出された星のリスト
            constellation: 星座データ
            image_width: 画像幅
            image_height: 画像高さ
            roi: 検索領域 (x, y, width, height)、Noneなら画像全体

        Returns:
            マッチした場合は線のリスト [(x1,y1,x2,y2), ...]、マッチしない場合はNone
        """
        if roi:
            rx, ry, rw, rh = roi
        else:
            rx, ry, rw, rh = 0, 0, image_width, image_height

        # 星座の星を画像座標に変換
        constellation_points = []
        for cs in constellation.stars:
            px = rx + cs.relative_x * rw
            py = ry + cs.relative_y * rh
            constellation_points.append((px, py))

        # 各星座の星に最も近い検出星を見つける
        matched_stars = []
        used_indices = set()

        for i, (px, py) in enumerate(constellation_points):
            best_match = None
            best_dist = float('inf')

            for j, star in enumerate(stars):
                if j in used_indices:
                    continue

                dist = np.sqrt((star.x - px)**2 + (star.y - py)**2)
                # 許容範囲内かチェック
                max_dist = self.tolerance * max(rw, rh)

                if dist < max_dist and dist < best_dist:
                    best_dist = dist
                    best_match = j

            if best_match is not None:
                matched_stars.append(best_match)
                used_indices.add(best_match)
            else:
                # 星が見つからない場合は星座の位置をそのまま使う
                matched_stars.append(None)

        # 線を生成
        lines = []
        for start_idx, end_idx in constellation.lines:
            if matched_stars[start_idx] is not None:
                start_star = stars[matched_stars[start_idx]]
                x1, y1 = int(start_star.x), int(start_star.y)
            else:
                x1, y1 = int(constellation_points[start_idx][0]), int(constellation_points[start_idx][1])

            if matched_stars[end_idx] is not None:
                end_star = stars[matched_stars[end_idx]]
                x2, y2 = int(end_star.x), int(end_star.y)
            else:
                x2, y2 = int(constellation_points[end_idx][0]), int(constellation_points[end_idx][1])

            lines.append((x1, y1, x2, y2))

        return lines


class ConstellationDrawer:
    """星座線を描画するクラス"""

    def __init__(self,
                 line_color: Tuple[int, int, int] = (0, 255, 255),  # 黄色（BGR）
                 line_thickness: int = 2,
                 star_color: Tuple[int, int, int] = (0, 255, 0),   # 緑
                 draw_star_circles: bool = True,
                 draw_labels: bool = True,
                 font_scale: float = 0.5):
        self.line_color = line_color
        self.line_thickness = line_thickness
        self.star_color = star_color
        self.draw_star_circles = draw_star_circles
        self.draw_labels = draw_labels
        self.font_scale = font_scale

    def draw(self,
             image: np.ndarray,
             lines: List[Tuple[int, int, int, int]],
             constellation: ConstellationData,
             matched_positions: Optional[List[Tuple[int, int]]] = None) -> np.ndarray:
        """
        星座線を描画

        Args:
            image: 入力画像
            lines: 描画する線のリスト [(x1,y1,x2,y2), ...]
            constellation: 星座データ
            matched_positions: マッチした星の位置（オプション）

        Returns:
            描画後の画像
        """
        result = image.copy()

        # 線を描画（アンチエイリアス付き）
        for x1, y1, x2, y2 in lines:
            cv2.line(result, (x1, y1), (x2, y2),
                    self.line_color, self.line_thickness, cv2.LINE_AA)

        # 星のマーカーを描画
        if self.draw_star_circles and matched_positions:
            for pos in matched_positions:
                if pos:
                    cv2.circle(result, pos, 5, self.star_color, 2, cv2.LINE_AA)

        # 星座名を描画
        if self.draw_labels and lines:
            # 星座の中心付近にラベルを配置
            all_x = [l[0] for l in lines] + [l[2] for l in lines]
            all_y = [l[1] for l in lines] + [l[3] for l in lines]
            center_x = int(np.mean(all_x))
            center_y = int(np.min(all_y)) - 20  # 上部に配置

            # 日本語名と英語名を表示
            label = f"{constellation.name_jp} ({constellation.name})"
            cv2.putText(result, constellation.name, (center_x - 30, center_y),
                       cv2.FONT_HERSHEY_SIMPLEX, self.font_scale,
                       self.line_color, 1, cv2.LINE_AA)

        return result


def process_image(input_path: str,
                  output_path: str,
                  constellation_names: List[str],
                  roi: Optional[Tuple[int, int, int, int]] = None,
                  min_brightness: int = 180,
                  auto_detect: bool = True,
                  line_color: Tuple[int, int, int] = (0, 255, 255),
                  show_detected_stars: bool = False) -> None:
    """
    画像を処理して星座線を描画

    Args:
        input_path: 入力画像パス
        output_path: 出力画像パス
        constellation_names: 描画する星座名のリスト
        roi: 検索領域 (x, y, width, height)
        min_brightness: 星検出の最小明るさ
        auto_detect: 星を自動検出するか
        line_color: 線の色 (B, G, R)
        show_detected_stars: 検出した星を表示するか
    """
    # 画像読み込み
    image = cv2.imread(input_path)
    if image is None:
        raise ValueError(f"画像を読み込めません: {input_path}")

    height, width = image.shape[:2]
    result = image.copy()

    # 星を検出
    if auto_detect:
        detector = StarDetector(min_brightness=min_brightness)
        stars = detector.detect(image)
        print(f"検出された星の数: {len(stars)}")

        # 検出した星を表示（デバッグ用）
        if show_detected_stars:
            for i, star in enumerate(stars[:50]):  # 上位50個
                cv2.circle(result, (int(star.x), int(star.y)),
                          int(star.radius) + 2, (255, 0, 0), 1)
                cv2.putText(result, str(i), (int(star.x) + 5, int(star.y)),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.3, (255, 255, 255), 1)
    else:
        stars = []

    # 各星座を処理
    matcher = ConstellationMatcher(tolerance=0.2)
    drawer = ConstellationDrawer(line_color=line_color)

    for name in constellation_names:
        name_lower = name.lower()
        if name_lower not in CONSTELLATIONS:
            print(f"警告: 星座 '{name}' はデータベースにありません")
            print(f"利用可能な星座: {', '.join(CONSTELLATIONS.keys())}")
            continue

        constellation = CONSTELLATIONS[name_lower]
        print(f"処理中: {constellation.name_jp} ({constellation.name})")

        # マッチングと描画
        lines = matcher.match(stars, constellation, width, height, roi)
        if lines:
            result = drawer.draw(result, lines, constellation)

    # 結果を保存
    cv2.imwrite(output_path, result)
    print(f"出力: {output_path}")


def interactive_mode(input_path: str, output_path: str) -> None:
    """
    インタラクティブモード: マウスで領域を選択して星座を配置
    """
    image = cv2.imread(input_path)
    if image is None:
        raise ValueError(f"画像を読み込めません: {input_path}")

    result = image.copy()
    drawing = False
    roi_start = None
    roi_end = None

    def mouse_callback(event, x, y, flags, param):
        nonlocal drawing, roi_start, roi_end, result

        if event == cv2.EVENT_LBUTTONDOWN:
            drawing = True
            roi_start = (x, y)

        elif event == cv2.EVENT_MOUSEMOVE and drawing:
            temp = image.copy()
            cv2.rectangle(temp, roi_start, (x, y), (0, 255, 0), 2)
            cv2.imshow("Select ROI", temp)

        elif event == cv2.EVENT_LBUTTONUP:
            drawing = False
            roi_end = (x, y)

    cv2.namedWindow("Select ROI")
    cv2.setMouseCallback("Select ROI", mouse_callback)

    print("\n=== インタラクティブモード ===")
    print("マウスで星座を配置する領域を選択してください")
    print("キー操作:")
    print("  1-5: 星座を選択")
    print("  1: オリオン座")
    print("  2: 北斗七星")
    print("  3: カシオペア座")
    print("  4: はくちょう座")
    print("  5: さそり座")
    print("  r: リセット")
    print("  s: 保存")
    print("  q: 終了")

    constellation_keys = {
        ord('1'): 'orion',
        ord('2'): 'bigdipper',
        ord('3'): 'cassiopeia',
        ord('4'): 'cygnus',
        ord('5'): 'scorpius',
    }

    while True:
        cv2.imshow("Select ROI", result)
        key = cv2.waitKey(1) & 0xFF

        if key == ord('q'):
            break
        elif key == ord('r'):
            result = image.copy()
            roi_start = roi_end = None
        elif key == ord('s'):
            cv2.imwrite(output_path, result)
            print(f"保存しました: {output_path}")
        elif key in constellation_keys and roi_start and roi_end:
            # ROI計算
            x1, y1 = min(roi_start[0], roi_end[0]), min(roi_start[1], roi_end[1])
            x2, y2 = max(roi_start[0], roi_end[0]), max(roi_start[1], roi_end[1])
            roi = (x1, y1, x2 - x1, y2 - y1)

            # 星座描画
            constellation_name = constellation_keys[key]
            constellation = CONSTELLATIONS[constellation_name]

            detector = StarDetector(min_brightness=150)
            stars = detector.detect(image)

            matcher = ConstellationMatcher(tolerance=0.25)
            lines = matcher.match(stars, constellation,
                                 image.shape[1], image.shape[0], roi)

            if lines:
                drawer = ConstellationDrawer()
                result = drawer.draw(result, lines, constellation)
                print(f"描画: {constellation.name_jp}")

            roi_start = roi_end = None

    cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(
        description="星空画像に星座線を描画する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # オリオン座を描画
  python constellation_drawer.py starfield.jpg -o output.jpg -c orion

  # 複数の星座を描画
  python constellation_drawer.py starfield.jpg -o output.jpg -c orion bigdipper

  # インタラクティブモード
  python constellation_drawer.py starfield.jpg -o output.jpg --interactive

  # 検出した星を表示（デバッグ用）
  python constellation_drawer.py starfield.jpg -o output.jpg -c orion --show-stars

利用可能な星座:
  orion      - オリオン座
  bigdipper  - 北斗七星
  cassiopeia - カシオペア座
  cygnus     - はくちょう座
  scorpius   - さそり座
        """
    )

    parser.add_argument("input", help="入力画像ファイル")
    parser.add_argument("-o", "--output", default="output.jpg",
                       help="出力画像ファイル (default: output.jpg)")
    parser.add_argument("-c", "--constellation", nargs="+", default=["orion"],
                       help="描画する星座名 (default: orion)")
    parser.add_argument("--roi", nargs=4, type=int, metavar=("X", "Y", "W", "H"),
                       help="検索領域 (x y width height)")
    parser.add_argument("--min-brightness", type=int, default=180,
                       help="星検出の最小明るさ (0-255, default: 180)")
    parser.add_argument("--line-color", nargs=3, type=int, default=[0, 255, 255],
                       metavar=("B", "G", "R"),
                       help="線の色 BGR (default: 0 255 255 = 黄色)")
    parser.add_argument("--interactive", "-i", action="store_true",
                       help="インタラクティブモード")
    parser.add_argument("--show-stars", action="store_true",
                       help="検出した星を表示（デバッグ用）")
    parser.add_argument("--list", action="store_true",
                       help="利用可能な星座一覧を表示")

    args = parser.parse_args()

    if args.list:
        print("利用可能な星座:")
        for key, data in CONSTELLATIONS.items():
            print(f"  {key:12} - {data.name_jp} ({data.name})")
        return

    if args.interactive:
        interactive_mode(args.input, args.output)
    else:
        roi = tuple(args.roi) if args.roi else None
        process_image(
            args.input,
            args.output,
            args.constellation,
            roi=roi,
            min_brightness=args.min_brightness,
            line_color=tuple(args.line_color),
            show_detected_stars=args.show_stars
        )


if __name__ == "__main__":
    main()
