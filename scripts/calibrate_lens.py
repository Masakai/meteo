#!/usr/bin/env python3
"""
直線構造物（電線・屋根の稜線など）を使ったレンズ歪みキャリブレーション。
プラムライン法（straight-line method）で k1, k2 を推定する。

使い方:
    source .venv/bin/activate
    python scripts/calibrate_lens.py camera1.jpg [--fov 110]

操作:
    - 画像上の「直線であるべき線」（電線・屋根など）をクリックして点を追加
    - 右クリックで最後の点を取り消し
    - 'n' キー / Enterキー: 次の線へ（最低2本、できれば4本以上推奨）
    - 'c' キー: この線の点をリセット
    - 'q' キー: キャリブレーション実行
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.widgets import Button
from scipy.optimize import minimize


# ─────────────────────────────────────────
# 歪み補正の数式
# ─────────────────────────────────────────

def undistort_points(pts_px, cx, cy, fx, fy, k1, k2=0.0, k3=0.0):
    """
    歪んだピクセル座標 → 補正後ピクセル座標（Brown-Conradyモデル）

    pts_px: (N, 2) array of (u, v)
    """
    x = (pts_px[:, 0] - cx) / fx
    y = (pts_px[:, 1] - cy) / fy
    r2 = x**2 + y**2
    factor = 1 + k1 * r2 + k2 * r2**2 + k3 * r2**3
    xu = x * factor
    yu = y * factor
    u = xu * fx + cx
    v = yu * fy + cy
    return np.stack([u, v], axis=1)


def point_to_line_distance_sq(pts, line_coeffs):
    """
    直線 ax + by + c = 0 への点群の距離²の合計
    line_coeffs: (a, b, c)
    """
    a, b, c = line_coeffs
    norm = a**2 + b**2 + 1e-12
    d2 = (a * pts[:, 0] + b * pts[:, 1] + c)**2 / norm
    return d2.sum()


def fit_line_algebraic(pts):
    """点群に最小二乗直線をフィット (a, b, c) を返す"""
    u = pts[:, 0]
    v = pts[:, 1]
    A = np.stack([u, v, np.ones(len(u))], axis=1)
    _, _, Vt = np.linalg.svd(A)
    return Vt[-1]  # (a, b, c)


def calibration_residual(params, lines_px, cx, cy, fx, fy):
    """
    歪み係数 params = [k1] or [k1, k2] を変えたとき、
    各点群が直線に近づく度合い（残差）
    """
    k1 = params[0]
    k2 = params[1] if len(params) > 1 else 0.0

    total = 0.0
    for pts in lines_px:
        pts_u = undistort_points(pts, cx, cy, fx, fy, k1, k2)
        line = fit_line_algebraic(pts_u)
        total += point_to_line_distance_sq(pts_u, line)
    return total


# ─────────────────────────────────────────
# FOVからfx,fyを計算
# ─────────────────────────────────────────

def fov_to_focal(fov_h_deg, fov_v_deg, width, height):
    fov_h = np.radians(fov_h_deg)
    fov_v = np.radians(fov_v_deg)
    fx = (width / 2.0) / np.tan(fov_h / 2.0)
    fy = (height / 2.0) / np.tan(fov_v / 2.0)
    return fx, fy


# ─────────────────────────────────────────
# 角度誤差マップ（三角測量への影響可視化）
# ─────────────────────────────────────────

def compute_angle_error_map(width, height, fx, fy, k1, k2=0.0, step=20):
    """
    歪み補正をしなかった場合の各ピクセルでの方向角誤差（度）マップ
    「補正なし」- 「補正あり」の差
    """
    uu = np.arange(step // 2, width, step)
    vv = np.arange(step // 2, height, step)
    UU, VV = np.meshgrid(uu, vv)
    pts = np.stack([UU.ravel(), VV.ravel()], axis=1).astype(float)

    cx, cy = width / 2, height / 2

    # 補正なし（ピンホールのみ）の方向ベクトル
    xn = (pts[:, 0] - cx) / fx
    yn = (pts[:, 1] - cy) / fy
    dirs_raw = np.stack([xn, yn, np.ones(len(xn))], axis=1)
    dirs_raw /= np.linalg.norm(dirs_raw, axis=1, keepdims=True)

    # 補正ありの方向ベクトル
    pts_u = undistort_points(pts, cx, cy, fx, fy, k1, k2)
    xu = (pts_u[:, 0] - cx) / fx
    yu = (pts_u[:, 1] - cy) / fy
    dirs_cor = np.stack([xu, yu, np.ones(len(xu))], axis=1)
    dirs_cor /= np.linalg.norm(dirs_cor, axis=1, keepdims=True)

    # 2ベクトル間の角度（度）
    dot = np.clip((dirs_raw * dirs_cor).sum(axis=1), -1, 1)
    angle_error = np.degrees(np.arccos(dot))

    return UU, VV, angle_error.reshape(UU.shape)


# ─────────────────────────────────────────
# インタラクティブ点選択
# ─────────────────────────────────────────

class LineCollector:
    """マウスクリックで複数の直線上の点群を収集する"""

    def __init__(self, img_rgb):
        self.img = img_rgb
        self.lines = []          # 確定した線の点群リスト
        self.current = []        # 現在編集中の点群
        self.colors = plt.cm.tab10.colors
        self.done = False

        self.fig, self.ax = plt.subplots(figsize=(14, 8))
        self.fig.canvas.manager.set_window_title(
            "レンズ歪みキャリブレーション — 直線上の点をクリック"
        )
        self.ax.imshow(self.img)
        self.ax.set_title(
            "電線・屋根など直線であるべき箇所をクリック\n"
            "[Enter/n]=次の線  [c]=リセット  [q]=キャリブレーション実行",
            fontsize=11,
        )

        self._scatter = None
        self._confirmed_scatters = []

        self.fig.canvas.mpl_connect("button_press_event", self._on_click)
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)
        self._update_title()

    def _color(self, idx):
        return self.colors[idx % len(self.colors)]

    def _on_click(self, event):
        if event.inaxes != self.ax:
            return
        if event.button == 1:  # 左クリック: 点追加
            self.current.append((event.xdata, event.ydata))
            self._redraw_current()
        elif event.button == 3:  # 右クリック: 取り消し
            if self.current:
                self.current.pop()
                self._redraw_current()

    def _on_key(self, event):
        if event.key in ("n", "enter"):
            self._confirm_line()
        elif event.key == "c":
            self.current = []
            self._redraw_current()
        elif event.key == "q":
            self._confirm_line()
            self.done = True
            plt.close(self.fig)

    def _confirm_line(self):
        if len(self.current) >= 3:
            pts = np.array(self.current)
            self.lines.append(pts)
            color = self._color(len(self.lines) - 1)
            sc = self.ax.scatter(pts[:, 0], pts[:, 1], s=40,
                                 color=color, zorder=5)
            # 点をつなぐ折れ線
            self.ax.plot(pts[:, 0], pts[:, 1], '-', color=color,
                         alpha=0.5, linewidth=1)
            self._confirmed_scatters.append(sc)
            self.fig.canvas.draw()
            print(f"  線 {len(self.lines)}: {len(pts)} 点を確定")
        self.current = []
        self._redraw_current()
        self._update_title()

    def _redraw_current(self):
        if self._scatter:
            self._scatter.remove()
            self._scatter = None
        if self.current:
            pts = np.array(self.current)
            color = self._color(len(self.lines))
            self._scatter = self.ax.scatter(
                pts[:, 0], pts[:, 1], s=50, color=color,
                edgecolors='white', linewidths=0.8, zorder=6,
            )
        self.fig.canvas.draw()

    def _update_title(self):
        n = len(self.lines)
        status = f"確定済み: {n}本"
        if n < 2:
            status += "  ← あと最低 {0}本必要".format(2 - n)
        self.ax.set_title(
            f"[{status}] 電線・屋根など直線上をクリック\n"
            "[Enter/n]=次の線  [c]=リセット  [q]=キャリブレーション実行",
            fontsize=10,
        )
        self.fig.canvas.draw()

    def collect(self):
        plt.tight_layout()
        plt.show()
        return self.lines


# ─────────────────────────────────────────
# 結果の可視化
# ─────────────────────────────────────────

def show_results(img_bgr, k1, k2, fx, fy, lines_px, width, height):
    cx, cy = width / 2, height / 2

    # --- 補正後画像の生成（OpenCV） ---
    cam_mat = np.array([[fx, 0, cx],
                         [0, fy, cy],
                         [0,  0,  1]], dtype=np.float64)
    dist_coeffs = np.array([k1, k2, 0, 0, 0], dtype=np.float64)
    # NOTE: OpenCVの歪みモデルは「理想→歪み」方向なので符号が逆になることに注意。
    # ここでは「歪み→理想」の逆補正をかける。
    img_undist = cv2.undistort(img_bgr, cam_mat, dist_coeffs)

    # --- 角度誤差マップ ---
    UU, VV, err_map = compute_angle_error_map(width, height, fx, fy, k1, k2)

    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle(
        f"レンズ歪みキャリブレーション結果\n"
        f"k1 = {k1:.4f}  k2 = {k2:.4f}  "
        f"(fx={fx:.1f}, fy={fy:.1f})",
        fontsize=13,
    )

    # (0,0) 元画像 + キャリブレーション点
    ax0 = axes[0, 0]
    ax0.imshow(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    ax0.set_title("元画像（歪みあり）")
    colors = plt.cm.tab10.colors
    for i, pts in enumerate(lines_px):
        ax0.scatter(pts[:, 0], pts[:, 1], s=30,
                    color=colors[i % len(colors)], zorder=5)
        ax0.plot(pts[:, 0], pts[:, 1], '-',
                 color=colors[i % len(colors)], alpha=0.5)

    # (0,1) 補正後画像
    ax1 = axes[0, 1]
    ax1.imshow(cv2.cvtColor(img_undist, cv2.COLOR_BGR2RGB))
    ax1.set_title("補正後画像")
    # 補正後の点を重ねる
    for i, pts in enumerate(lines_px):
        pts_u = undistort_points(pts, cx, cy, fx, fy, k1, k2)
        ax1.scatter(pts_u[:, 0], pts_u[:, 1], s=30,
                    color=colors[i % len(colors)], zorder=5)
        # フィット直線
        line = fit_line_algebraic(pts_u)
        a, b, c = line
        if abs(b) > 1e-6:
            u_range = np.array([0, width])
            v_fit = -(a * u_range + c) / b
            ax1.plot(u_range, v_fit, '--',
                     color=colors[i % len(colors)], alpha=0.7)

    # (1,0) 角度誤差ヒートマップ
    ax2 = axes[1, 0]
    hm = ax2.pcolormesh(UU, VV, err_map, cmap='hot_r', shading='auto')
    fig.colorbar(hm, ax=ax2, label='角度誤差（度）')
    ax2.set_xlim(0, width)
    ax2.set_ylim(height, 0)
    ax2.set_title("補正なし時の方向角誤差マップ\n（三角測量への影響）")
    ax2.set_aspect('equal')

    # (1,1) 元画像との差分（歪みの可視化）
    ax3 = axes[1, 1]
    diff = cv2.absdiff(img_bgr, img_undist).astype(float)
    diff_gray = diff.mean(axis=2)
    im = ax3.imshow(diff_gray, cmap='magma', vmin=0, vmax=diff_gray.max())
    fig.colorbar(im, ax=ax3, label='ピクセル差（輝度）')
    ax3.set_title("元画像 vs 補正後の差分\n（赤いほど歪みが大きかった箇所）")

    plt.tight_layout()
    plt.show()

    # 補正後画像を保存
    return img_undist


# ─────────────────────────────────────────
# メイン
# ─────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="プラムライン法レンズ歪みキャリブレーション")
    parser.add_argument("image", help="入力画像パス (例: camera1.jpg)")
    parser.add_argument("--fov-h", type=float, default=110.0,
                        help="水平FOV（度）デフォルト: 110")
    parser.add_argument("--fov-v", type=float, default=62.0,
                        help="垂直FOV（度）デフォルト: 62")
    parser.add_argument("--k2", action="store_true",
                        help="k2も最適化する（点が多い場合に有効）")
    args = parser.parse_args()

    img_path = Path(args.image)
    if not img_path.exists():
        print(f"エラー: {img_path} が見つかりません")
        sys.exit(1)

    img_bgr = cv2.imread(str(img_path))
    if img_bgr is None:
        print(f"エラー: 画像を読み込めません: {img_path}")
        sys.exit(1)

    height, width = img_bgr.shape[:2]
    cx, cy = width / 2.0, height / 2.0
    fx, fy = fov_to_focal(args.fov_h, args.fov_v, width, height)

    print(f"\n画像サイズ: {width}x{height}")
    print(f"FOV: H={args.fov_h}°, V={args.fov_v}°")
    print(f"焦点距離: fx={fx:.1f}, fy={fy:.1f} px")
    print(f"\n--- 点を選択してください ---")
    print("電線・屋根の稜線など、直線であるはずの箇所をクリック")
    print("[Enter/n] 次の線  [c] リセット  [q] キャリブレーション開始\n")

    # 点の収集
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    collector = LineCollector(img_rgb)
    lines_px = collector.collect()

    if len(lines_px) < 2:
        print("最低2本の線が必要です。終了します。")
        sys.exit(0)

    total_pts = sum(len(l) for l in lines_px)
    print(f"\n{len(lines_px)}本の線、合計{total_pts}点で最適化します...")

    # 最適化
    x0 = [0.0, 0.0] if args.k2 else [0.0]

    result = minimize(
        calibration_residual,
        x0,
        args=(lines_px, cx, cy, fx, fy),
        method="Nelder-Mead",
        options={"xatol": 1e-6, "fatol": 1e-6, "maxiter": 10000},
    )

    k1 = result.x[0]
    k2 = result.x[1] if args.k2 else 0.0

    print(f"\n=== キャリブレーション結果 ===")
    print(f"k1 = {k1:.6f}")
    if args.k2:
        print(f"k2 = {k2:.6f}")
    print(f"残差: {result.fun:.2f} px²")
    print(f"収束: {result.success}")

    # 各ピクセル端での角度誤差
    corner_pts = np.array([[0, 0], [width, 0], [0, height], [width, height]], dtype=float)
    corner_u = undistort_points(corner_pts, cx, cy, fx, fy, k1, k2)
    # コーナーの角度誤差
    for (u, v), (uu, vv) in zip(corner_pts, corner_u):
        x_raw = (u - cx) / fx
        y_raw = (v - cy) / fy
        d_raw = np.array([x_raw, y_raw, 1.0])
        d_raw /= np.linalg.norm(d_raw)
        xu = (uu - cx) / fx
        yu = (vv - cy) / fy
        d_cor = np.array([xu, yu, 1.0])
        d_cor /= np.linalg.norm(d_cor)
        err_deg = np.degrees(np.arccos(np.clip(np.dot(d_raw, d_cor), -1, 1)))
        print(f"  コーナー ({int(u)},{int(v)}): 補正なし時の角度誤差 {err_deg:.2f}°")

    print(f"\n--- station.json への記載例 ---")
    print(f'"distortion_k1": {k1:.6f},')
    if args.k2:
        print(f'"distortion_k2": {k2:.6f},')

    # 結果の可視化
    img_undist = show_results(img_bgr, k1, k2, fx, fy, lines_px, width, height)

    # 補正後画像を保存
    out_path = img_path.with_stem(img_path.stem + "_undistorted")
    cv2.imwrite(str(out_path), img_undist)
    print(f"\n補正後画像を保存: {out_path}")


if __name__ == "__main__":
    main()
