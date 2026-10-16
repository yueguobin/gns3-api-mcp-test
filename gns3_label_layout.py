#!/usr/bin/env python3
"""gns3_label_layout —— GNS3 Web UI 拓扑标注布局引擎(单文件库, 零依赖)。

把"给拓扑画布摆标注"抽象为: 几何原语 + 优先级贪心消解引擎 + GNS3 适配。
与具体项目解耦——实体映射与风格偏移全部由调用方(CLI)配置。

== 坐标系与锚点(实测定案, 勿再猜) ==
- 画布 = 左手笛卡尔系(x 右正, y 下正, 原点=场景中心)
- 节点 (x, y) = 图标**左上角**; 图标 60×60 → 图标体 (x,y)~(x+60,y+60),
  图标中心 = (x+30, y+30)
- drawing (x, y) = **左上角**
- link 几何 = 两端【图标中心】的直线段
- text 度量 = 宽: 最长行字符数×font_size×0.8; 高: 行数×round(font_size×1.9)

== 碰撞模型 ==
- 框×框: AABB, 间隙 < pad 即碰撞
- 框×线段: 矩形(含高度)与线段的最近距离 < pad 即碰撞(相交=0);
  斜线的关键接触点是**底边角**——左上角净空并不代表不碰, 判定必须用
  整个矩形(四角+边)对线段取最小距离

== 消解引擎(贪心最小位移, 确定性可复现) ==
- Entity.mode: fixed | candidates | slide-x | slide-y
- 按 priority 降序逐个摆放; 每个实体避开: 障碍框 + 线段 + 已放实体
- candidates: 候选槽位按序扫描, 首个全净即选; 全脏则取碰撞最少者并标记 fallback
- slide: 沿保语义轴双向扫描(0, +step, -step, +2step, ...), 首个全净即选;
  上限内无解 → unresolved 标记(不静默)
- 布置完成后建议调用 audit() 独立复核(全对全距离检查)

== 扩展点 ==
- link 含折点/曲线 → 线段原语替换为折线最小距离, 引擎与 mode 不变
- 新实体类型(图标/自由注释) → 增加 mode 分支
- 换渲染平台(锚点语义不同) → 只改 §4 适配函数
"""

import json
from dataclasses import dataclass, field
from math import floor, hypot

STYLE = {
    "icon": 60,           # 节点图标边长(px)
    "pad": 6.0,           # 最小间隙: 框-框 / 框-线段
    "slide_step": 4.0,    # 自由轴扫描步长
    "slide_max": 300.0,   # 自由轴扫描上限
    "char_w": 0.8,        # 字宽系数: w = 字符数 × font_size × char_w
    "line_h": 1.9,        # 行高系数: lh = round(font_size × line_h)
}


def iround(x):
    """round-half-up, 与既有画布坐标一致(勿用 banker's rounding)。"""
    return int(floor(x + 0.5))


# ================= §1 几何原语 =================

def aabb_hit(a, b, pad):
    """AABB 碰撞: 两框间隙 < pad 视为碰撞。a/b=(x,y,w,h)。"""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ox = min(ax + aw, bx + bw) - max(ax, bx) + pad
    oy = min(ay + ah, by + bh) - max(ay, by) + pad
    return ox > 0 and oy > 0


def seg_intersects_box(p1, p2, box):
    """线段与 AABB 是否相交(Liang-Barsky slab)。"""
    x, y, w, h = box
    t0, t1 = 0.0, 1.0
    for p, d, mn, mx in ((p1[0], p2[0] - p1[0], x, x + w), (p1[1], p2[1] - p1[1], y, y + h)):
        if abs(d) < 1e-12:
            if p < mn or p > mx:
                return False
        else:
            ta, tb = (mn - p) / d, (mx - p) / d
            if ta > tb:
                ta, tb = tb, ta
            t0, t1 = max(t0, ta), min(t1, tb)
            if t0 > t1:
                return False
    return True


def pt_seg(px, py, p1, p2):
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return hypot(px - p1[0], py - p1[1])
    t = max(0.0, min(1.0, ((px - p1[0]) * dx + (py - p1[1]) * dy) / L2))
    return hypot(px - (p1[0] + t * dx), py - (p1[1] + t * dy))


def pt_box(px, py, box):
    x, y, w, h = box
    return hypot(max(x - px, 0, px - (x + w)), max(y - py, 0, py - (y + h)))


