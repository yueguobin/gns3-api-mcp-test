# 阶段 17: Alpine Linux（Docker）节点批量测试 - 测试记录

## 测试基本信息

**阶段编号**: 阶段 17  
**阶段名称**: Alpine Linux（Docker）节点批量测试  
**测试日期**: 2026-06-16  
**测试类型**: 专项测试（Docker 节点批量创建 + 全互联/循环图拓扑）  
**节点类型**: Docker / Alpine Linux（docker 类型）  
**测试状态**: ✅ 全部通过  

### 测试服务器环境

| 项目 | 值 |
|------|-----|
| 主机名 | home |
| OS | Debian GNU/Linux 12 (bookworm) |
| 内核 | Linux 6.1.0-42-amd64 x86_64 |
| CPU | Intel Pentium Silver J5040 @ 2.00GHz（4 核） |
| 内存 | 11 GiB |
| 磁盘 | 915G |

---

## 测试目标

前两阶段分别验证了 **Dynamips c7200**（阶段 15）和 **QEMU IOSv**（阶段 16）的大规模批量能力。本阶段切换到 **Docker 类型的 Alpine Linux**，对比验证：

1. **Docker 节点批量创建**：一次性创建 100 台 Alpine Linux Docker 容器
2. **全互联（full mesh）拓扑**：10 节点全互联 = 45 条链路
3. **循环图 C(100,{1,2}) 拓扑**：100 节点每节点 4 条 = 200 条链路
4. **Docker 端口模型**：每个容器 `adapters=30`，port 模型与 QEMU/Dynamips 不同

---

## 测试对象：Alpine Linux 模板

**模板名**: Alpine Linux  
**模板 ID**: `ef7d4150-d6d1-4ff4-816b-403e2235776e`  
**类型**: `docker`  
**镜像**: `alpine`  
**网卡**: `adapters=30`（30 个 ethernet 接口，每个 1 个端口）  
**默认命名格式**: `{name}-{0}`

### Docker 端口模型

| 属性 | 说明 |
|------|------|
| `adapters` | 30（可用 adapter 0~29） |
| 每 adapter 端口数 | 1（port 0） |
| 端口标签 | `{adapter_number}/0` |

> Docker 容器的多 adapter 模型与 QEMU IOSv（adapters=4）类似，但 adapter 数多达 30 个，适合密集拓扑。

---

## 工具列表

1. `mcp__My_GNS3_Server__project_create` / `project_update` - 创建项目
2. `mcp__My_GNS3_Server__node_create` - 批量创建节点
3. `mcp__My_GNS3_Server__node_list` - 查询节点
4. `mcp__My_GNS3_Server__link_create` - 批量创建链路
5. `mcp__My_GNS3_Server__link_list` - 查询链路总数
6. `mcp__My_GNS3_Server__node_links` - 查询单节点链路

---

## 测试过程

### 测试 17.1: 10 节点全互联 + 无冲突端口验证

**工具**: `project_create` / `node_create` / `link_create`  
**项目**: alpine-mesh-test（0338f597-…）  
**验证目的**: Docker 多 adapter 端口映射 + full mesh 端口无冲突

#### 步骤

1. 创建 10 台 Alpine Linux Docker 节点（顶层 `template_id`）
2. 建 45 条全互联链路

#### 端口映射方案（full mesh）

对于节点 `(i, j)` 其中 `i < j`：
- node_i 用 `adapter_(j-1)` / port0
- node_j 用 `adapter_i` / port0

每节点最多用 9 个 adapter（0~8），低于 30 的上限，无冲突。

#### 验证
```
link_list → count: 45
node_links(AlpineLinux-1) → count: 9（连到其他全部 9 台）
```

#### 关键发现

- ❌ **首次尝试端口映射错误**：错用 adapter 0 连接所有链路，导致 409 Port already used。删除重做后正确。
- ✅ 正确映射后 45 条全部 success
- ✅ Docker 适配器 30 个远多于 QEMU IOSv（4 个），全互联 10 节点只需 9 个

#### 测试结论
✅ **测试成功** - 10 节点 full mesh 正确使用多 adapter

---

### 测试 17.2: 100 节点 + 循环图 C(100,{1,2}) = 200 条链路

