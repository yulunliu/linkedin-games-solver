"""
從截圖中找出 Tango 棋盤的邊界，並切出 N x N 每一格的座標。

假設：
  - 輸入圖片已經是「大致裁切過的棋盤」(可以包含一點點邊框/留白，
    但棋盤應佔畫面中主要、對比最明顯的正方形區域)。
  - 棋盤本身是由淺色格線分隔的正方形網格 (N 通常是偶數，如 6)。

策略：
  1. 用邊緣偵測 + 輪廓找出畫面中最大的「近似正方形」區域，當作棋盤外框。
  2. 在棋盤內用 Hough 直線偵測抓出水平/垂直格線的位置，
     依線的分布數量推算 N (格線數 - 1 = N)。
  3. 若偵測不到清楚的格線 (line 太淺、太細)，退回使用指定的 --grid-size，
     直接把棋盤區域均分成 N x N。
"""

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class BoardGrid:
    n: int
    board_bbox: tuple[int, int, int, int]  # x, y, w, h (原圖座標)
    cell_boxes: list[list[tuple[int, int, int, int]]]  # [row][col] -> x, y, w, h


def detect_board_bbox(image: np.ndarray) -> tuple[int, int, int, int] | None:
    """
    找出畫面中最大的近似正方形輪廓，當作棋盤外框。
    找不到 (例如手機截圖裡棋盤本身沒有獨立外框，最大的方形輪廓其實是整張
    App 卡片、狀態列圖示等其他東西) 就回傳 None，交給呼叫端改用內容定位法。
    """
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 30, 100)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_area = 0
    image_area = h * w
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        area = cw * ch
        if area < image_area * 0.2:
            continue
        aspect = cw / ch if ch else 0
        if not (0.85 <= aspect <= 1.15):
            continue
        if area > best_area:
            best_area = area
            best = (x, y, cw, ch)

    return best


def _estimate_cell_size(positions: list[float], expected: float | None = None) -> tuple[float, float] | None:
    """
    從一堆座標點估計格子邊長，回傳 (cell_size, score)。
    做法：列出所有兩兩座標的差值，找出「最多其他差值都剛好是它的整數倍」的那個差值，
    這個差值就是格子邊長的基本單位 (相鄰兩格圖示剛好差 1 格、差 2 格...都會是它的倍數)。
    若有 expected (預期格子邊長，例如 圖片寬度/n)，優先在 expected 附近找，
    避免被畫面其他 UI 元素 (例如標題列圖示間距) 湊巧形成的規律訊號誤導。
    """
    diffs = sorted(
        {abs(a - b) for i, a in enumerate(positions) for b in positions[i + 1 :] if abs(a - b) > 20}
    )
    if not diffs:
        return None

    search_space = diffs
    if expected is not None:
        narrowed = [d for d in diffs if expected * 0.6 <= d <= expected * 1.4]
        if narrowed:
            search_space = narrowed

    best_d, best_score = None, -1
    for d in search_space:
        score = 0
        for other in diffs:
            ratio = other / d
            nearest = round(ratio)
            if nearest >= 1 and abs(ratio - nearest) < 0.08:
                score += 1
        if score > best_score or (score == best_score and (best_d is None or d < best_d)):
            best_score = score
            best_d = d
    return best_d, best_score


def _fit_lattice_origin(positions: list[float], cell_size: float) -> float:
    """已知格子邊長，估計網格原點 (格子中心對齊到哪個絕對座標)。"""
    ref = positions[0]
    aligned = []
    for p in positions:
        k = round((p - ref) / cell_size)
        aligned.append(p - k * cell_size)
    return sum(aligned) / len(aligned)


def _split_into_bands(sorted_values: list[float], gap: float) -> list[list[float]]:
    """依 y 座標把候選點切成好幾個「區塊」(標題列/棋盤/說明文字通常隔很開)。"""
    if not sorted_values:
        return []
    bands = [[sorted_values[0]]]
    for v in sorted_values[1:]:
        if v - bands[-1][-1] > gap:
            bands.append([])
        bands[-1].append(v)
    return bands


