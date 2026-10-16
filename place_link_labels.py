#!/usr/bin/env python3
"""vxlan-compute-test 标注布局 CLI —— 项目配置 + gns3_label_layout 引擎。

用法:
    python3 place_link_labels.py nodes.json [--pad 6] [--min-gap 200] [--current drawings.json]

输入(自动识别格式):
    nodes.json: {"nodes":[{"name","x","y"}, ...]} 或 {"Name":{"x","y"}}
    --current:  MCP drawing_list 原样 JSON, 用于与线上状态 diff, 只列需更新项

输出:
    stdout: 完整计划 JSON (shapes / title / tags / labels)
    stderr: 碰撞复核 + drawing_update 速查

工作流(每次现拉数据, 勿用缓存):
    ① MCP node_list(带 x,y) → nodes.json
    ② 本脚本 → 得到目标坐标 + 碰撞复核
    ③ MCP drawing_update 逐条执行(或先 --current 拿差异清单)
"""
import argparse
import json
import sys

from gns3_label_layout import (
    STYLE, Entity, resolve, audit, caption_candidates, iround,
    icon_box, link_segment, shape_box, load_nodes,
)

# ================= 项目配置: drawing_id ↔ 实体 =================
# 链路标注: drawing_id -> (文本, 端点A, 端点B, 宽, 高, 组)
# 组: diag=mesh斜线 / mh=mesh水平线 / ah=接入横线 / av=接入竖线
LABELS = {
    "7946e309-c736-4a76-9513-f4b9d4e27a32": ("21.1.12.0/24", "FRRDocker-21", "FRRDocker-22", 96, 19, "diag"),
    "9ca1e3fc-5082-4d6d-b830-5754f5b207c4": ("21.1.13.0/24", "FRRDocker-21", "FRRDocker-23", 96, 19, "diag"),
    "d53d26d5-e1a3-40b4-8781-e13ccb39bf58": ("21.1.24.0/24", "FRRDocker-22", "FRRDocker-24", 96, 19, "diag"),
    "bec94f82-02fa-422b-9922-287104c55be0": ("21.1.34.0/24", "FRRDocker-23", "FRRDocker-24", 96, 19, "diag"),
    "1e61b51f-3378-416b-b36d-3f6bc09768e9": ("21.1.14.0/24", "FRRDocker-21", "FRRDocker-24", 96, 19, "mh"),
    "bebe35f1-c600-4bc9-aba2-e189f6f7dd30": ("21.1.23.0/24", "FRRDocker-22", "FRRDocker-23", 96, 19, "mh"),
    "bd837e0b-9789-4d98-8b70-5db6218c9f05": ("21.1.1.0/24 · area 21", "Ubuntu-21", "FRRDocker-21", 168, 19, "ah"),
    "62dcbc3c-834a-41a7-9e35-494dbce3fdbc": ("21.1.4.0/24 · area 24", "Ubuntu-24", "FRRDocker-24", 168, 19, "ah"),
    "556cda54-ed0c-4a02-ad2e-a0fa3ace86e2": ("21.1.2.0/24\narea 22", "Ubuntu-22", "FRRDocker-22", 88, 38, "av"),
    "9c48db2a-d5f2-4fa8-92ce-a262e574e110": ("21.1.3.0/24\narea 23", "Ubuntu-23", "FRRDocker-23", 88, 38, "av"),
}

# 节点对形状: shape drawing_id -> (端点A, 端点B, 颜色)
SHAPES = {
    "cdcf60c6-629a-478d-8f22-4bb0bf326c30": ("Ubuntu-21", "FRRDocker-21", "#5AA9DD"),
    "09a5d3a0-a65d-45f2-8c59-92ddb717eba2": ("Ubuntu-22", "FRRDocker-22", "#7BC67E"),
    "fa9946d7-1a04-449b-8ecc-cf6bc627462a": ("Ubuntu-23", "FRRDocker-23", "#E8B85C"),
    "6a363a46-5e86-4f5c-bea1-102ddd7074db": ("Ubuntu-24", "FRRDocker-24", "#C792DF"),
}
SHAPE_TAGS = {  # 形状 drawing_id -> (标签 drawing_id, 标签宽, 标签高)
    "cdcf60c6-629a-478d-8f22-4bb0bf326c30": ("e35c1877-5a9c-4365-b024-197ce90daf9b", 288, 46),
    "09a5d3a0-a65d-45f2-8c59-92ddb717eba2": ("bf44ee4c-9e75-413d-ad80-cdad715fb21f", 240, 46),
    "fa9946d7-1a04-449b-8ecc-cf6bc627462a": ("4b665758-f9fb-4ad1-b6d9-665e93672457", 240, 46),
    "6a363a46-5e86-4f5c-bea1-102ddd7074db": ("0bf469b7-8e0d-4979-ab5e-f1629ce883da", 240, 46),
}
TITLE = ("d51ebfc4-0cad-424b-9995-d09385e0ae40", -208, -430, 852, 54)