**工具**: `mcp__My_GNS3_Server__node_create` / `link_create`  
**项目**: alpine-100（efe40892-…）

#### 创建 100 个 Alpine Docker 节点

```json
{
  "project_id": "efe40892-...",
  "template_id": "ef7d4150-d6d1-4ff4-816b-403e2235776e",
  "nodes": [
    {"x":100,"y":100}, {"x":220,"y":100}, ... 共 100 项
  ]
}
```

**返回**: 100/100 ✅ success（Docker 创建极快，无超时）

#### 拓扑：循环图 C(100,{1,2})

每节点 4 条链路：
- dist1 环 `(i, i+1)`：adapter 0 ↔ adapter 2
- dist2 环 `(i, i+2)`：adapter 1 ↔ adapter 3

节点命名参考：`AlpineLinux-1` ~ `AlpineLinux-100`

#### 创建 200 条链路

| 批次 | 链路数 | 类型 | 端口映射 | 结果 |
|------|--------|------|----------|------|
| 1 | 50 | dist1（i=0..49） | ad0 ↔ ad2 | ✅ success |
| 2 | 50 | dist1（i=50..99 + wrap） | ad0 ↔ ad2 | ✅ success |
| 3 | 50 | dist2（i=0..49） | ad1 ↔ ad3 | ✅ success |
| 4 | 50 | dist2（i=50..99 + wrap） | ad1 ↔ ad3 | ✅ success |

> 注：`link_create` 单次批量创建的实际处理上限约 50 条（11KB），200 条分 4 批创建。

#### 验证
```json
link_list(fields=["link_id"]) → {"links": [200 条], "count": 200}
```

#### 结果分析

**✅ 100 节点 + 200 链路全部成功**
- 100/100 节点，200/200 链路
- 每节点 4 条，适配器 0/1/2/3 各一
- Docker 创建速度远快于 QEMU（无需复制磁盘镜像）

#### 测试结论
✅ **测试成功** - 100 节点循环图拓扑全部建成

---

## 阶段测试总结

### 功能验证结果

| 测试项 | 工具名称 | 规模 | 状态 | 备注 |
|-------|---------|------|------|------|
| 17.1 10 节点全互联 | node_create / link_create | 10节点/45链路 | ✅ 成功 | 首次有端口冲突，修正后通过 |
| 17.2 100 节点循环图 | node_create / link_create | 100节点/200链路 | ✅ 成功 | 链路分 4 批 |

### 规模统计

| 资源 | 数量 | 说明 |
|------|------|------|
| 项目 | 1 | alpine-100（保留） |
| 节点 | 100 | AlpineLinux-1~100 |
| 链路 | 200 | dist1 环 100 + dist2 环 100 |
| 每节点端口 | 4 | adapter 0/1/2/3 |
| 节点类型 | docker | Alpine Linux |

### Docker vs QEMU vs Dynamips 创建速度对比

| 节点类型 | 100 台耗时 | 特点 |
|---------|-----------|------|
| Dynamips c7200 | 很长 | 需加载 IOS 镜像，资源占用大 |
| QEMU IOSv | ~190s | 需 linked_clone 复制 qcow2 |
| Docker Alpine | **秒级** | 容器化，无需磁盘镜像 |

### 关键发现

- 🟢 **Docker 批量创建极快**：100 台秒级完成，远快于 QEMU/Dynamips
- 🟢 **多 adapter 端口充足**：30 个 adapter 可支撑密集拓扑
- 🟢 **`link_create` 单次上限约 50 条**（11KB），超限后需分批
- 🟢 **顶层 `template_id` 生效**：与阶段 16 一致
- 🟡 **端口分配需谨慎**：Docker 的 port_number 恒为 0，不同链路必须用不同 adapter_number 区分

---

## 测试签名

**测试执行**: Claude  
**测试监督**: YueGuobin  
**测试日期**: 2026-06-16  
**测试状态**: ✅ 全部通过  
**项目完成度**: 2 个测试项，100 节点 + 200 链路

---

**文档创建时间**: 2026-06-16  
**最后更新**: 2026-06-16  
**文档版本**: 1.0
