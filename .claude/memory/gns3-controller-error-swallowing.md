---
name: gns3-controller-error-swallowing
description: GNS3 controller 代理层吞掉底层4xx错误（如405），返回204成功伪装
metadata:
  type: reference
---

## GNS3 Controller 错误吞噬问题

### 现象
`node_suspend` 对 VPCS 和 IOU 节点类型返回 405 Method Not Allowed，但 GNS3 controller 代理层将此错误转换为 204 成功响应返回，导致客户端误判操作成功。

### 影响范围
- 所有经过 controller 代理的 API 调用都可能出现类似问题
- 无法单纯依赖 API 返回码判断操作是否真正执行
- 需要结合节点类型和状态变更综合判断

### 已验证的 node_suspend 类型兼容性

| 类型 | suspend 效果 |
|------|-------------|
| qemu/docker/dynamips/virtualbox/vmware | ✅ 有效暂停进程 |
| cloud/nat/switch | ✅ 标记状态 |
| iou | ❌ 405 被吞掉 |
| vpcs | ❌ 405 被吞掉 |

### 如何避免
- 对支持 suspend 的节点类型做前置校验
- 交叉验证节点状态变更（如检查进程是否存在）
- 在 GNS3 上游修复前，客户端应增加类型兼容性检查

详见 [[phase10-node-lifecycle-test]]
