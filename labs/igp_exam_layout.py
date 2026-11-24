#!/usr/bin/env python3
"""IGP-Lab-Exam 画布标注布局计算 v2 —— 收进 2000x1000 场景。

拓扑上半区(y80-640) + 地址表底部两行(y700-965) + 任务栏右列(x1560)。
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gns3_label_layout import (
    STYLE, resolve, audit, text_size, icon_box, link_segment, iround)

NODES = {
    # Area 1 (左)               Area 0 (中)              Area 2 (右)
    "R3": (100, 130), "R4": (100, 430),  "R1": (600, 130), "R2": (600, 430),
    "SW2": (30, 280), "SW1": (330, 280), "SW0": (600, 280),
    "R5": (1300, 130), "R6": (1300, 430), "SW3": (1070, 280), "SW4": (1380, 280),
    # 外部 (底部)
    "SW5": (80, 540), "R7": (230, 580), "SW6": (1290, 540), "R8": (1130, 580),
}

LINKS = [
    ("R1", "SW0"), ("R2", "SW0"),
    ("R1", "SW1"), ("R3", "SW1"), ("R4", "SW1"),
    ("R3", "SW2"), ("R4", "SW2"),
    ("R2", "SW3"), ("R5", "SW3"), ("R6", "SW3"),
    ("R5", "SW4"), ("R6", "SW4"),
    ("R4", "SW5"), ("R7", "SW5"),
    ("R6", "SW6"), ("R8", "SW6"),
]

SEGMENTS = {f"{a}-{b}": link_segment(NODES, a, b) for a, b in LINKS}
OBSTACLES = [icon_box(xy) for xy in NODES.values()]


def cjk_size(text, font):
    lines = text.split("\n")
    w = max(iround(sum(1.0 if ord(c) > 0x2E80 else 0.8 for c in l) * font)
            for l in lines)
    return w, iround(font * STYLE["line_h"]) * len(lines)


# (name, x, y, w, h) — 服务端返回的权威尺寸
FIXED = [
    ("title", 736, 8, 528, 42),
    ("subtitle", 659, 56, 682, 23),
    ("cap-a1", 10, 88, 167, 31),
    ("cap-a0", 570, 88, 167, 31),
    ("cap-a2", 1040, 88, 167, 31),
    ("as7", 310, 590, 146, 27),
    ("as8", 960, 590, 146, 27),
    ("tbl-a1", 20, 700, 468, 75),
    ("tbl-a0", 510, 700, 354, 50),
    ("tbl-a2", 890, 700, 468, 75),
    ("tbl-ext", 20, 790, 375, 75),
    ("tbl-lo", 420, 790, 281, 50),
    ("tbl-note", 730, 790, 188, 100),
    ("pinglun", 950, 790, 292, 175),
    ("task-head", 1560, 60, 359, 31),
    ("task-a", 1560, 100, 292, 375),
    ("task-b", 1560, 485, 354, 425),
]

LABELS = [
    ("L-sw0", "10.0.12.0/24", 700, 302),
    ("L-sw1", "10.1.0.0/24", 310, 345),
    ("L-sw2", "10.1.34.0/24", 115, 302),
    ("L-sw3", "10.2.0.0/24", 940, 250),
    ("L-sw4", "10.2.56.0/24", 1240, 302),
    ("L-sw5", "172.16.47.0/24", 140, 660),
    ("L-sw6", "172.16.68.0/24", 1050, 660),
]


def main():
    from gns3_label_layout import Entity
    ents = []
    for eid, txt, ix, iy in LABELS:
        w, h = text_size(txt, 12)
        ents.append(Entity(eid, w, h, (ix, iy), priority=10, mode="slide-x"))
    placements = resolve(ents, OBSTACLES, SEGMENTS)

    fixed_boxes = [(n, (x, y, w, h)) for n, x, y, w, h in FIXED]
    wmap = {e.eid: (e.w, e.h) for e in ents}
    label_boxes = [(eid, (placements[eid].x, placements[eid].y, *wmap[eid]))
                   for eid, *_ in LABELS]

    print("== 链路标注 ==")
    for eid, txt, *_ in LABELS:
        p = placements[eid]
        flag = "  ⚠unresolved" if p.unresolved else ""
        print(f"{eid} {txt!r}: ({p.x:.0f},{p.y:.0f})  [{p.slot}]{flag}")

    # 越界检查 (2000x1000)
    print("\n== 越界检查 ==")
    bad = []
    for n, (x, y, w, h) in fixed_boxes + label_boxes:
        if x < 0 or y < 0 or x + w > 2000 or y + h > 1000:
            bad.append(f"{n}: ({x},{y},{w},{h})")
    for name, (x, y) in NODES.items():
        if x < 0 or y < 0 or x + 60 > 2000 or y + 60 > 1000:
            bad.append(f"node {name}: ({x},{y})")
    print("\n".join(bad) if bad else "全部在 2000x1000 内 ✓")

    viols = audit(fixed_boxes + label_boxes, OBSTACLES, SEGMENTS)
    print("\n== audit 违例 ==")
    print("\n".join(viols) if viols else "全部干净 ✓")


if __name__ == "__main__":
    main()