def seg_box_dist(p1, p2, box):
    """线段到 AABB 的最小距离(相交=0)。凸集对凸集, 取角点/端点的最小即可。"""
    if seg_intersects_box(p1, p2, box):
        return 0.0
    x, y, w, h = box
    return min(pt_box(p1[0], p1[1], box), pt_box(p2[0], p2[1], box),
               pt_seg(x, y, p1, p2), pt_seg(x + w, y, p1, p2),
               pt_seg(x, y + h, p1, p2), pt_seg(x + w, y + h, p1, p2))


def box_clean(box, box_obs, segs, pad):
    """框与全部框障碍无碰撞, 且与全部线段距离 >= pad。segs: {name: (p1,p2)}。"""
    if any(aabb_hit(box, o, pad) for o in box_obs):
        return False
    return all(seg_box_dist(p1, p2, box) >= pad for p1, p2 in segs.values())


def slide_offsets(max_slide, step):
    """0, +step, -step, +2step, -2step, ... 最小位移优先, 同距取正方向。"""
    offs = [0.0]
    k = step
    while k <= max_slide:
        offs.extend([k, -k])
        k += step
    return offs


# ================= §2 消解引擎 =================

@dataclass
class Entity:
    """一个待摆放标注。

    mode:
      fixed       — 固定不检(自身作为障碍参与后续); 用于标题等
      candidates  — 候选槽位按序扫描(如区域 caption: 上方±平移 → 四内角)
      slide-x/-y  — 沿 x/y 双向滑动(保语义轴: 斜线/水平标注→x, 竖直接入→y)
    """
    eid: str
    w: float
    h: float
    ideal: tuple                       # 理想左上角 (x, y)
    priority: int = 0                  # 大者先摆放(先到先占, 即更高优先级)
    mode: str = "slide-x"
    candidates: list = field(default_factory=list)   # [(x, y, slot_name), ...]
    step: float = None                 # None → STYLE
    max_slide: float = None            # None → STYLE


@dataclass
class Placement:
    eid: str
    x: float
    y: float
    slot: str = ""                     # 决策说明(槽位名 / slide ±N / fixed)
    moved: tuple = (0.0, 0.0)          # 相对 ideal 的位移
    unresolved: bool = False           # slide 扫描无解
    fallback: bool = False             # candidates 全脏, 退化为最少碰撞槽位


def resolve(entities, obstacle_boxes, segments, pad=None):
    """优先级贪心解算。返回 {eid: Placement}。

    obstacle_boxes: [(x,y,w,h)] 固定障碍(节点图标等; 不含线段)
    segments:       {name: (p1, p2)} link 线段
    """
    pad = STYLE["pad"] if pad is None else pad
    placed = []
    out = {}
    for ent in sorted(entities, key=lambda e: -e.priority):
        obs = obstacle_boxes + placed
        step = ent.step or STYLE["slide_step"]
        max_slide = ent.max_slide or STYLE["slide_max"]
        pos, slot, unres, fb = ent.ideal, "fixed", False, False

        if ent.mode == "candidates":
            pos = None
            for cx, cy, s in ent.candidates:
                if box_clean((cx, cy, ent.w, ent.h), obs, segments, pad):
                    pos, slot = (cx, cy), s
                    break
            if pos is None:  # 兜底: 碰撞数最少的候选, 显式标记
                def n_hits(c):
                    box = (c[0], c[1], ent.w, ent.h)
                    n = sum(1 for o in obs if aabb_hit(box, o, pad))
                    n += sum(1 for p1, p2 in segments.values() if seg_box_dist(p1, p2, box) < pad)
                    return n
                cx, cy, s = min(ent.candidates, key=n_hits)
                pos, slot, fb = (cx, cy), s + "+fallback", True

        elif ent.mode in ("slide-x", "slide-y"):
            axis = ent.mode[-1]
            pos = None
            for off in slide_offsets(max_slide, step):
                nx = ent.ideal[0] + (off if axis == "x" else 0)
                ny = ent.ideal[1] + (off if axis == "y" else 0)
                if box_clean((nx, ny, ent.w, ent.h), obs, segments, pad):
                    pos, slot = (nx, ny), f"slide {off:+g}" if off else "slide 0"
                    break
            if pos is None:
                pos, slot, unres = ent.ideal, "slide 无解", True

        out[ent.eid] = Placement(ent.eid, pos[0], pos[1], slot,
                                 (pos[0] - ent.ideal[0], pos[1] - ent.ideal[1]), unres, fb)
        placed.append((pos[0], pos[1], ent.w, ent.h))
    return out