# 摆放风格(用户手调反推的经验公式: 复现既定审美; 实际净空由消解层保证)
GROUP_OFFSET = {"mh": (17.5, 5.5), "ah": (30.0, 5.5), "av": (80.0, 17.5)}
FREE_MODE = {"diag": "slide-x", "mh": "slide-x", "ah": "slide-x", "av": "slide-y"}
MARGIN = 45        # 形状框对称外扩
BAND_DY = 5.5      # 斜线标注中部带: FRR 质心 y + 5.5
CAPTION_DX = 8     # caption 左缘: 形状左 + 8
CAPTION_DY = 8     # caption 底边距形状顶 8

SHAPE_SVG = ('<svg height="{h}" width="{w}"><rect fill="{c}" fill-opacity="0.12" '
             'stroke="{c}" stroke-width="2" height="{h}" width="{w}" rx="0" ry="0"/></svg>')


def diag_crossing_x(a, b, band_y):
    """斜线与水平带 y=band_y 交点的 x。"""
    ax, ay = a
    bx, by = b
    dy = by - ay
    if dy == 0:
        raise ValueError("horizontal link in diag group")
    t = (band_y - ay) / dy
    return ax + (bx - ax) * t


def build_plan(nodes, min_gap, pad):
    """由节点坐标构建: 形状 / 障碍 / 线段 / 实体 → 解算 → 复核。"""
    # ---------- 形状 / 障碍 / 线段 ----------
    shapes = {sid: shape_box(nodes, a, b, MARGIN) for sid, (a, b, _c) in SHAPES.items()}
    obstacles = [icon_box(nodes[n]) for n in nodes]
    segments = {}
    for _did, (_t, a, b, *_rest) in LABELS.items():
        key = "--".join(sorted((a, b)))
        if key not in segments:
            segments[key] = link_segment(nodes, a, b)

    # ---------- 实体: 标题(fixed) / 区域标签(candidates) / 链路标注(slide) ----------
    entities = [Entity(TITLE[0], TITLE[3], TITLE[4], ideal=(TITLE[1], TITLE[2]),
                       priority=100, mode="fixed")]

    for sid, (tid, tw, th) in SHAPE_TAGS.items():
        rx, ry, rw, rh = shapes[sid]
        cands = caption_candidates(rx, ry, rw, rh, tw, th, dx=CAPTION_DX, dy=CAPTION_DY)
        entities.append(Entity(tid, tw, th, ideal=cands[0][:2],
                               priority=10, mode="candidates", candidates=cands))

    frr_ys = [nodes[n][1] for n in nodes if n.startswith("FRR")]
    band_y = sum(frr_ys) / len(frr_ys) + BAND_DY
    diag = sorted([(did, diag_crossing_x(nodes[LABELS[did][1]], nodes[LABELS[did][2]], band_y))
                   for did in LABELS if LABELS[did][5] == "diag"], key=lambda t: t[1])
    diag_x, prev = {}, None
    for did, cx in diag:  # 左起 min-gap 推挤防叠
        cx = max(cx, prev + min_gap) if prev is not None else cx
        diag_x[did] = cx
        prev = cx

    for did, (_t, a, b, w, h, g) in LABELS.items():
        if g == "diag":
            cx, cy = diag_x[did], band_y
        else:
            ox, oy = GROUP_OFFSET[g]
            cx = (nodes[a][0] + nodes[b][0]) / 2.0 + ox
            cy = (nodes[a][1] + nodes[b][1]) / 2.0 + oy
        entities.append(Entity(did, w, h, ideal=(iround(cx - w / 2.0), iround(cy - h / 2.0)),
                               priority=5, mode=FREE_MODE[g]))

    # ---------- 解算 + 独立复核 ----------
    placements = resolve(entities, obstacles, segments, pad=pad)
    text_boxes = [(e.eid, (placements[e.eid].x, placements[e.eid].y, e.w, e.h)) for e in entities]
    viols = audit(text_boxes, obstacles, segments, pad=pad)

    # ---------- 计划(目标坐标) ----------
    plan = {"shapes": [], "title": None, "tags": [], "labels": []}
    for sid, (_a, _b, c) in SHAPES.items():
        x, y, w, h = shapes[sid]
        plan["shapes"].append({"drawing_id": sid, "x": x, "y": y, "w": w, "h": h,
                               "svg": SHAPE_SVG.format(h=h, w=w, c=c)})
    plan["title"] = {"drawing_id": TITLE[0], "x": TITLE[1], "y": TITLE[2]}
    for sid, (tid, _tw, _th) in SHAPE_TAGS.items():
        p = placements[tid]
        plan["tags"].append({"drawing_id": tid, "x": iround(p.x), "y": iround(p.y), "slot": p.slot})
    for did, (text, *_rest) in LABELS.items():
        p = placements[did]
        plan["labels"].append({"drawing_id": did, "text": text.replace("\n", "|"),
                               "x": iround(p.x), "y": iround(p.y), "slot": p.slot})
    return plan, viols


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("nodes_json")
    ap.add_argument("--pad", type=float, default=STYLE["pad"])
    ap.add_argument("--min-gap", type=float, default=200.0)
    ap.add_argument("--current", help="MCP drawing_list JSON: 与线上 diff, 只列需更新项")
    args = ap.parse_args()

    nodes = load_nodes(args.nodes_json)
    need = ({n for pair in SHAPES.values() for n in pair[:2]}
            | {n for _, (_t, a, b, *_r) in LABELS.items() for n in (a, b)})
    missing = need - set(nodes)
    if missing:
        sys.exit(f"missing node coords: {sorted(missing)}")

    plan, viols = build_plan(nodes, args.min_gap, args.pad)

    print(f"=== 碰撞复核 (pad={args.pad:g}) ===", file=sys.stderr)
    for v in viols:
        print(f"  !! {v}", file=sys.stderr)
    print(f"  违例数: {len(viols)}" + ("  (全净)" if not viols else "  — 需人工处理"), file=sys.stderr)

    items = []
    for s in plan["shapes"]:
        items.append(("[shape]      ", s["drawing_id"], s["x"], s["y"], f'{s["w"]}x{s["h"]}', s))
    items.append(("[title]      ", plan["title"]["drawing_id"], plan["title"]["x"], plan["title"]["y"], "", plan["title"]))
    for t in plan["tags"]:
        items.append((f'[tag {t["slot"]}]', t["drawing_id"], t["x"], t["y"], "", t))
    for lb in plan["labels"]:
        items.append((f'[label {lb["slot"]}]', lb["drawing_id"], lb["x"], lb["y"], lb["text"], lb))

    if args.current:
        cur = {d["drawing_id"]: d for d in json.load(open(args.current))["drawings"]}
        print("\n# ---- 与线上 diff (x/y = 左上角) ----", file=sys.stderr)
        n_need = 0
        for tag, did, x, y, extra, obj in items:
            d = cur.get(did)
            dirty = (d is None or iround(d["x"]) != x or iround(d["y"]) != y
                     or ("svg" in obj and d.get("svg") != obj["svg"]))
            if dirty:
                n_need += 1
                old = f'({iround(d["x"])},{iround(d["y"])})' if d else "(缺失)"
                print(f'# !! {tag:<22} {did[:8]}  {old} -> ({x},{y}) {extra}', file=sys.stderr)
        print(f'# 需更新 {n_need} 项 / 共 {len(items)} 项', file=sys.stderr)
    else:
        print("\n# ---- drawing_update 速查 (x/y = 左上角) ----", file=sys.stderr)
        for tag, did, x, y, extra, _obj in items:
            print(f'# {tag:<22} {did[:8]} -> x={x:<5} y={y:<5} {extra}', file=sys.stderr)

    print(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