def _find_content_blobs(image: np.ndarray, aspect_range: tuple[float, float]) -> list[tuple[float, float]]:
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 30, 100)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    lo, hi = aspect_range
    centers = []
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        if cw < 15 or ch < 15:
            continue
        aspect = cw / ch if ch else 0
        if not (lo <= aspect <= hi):
            continue
        area_ratio = (cw * ch) / (w * h)
        if not (0.0003 <= area_ratio <= 0.02):
            continue
        centers.append((x + cw / 2, y + ch / 2))
    return centers


def detect_board_bbox_by_content(image: np.ndarray, n: int) -> tuple[int, int, int, int] | None:
    """
    當棋盤本身沒有明顯外框可偵測時 (例如手機 App 截圖，整張圖含狀態列、標題列、
    按鈕、說明文字，棋盤格線很淡、沒有獨立粗外框) 的備用做法：
    直接偵測格子內太陽/月亮圖示、=/× 符號這些內容的位置，反推整個棋盤的格子
    邊長與原點，而不是去找一個包住棋盤的外框輪廓。必須事先知道棋盤格數 n
    (無法從內容分佈可靠地推算出 n)。

    整張截圖裡標題列圖示、說明文字裡的項目符號等也會被抓成候選，所以：
      1. 先用「方形」濾條件 (太陽/月亮圖示接近正方形) 找候選點，依 y 座標切成
         幾個區塊 (區塊間 gap 很大，例如標題列跟棋盤之間、棋盤跟下方按鈕/
         說明文字之間都有明顯留白)。
      2. 用「預期格子邊長 = 圖片較短邊 / n」當作先驗，每個區塊分別估計格子
         邊長，挑最接近預期值的那個區塊當作棋盤本體。
      3. 棋盤第一列(或最後一列)可能剛好沒有太陽/月亮圖示 (只有扁長的 =/×
         符號、或整列空白)，導致上一步的原點少算了一整列。用這個區塊跟
         「前一個區塊 (標題列)」之間的空隙大小反推：這段空隙扣掉 UI 本身
         正常的留白後，還能再塞進幾個整格，那就是被漏算的列數。
    """
    h, w = image.shape[:2]
    icon_centers = _find_content_blobs(image, aspect_range=(0.7, 1.4))
    if len(icon_centers) < 4:
        return None

    expected_cell_size = min(w, h) / n
    # 要比「同一個棋盤內、沒有圖示的空列/空欄」造成的間隔大 (最多約 1 格)，
    # 但要比「棋盤跟標題列/說明文字之間」的留白間隔小，才能正確切開區塊。
    band_gap = expected_cell_size * 1.3

    ys_sorted = sorted(cy for _, cy in icon_centers)
    y_bands = _split_into_bands(ys_sorted, band_gap)

    best = None  # (closeness, band_index, cell_size, origin_x, origin_y)
    for band_idx, band in enumerate(y_bands):
        band_set = set(band)
        band_centers = [(cx, cy) for cx, cy in icon_centers if cy in band_set]
        if len(band_centers) < 4:
            continue

        tol = min(w, h) * 0.01
        x_groups = _cluster_positions(sorted(cx for cx, _ in band_centers), tol)
        y_groups = _cluster_positions(sorted(cy for _, cy in band_centers), tol)
        if len(x_groups) < 2 or len(y_groups) < 2:
            continue

        result = _estimate_cell_size(x_groups + y_groups, expected=expected_cell_size)
        if result is None:
            continue
        cell_size, _score = result
        # 離預期值太遠的直接跳過 (例如說明文字行距湊巧規律，但跟格子邊長差太多)
        if not (expected_cell_size * 0.7 <= cell_size <= expected_cell_size * 1.3):
            continue

        origin_x = _fit_lattice_origin(x_groups, cell_size)
        origin_y = _fit_lattice_origin(y_groups, cell_size)

        # 挑「格子邊長最接近預期值」的區塊，而不是訊號分數最高的：
        # 說明文字之類的區塊雜訊點多，分數容易虛高，但格子邊長通常明顯偏離預期。
        closeness = abs(cell_size - expected_cell_size)
        if best is None or closeness < best[0]:
            best = (closeness, band_idx, cell_size, origin_x, origin_y)

    if best is None:
        return None
    _, band_idx, cell_size, origin_x, origin_y = best

    prev_band_end = y_bands[band_idx - 1][-1] if band_idx > 0 else 0.0
    gap_above = min(y_bands[band_idx]) - prev_band_end
    extra_rows_above = max(0, int(gap_above // cell_size))
    origin_y -= extra_rows_above * cell_size

    bx = origin_x - cell_size / 2
    by = origin_y - cell_size / 2
    return round(bx), round(by), round(cell_size * n), round(cell_size * n)


def _cluster_positions(positions: list[float], tol: float) -> list[float]:
    if not positions:
        return []
    positions = sorted(positions)
    clusters = [[positions[0]]]
    for p in positions[1:]:
        if p - clusters[-1][-1] <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return [sum(c) / len(c) for c in clusters]


def detect_grid_line_count(board_roi: np.ndarray) -> int | None:
    """嘗試偵測棋盤內的格線數量，回傳 N (格數)。偵測失敗回傳 None。"""
    h, w = board_roi.shape[:2]
    gray = cv2.cvtColor(board_roi, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 20, 60)

    min_len = int(min(h, w) * 0.6)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180, threshold=min_len // 2,
        minLineLength=min_len, maxLineGap=10,
    )
    if lines is None:
        return None

    horiz_y, vert_x = [], []
    for line in lines.reshape(-1, 4):
        x1, y1, x2, y2 = line
        if abs(y1 - y2) < 3 and abs(x1 - x2) > min_len * 0.8:
            horiz_y.append((y1 + y2) / 2)
        elif abs(x1 - x2) < 3 and abs(y1 - y2) > min_len * 0.8:
            vert_x.append((x1 + x2) / 2)

    tol = min(h, w) * 0.02
    h_clusters = _cluster_positions(horiz_y, tol)
    v_clusters = _cluster_positions(vert_x, tol)

    n_from_h = len(h_clusters) - 1 if len(h_clusters) >= 2 else None
    n_from_v = len(v_clusters) - 1 if len(v_clusters) >= 2 else None

    candidates = [n for n in (n_from_h, n_from_v) if n and n > 1]
    if not candidates:
        return None
    # 兩個方向都偵測到且不一致時，取較常見/較小的偶數值比較安全
    if len(candidates) == 2 and candidates[0] != candidates[1]:
        return None
    return candidates[0]


def build_grid(image: np.ndarray, n_hint: int | None = None) -> BoardGrid:
    bbox = detect_board_bbox(image)

    if bbox is not None:
        x, y, w, h = bbox
        roi = image[y : y + h, x : x + w]
        n = detect_grid_line_count(roi)
        if n is None:
            if n_hint is None:
                raise ValueError("無法自動偵測棋盤格數，請手動指定棋盤格數 (例如 6)")
            n = n_hint
        elif n_hint is not None and n != n_hint:
            # 偵測結果與使用者指定不同時，以使用者指定為準，但發出提醒交由呼叫端處理
            n = n_hint
    else:
        # 找不到棋盤自己的外框 (常見於手機截圖：整張畫面含狀態列、標題列、
        # 按鈕、說明文字，棋盤格線很淡、沒有獨立粗外框)。
        # 改用「格內圖示/符號的位置分佈」反推棋盤範圍，但這個方法需要先知道 n。
        if n_hint is None:
            raise ValueError(
                "偵測不到棋盤外框，且未提供棋盤格數，無法用內容定位法反推棋盤範圍，"
                "請手動指定棋盤格數 (例如 6)"
            )
        content_bbox = detect_board_bbox_by_content(image, n_hint)
        if content_bbox is None:
            raise ValueError("偵測不到棋盤位置，請確認截圖有包含完整的棋盤區域")
        x, y, w, h = content_bbox
        n = n_hint

    cell_w = w / n
    cell_h = h / n
    cell_boxes = []
    for r in range(n):
        row_boxes = []
        for c in range(n):
            cx = x + round(c * cell_w)
            cy = y + round(r * cell_h)
            cw = round(cell_w)
            ch = round(cell_h)
            row_boxes.append((cx, cy, cw, ch))
        cell_boxes.append(row_boxes)

    return BoardGrid(n=n, board_bbox=(x, y, w, h), cell_boxes=cell_boxes)
