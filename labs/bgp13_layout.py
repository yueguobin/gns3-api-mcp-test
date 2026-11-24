#!/usr/bin/env python3
"""BGP-Bestpath-13Rules-FRR 画布标注布局计算。

拓扑 9 节点/13 链, 画布 2000x1200。产出:
  - 3 个 AS 区域矩形 + caption
  - 信息块(左上) / 五路径表(左下) — fixed
  - 5 个角色标签 / 26 个链路两端地址标注 — 引擎消解
输出 MCP drawing_create_* 的目标坐标清单 + audit 复核。
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gns3_label_layout import (
    STYLE, Entity, resolve, audit, text_size, icon_box, node_center, iround)

NODES = {
    "R1": (820, 780), "R2": (330, 620), "R3": (820, 140), "R4": (1280, 140),
    "R5": (1050, 380), "R6": (1350, 620), "R7": (1620, 560),
    "H1": (820, 930), "H2": (480, 300),
}

# (a, b, addr_a, addr_b, kind)  kind: ebgp/ibgp/int/host
LINKS = [
    ("R3", "R1", "10.0.13.3",     "10.0.13.1",     "ebgp"),
    ("R4", "R1", "10.0.14.4",     "10.0.14.1",     "ebgp"),
    ("R5", "R1", "10.0.15.5",     "10.0.15.1",     "ebgp"),
    ("R2", "R1", "10.0.12.2",     "10.0.12.1",     "int"),
    ("R6", "R1", "10.0.16.6",     "10.0.16.1",     "int"),
    ("R3", "R2", "10.0.23.3",     "10.0.23.2",     "ebgp"),
    ("R4", "R6", "10.0.64.4",     "10.0.64.6",     "ebgp"),
    ("R4", "R3", "10.0.34.4",     "10.0.34.3",     "ibgp"),
    ("R5", "R3", "10.0.35.5",     "10.0.35.3",     "ebgp"),
    ("R2", "R6", "10.0.26.2",     "10.0.26.6",     "int"),
    ("R7", "R6", "10.0.67.7",     "10.0.67.6",     "int"),
    ("H1", "R1", "10.0.101.2",    "10.0.101.1",    "host"),
    ("H2", "R3", "100.100.100.2", "100.100.100.3", "host"),
]

COLORS = {"ebgp": "#B00000", "ibgp": "#B36B00", "int": "#0055AA", "host": "#555555"}

# AS 区域矩形: name -> (x, y, w, h, stroke)
RECTS = {
    "as200": (780, 100, 600, 140, "#B00000"),
    "as300": (1000, 330, 160, 160, "#B00000"),
    "as100": (290, 520, 1510, 510, "#0055AA"),
}

FIXED_TEXTS = [  # (eid, x, y, text, font, color, bold)
    ("info", 40, 25,
     "BGP-Bestpath-13Rules-FRR\n"
     "BGP 13 条选路原则实验场 · FRRDocker · 2026-11-21\n"
     "测试前缀 100.100.100.0/24 = H2 网段, R3 network 起源\n"
     "R1 五路径: P1 eBGP←R3 · P2 eBGP←R4 · P3 eBGP←R5\n"
     "P4 iBGP←R2 · P5 iBGP←R6  (P3 AS_PATH = 300 200)\n"
     "互联 10.0.XY.0/24 · Loopback/RID: R1..R7 = 1.1.1.1..7.7.7.7\n"
     "RR 阶段前缀 100.100.200.0/24 (R7) · 规则 12/13 用\n"
     "标注: 红=eBGP 橙=AS200 iBGP 蓝=AS100 内部(OSPF+iBGP) 灰=主机\n"
     "快照 baseline-bgp13-clean · 实验菜单见仓库 方案文档", 10, "#000000", True),
    ("cap-as200", 786, 106, "AS 200 · 源侧 (R3 network 起源 · R3–R4 iBGP)", 10, "#B00000", False),
    ("cap-as300", 1068, 338, "AS 300 转接", 10, "#B00000", False),
    ("cap-as100", 560, 526, "AS 100 · OSPF area 0 · iBGP", 10, "#0055AA", False),
    ("paths", 40, 1070,
     "P1 eBGP R1←R3  AS_PATH: 200\n"
     "P2 eBGP R1←R4  AS_PATH: 200\n"
     "P3 eBGP R1←R5  AS_PATH: 300 200\n"
     "P4 iBGP R1←R2  AS_PATH: 200  (NH 2.2.2.2)\n"
     "P5 iBGP R1←R6  AS_PATH: 200  (NH 6.6.6.6)", 10, "#333333", False),
]

ROLE_TAGS = [  # (eid, text, ideal_x, ideal_y, color) — slide-x 消解
    ("tag-r1", "裁决点 judge · 同前缀五路径比较", 888, 846, "#0055AA"),
    ("tag-r3", "源A · network 起源", 890, 142, "#B00000"),
    ("tag-r4", "源B · 经 R3 iBGP 转发", 1350, 142, "#B00000"),
    ("tag-r7", "RR 客户端 (规则12/13)", 1620, 632, "#0055AA"),
]

# 逐链两端法线侧覆盖: 默认 (a:+1, b:-1)
SIDE_OVERRIDE = {("R5", "R1"): (-1, +1), ("R4", "R1"): (+1, +1), ("H1", "R1"): (+1, +1)}

# 端标注钉死坐标(引擎死角的人工定案): R5 东侧净空位
FIXED_PIN = {"L-R5R1-R5": (1166, 396)}

FONT_ADDR = 10
DIST, PERP = 72.0, 24.0  # 端标注理想位置: 沿线距端中心 72px, 垂直偏移 24px(两端异侧)


def cjk_size(text, font):
    lines = text.split("\n")
    w = max(iround(sum(1.0 if ord(c) > 0x2E80 else 0.8 for c in l) * font)
            for l in lines)
    return w, iround(font * STYLE["line_h"]) * len(lines)


def unit(dx, dy):
    L = (dx * dx + dy * dy) ** 0.5
    return dx / L, dy / L


def main():
    # ---- 障碍与线段 ----
    obstacles = [icon_box(xy) for xy in NODES.values()]
    segments = {}
    for a, b, *_ in LINKS:
        segments[f"{a}-{b}"] = (node_center(NODES[a]), node_center(NODES[b]))
    for name, (rx, ry, rw, rh, _c) in RECTS.items():  # 矩形边也进避让模型
        segments[f"{name}-top"] = ((rx, ry), (rx + rw, ry))
        segments[f"{name}-bot"] = ((rx, ry + rh), (rx + rw, ry + rh))
        segments[f"{name}-l"] = ((rx, ry), (rx, ry + rh))
        segments[f"{name}-r"] = ((rx + rw, ry), (rx + rw, ry + rh))

    fixed_boxes = []
    for eid, x, y, text, font, _c, _b in FIXED_TEXTS:
        w, h = cjk_size(text, font)
        fixed_boxes.append((eid, (x, y, w, h)))
    obstacles += [b for _n, b in fixed_boxes]

    # ---- 实体: 角色标签 + 链路两端地址标注 ----
    ents = []
    for eid, text, ix, iy, color in ROLE_TAGS:
        w, h = cjk_size(text, 10)
        ents.append(Entity(eid, w, h, (ix, iy), priority=20, mode="slide-x"))

    end_labels = []  # (eid, text, color) 与坐标由消解决定
    for a, b, addr_a, addr_b, kind in LINKS:
        ca, cb = node_center(NODES[a]), node_center(NODES[b])
        w, h = text_size(addr_a, FONT_ADDR)
        sides = SIDE_OVERRIDE.get((a, b), (+1, -1))
        # 两端理想位置: 各自沿"指向对端"方向退 DIST, 再沿该方向法线偏 perp_off (两端异侧)
        for end, (c, addr, sign, dirx, diry) in (
                (a, (ca, addr_a, sides[0],
                     *unit(cb[0] - ca[0], cb[1] - ca[1]))),
                (b, (cb, addr_b, sides[1],
                     *unit(ca[0] - cb[0], ca[1] - cb[1])))):
            px, py = -diry, dirx  # 该端方向向量的法线
            # 法线偏移须让整个框避开自身链路线: 框沿法线方向的半_extent + 余量
            perp_off = max(PERP, (w / 2.0) * abs(diry) + (h / 2.0) * abs(dirx) + STYLE["pad"] + 2)
            ex = c[0] + dirx * DIST + px * perp_off * sign
            ey = c[1] + diry * DIST + py * perp_off * sign
            eid = f"L-{a}{b}-{end}"
            if eid in FIXED_PIN:
                ents.append(Entity(eid, w, h, FIXED_PIN[eid], priority=30, mode="fixed"))
            else:
                mode = "slide-x" if abs(dirx) >= abs(diry) else "slide-y"
                ents.append(Entity(eid, w, h, (iround(ex - w / 2), iround(ey - h / 2)),
                                   priority=10, mode=mode))
            end_labels.append((eid, addr, COLORS[kind]))

    placements = resolve(ents, obstacles, segments)

    # ---- 输出 ----
    plan = {"rects": [], "texts": []}
    for name, (rx, ry, rw, rh, c) in RECTS.items():
        plan["rects"].append({"name": name, "x": rx, "y": ry, "w": rw, "h": rh, "stroke": c})
    for eid, x, y, text, font, color, bold in FIXED_TEXTS:
        plan["texts"].append({"eid": eid, "x": x, "y": y, "text": text,
                              "font": font, "color": color, "bold": bold})
    for eid, text, ix, iy, color in ROLE_TAGS:
        p = placements[eid]
        plan["texts"].append({"eid": eid, "x": iround(p.x), "y": iround(p.y), "text": text,
                              "font": 10, "color": color, "bold": True,
                              "slot": p.slot, "moved": [iround(p.moved[0]), iround(p.moved[1])],
                              "unresolved": p.unresolved})
    for eid, text, color in end_labels:
        p = placements[eid]
        plan["texts"].append({"eid": eid, "x": iround(p.x), "y": iround(p.y), "text": text,
                              "font": FONT_ADDR, "color": color, "bold": False,
                              "slot": p.slot, "moved": [iround(p.moved[0]), iround(p.moved[1])],
                              "unresolved": p.unresolved})

    # ---- 复核 ----
    ent_boxes = [(e.eid, (placements[e.eid].x, placements[e.eid].y, e.w, e.h)) for e in ents]
    icon_only = [icon_box(xy) for xy in NODES.values()]
    viols = audit(fixed_boxes + ent_boxes, icon_only, segments)
    unresolved = [t["eid"] for t in plan["texts"] if t.get("unresolved")]

    print(json.dumps(plan, ensure_ascii=False, indent=1))
    print(f"\n== audit 违例 ({len(viols)}) ==", file=sys.stderr)
    for v in viols:
        print(f"  {v}", file=sys.stderr)
    print(f"== unresolved: {unresolved or '无'} ==", file=sys.stderr)
    oob = [t["eid"] for t in plan["texts"]
           if t["x"] < 0 or t["y"] < 0 or t["x"] > 2000 or t["y"] > 1200]
    print(f"== 越界(2000x1200): {oob or '无'} ==", file=sys.stderr)
    moved = [(t['eid'], t['moved'], t['slot']) for t in plan['texts']
             if t.get('moved') and (t['moved'][0] or t['moved'][1])]
    print(f"== 发生滑移的标注 {len(moved)} 个 ==", file=sys.stderr)
    for m in moved:
        print(f"  {m[0]} moved={m[1]} [{m[2]}]", file=sys.stderr)


if __name__ == "__main__":
    main()
