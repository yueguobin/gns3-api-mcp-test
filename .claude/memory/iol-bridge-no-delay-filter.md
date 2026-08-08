---
name: iol-bridge-no-delay-filter
description: GNS3 link packet filter（delay/corrupt/packet_loss 等）在 IOL bridge 上不支持，只能用在 dynamips/qemu 侧链路
metadata: 
  node_type: memory
  type: reference
  originSessionId: 877e239e-bcda-407c-9b1d-75f6325c3a8f
  modified: 2026-07-26T03:33:27.142Z
---

GNS3 给 link 加 packet filter（`link_update` 的 `filters`：delay、corrupt、packet_loss、frequency_drop 等）时，若链路涉及 **IOL bridge（IOU/IOL 节点）**，uBridge 报错：`delay filter is not supported on IOL bridges`（HTTP 409）。

**实测（mark-test 项目）：**
- IOU3↔Switch1 链路（IOU3 是 IOL）加 `delay [100,30]` → 409 失败。
- R3↔Switch1 链路（R3 是 dynamips）加同样 filter → 成功；实测 Ubuntu-1 ping R3 的 RTT 从 ~1ms 升到 ~195ms（100ms×2 往返），mdev ~27ms（jitter 30），符合预期。

**结论：** delay/corrupt 这类需包级处理的 filter 只在非-IOL bridge 上可用。涉及 IOU 节点的链路做不了 delay/corrupt/packet_loss 模拟，要改走 dynamips 或 qemu 侧的链路。

**附带（delay 模型本质）：** GNS3 的 delay filter 是"固定延迟+随机抖动"模型，不模拟带宽瓶颈/队列，所以 `ping -f` flood 不会造成排队丢包，仅因对端 CPU 处理带来小幅 RTT/抖动上升（实测 flood 下 RTT 195→213ms、mdev 27→31、0 丢包）。要观察拥塞效应应改用 `packet_loss` filter 或带宽限制场景。

参见 [[gns3-ws-console-usage]]、[[prefer-mcp-tool-desc-over-stale-memory]]。