def audit(text_boxes, obstacle_boxes, segments, pad=None):
    """独立复核: 全对全检查, 返回违例清单(空列表=全净)。

    text_boxes: [(name, (x,y,w,h))] — 所有文字实体(含标题)
    """
    pad = STYLE["pad"] if pad is None else pad
    viols = []
    for i, (n1, b1) in enumerate(text_boxes):
        for n2, b2 in text_boxes[i + 1:]:
            if aabb_hit(b1, b2, pad):
                viols.append(f"{n1} × {n2}")
        for k, b2 in enumerate(obstacle_boxes):
            if aabb_hit(b1, b2, pad):
                viols.append(f"{n1} × fixed#{k}")
        for sn, (p1, p2) in segments.items():
            d = seg_box_dist(p1, p2, b1)
            if d < pad:
                viols.append(f"{n1} × link {sn}  d={d:.1f}")
    return viols


# ================= §3 风格工具 =================

def caption_candidates(rx, ry, rw, rh, tw, th, dx=8, dy=8, step=8, near=96, far=240):
    """区域 caption 候选槽位(优先级序):
    上方/下方 (±近程水平平移) → 四内角 → 上方/下方 (±远程平移)。"""
    ds = [0]
    k = step
    while k <= far:
        ds.extend([k, -k])
        k += step
    cands = []
    for d in [v for v in ds if abs(v) <= near]:
        cands.append((rx + dx + d, ry - th - dy, "caption-above" + (f"{d:+d}px" if d else "")))
    for d in [v for v in ds if abs(v) <= near]:
        cands.append((rx + dx + d, ry + rh + dy, "caption-below" + (f"{d:+d}px" if d else "")))
    cands += [
        (rx + dx, ry + dy, "in-TL"),
        (rx + rw - tw - dx, ry + dy, "in-TR"),
        (rx + dx, ry + rh - th - dy, "in-BL"),
        (rx + rw - tw - dx, ry + rh - th - dy, "in-BR"),
    ]
    for d in [v for v in ds if abs(v) > near]:
        cands.append((rx + dx + d, ry - th - dy, f"caption-above{d:+d}px"))
    for d in [v for v in ds if abs(v) > near]:
        cands.append((rx + dx + d, ry + rh + dy, f"caption-below{d:+d}px"))
    return cands


# ================= §4 GNS3 适配 =================

def text_size(text, font_size, style=None):
    """按实测公式返回 (宽, 高)。"""
    s = style or STYLE
    lines = text.split("\n")
    w = iround(max(len(l) for l in lines) * font_size * s["char_w"])
    return w, iround(font_size * s["line_h"]) * len(lines)


def icon_box(node_xy, style=None):
    """节点图标体 AABB。节点 (x,y)=图标左上角。"""
    ic = (style or STYLE)["icon"]
    return (node_xy[0], node_xy[1], ic, ic)


def node_center(node_xy, style=None):
    ic = (style or STYLE)["icon"]
    return (node_xy[0] + ic / 2.0, node_xy[1] + ic / 2.0)


def link_segment(nodes, a, b, style=None):
    """link 线段 = 两端图标中心连线。nodes: {name: (x,y)}。"""
    return (node_center(nodes[a], style), node_center(nodes[b], style))


def shape_box(nodes, a, b, margin, style=None):
    """节点对形状框: 两图标体并集四周对称外扩 margin → 中心=节点组中心。"""
    ic = (style or STYLE)["icon"]
    x0 = min(nodes[a][0], nodes[b][0]) - margin
    y0 = min(nodes[a][1], nodes[b][1]) - margin
    x1 = max(nodes[a][0], nodes[b][0]) + ic + margin
    y1 = max(nodes[a][1], nodes[b][1]) + ic + margin
    return (x0, y0, x1 - x0, y1 - y0)


def load_nodes(src):
    """读取节点坐标, 接受: {"nodes":[{name,x,y}..]} / {"Name":{"x","y"}} / [{name,x,y}..]。"""
    data = json.load(open(src)) if isinstance(src, str) else src
    if isinstance(data, dict) and "nodes" in data:
        return {n["name"]: (n["x"], n["y"]) for n in data["nodes"]}
    if isinstance(data, dict):
        return {k: (v["x"], v["y"]) for k, v in data.items()}
    if isinstance(data, list):
        return {n["name"]: (n["x"], n["y"]) for n in data}
    raise ValueError("无法识别的 nodes 格式")
