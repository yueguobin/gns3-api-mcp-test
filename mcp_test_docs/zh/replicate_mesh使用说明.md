# replicate_mesh.py — GNS3 mesh 批量复制脚本使用说明

`mcp-manual-test/replicate_mesh.py`：通过 GNS3 MCP 在项目中按 225px 网格批量复制一组路由器 mesh（节点 + 链路），用于搭建大规模 IOU 拓扑（如 100-node-iou 项目的 10×10 mesh 矩阵）。

## 前置条件

- Python 3.11+，依赖 `mcp` SDK（仓库 `.venv` 已安装）：用 `.venv/bin/python` 运行
- `.env` 连接配置（见 `.env.example`）：`GNS3_MCP_URL` / `GNS3_MCP_TOKEN`
  - 本机 GNS3 服务器：`GNS3_MCP_URL=http://127.0.0.1:3080/v3/mcp/transport/sse`
- **源 mesh 的节点必须 `stopped`**：GNS3 3.1.0.dev5 起禁止复制运行中的节点（409 "Cannot duplicate node data while the node is running"），脚本启动时会自动检查并报错

## 用法示例

```bash
# 预览计划（只读，安全）
.venv/bin/python mcp-manual-test/replicate_mesh.py \
    --project <project_id> --grid 4x3 --place down --dry-run

# 在源 mesh 右侧复制 2×2 = 4 组
.venv/bin/python mcp-manual-test/replicate_mesh.py \
    --project <project_id> --grid 2x2 --place right

# 指定原点复制（负坐标用 = 形式）
.venv/bin/python mcp-manual-test/replicate_mesh.py \
    --project <project_id> --grid 1x3 --origin=-1830,-105

# 补全既有矩阵（跳过已占位置）
.venv/bin/python mcp-manual-test/replicate_mesh.py \
    --project <project_id> --grid 10x10 --origin=-1830,-555 --skip-existing

# 修复：扫描网格帧，给完整的组补缺失链路（中断恢复用）
.venv/bin/python mcp-manual-test/replicate_mesh.py \
    --project <project_id> --grid 10x10 --origin=-1830,-555 --repair-links
```

## 参数

| 参数 | 说明 |
|---|---|
| `--project` | 项目 UUID（必填） |
| `--source` | 源 mesh 节点名，顺序定义角色 A/B/C…（默认 `R-1 … R-6`） |
| `--grid` | 复制几组：`WxH`（列×行），如 `4x3`、`1x3` |
| `--place` | `right` / `down` / `origin`：新块放在源 mesh 右侧 / 下方 / 指定原点 |
| `--origin` | `X,Y` 原点坐标（配合 `--place origin`；负坐标用 `--origin=X,Y` 等号形式） |
| `--spacing` | 网格间距 px（默认 225） |
| `--dry-run` | 只读预览计划（拓扑发现、位置、碰撞警告），不落地 |
| `--skip-existing` | 跳过与既有节点重叠的复制位（补全矩阵用） |
| `--repair-links` | 不复制节点；扫描网格帧内完整的 mesh，补建缺失链路，报告残缺组 |

## 行为与限制

- **拓扑自动发现**：从 `link_list` 筛选两端都在源节点内的链路，按相同 adapter/port 复刻 —— 对任意形状的源 mesh 通用（不硬编码 6 节点）
- **位置算法**：组内步进 `--spacing`，组间步进 `组列数×spacing` / `组行数×spacing`（由源 mesh 实际 3×2 布局推导）
- **碰撞检测**：目标位置与既有节点重叠时逐条警告（dry-run 可见；`--skip-existing` 则直接跳过）
- **IOU 512 节点硬顶**：IOU 的 application_id 空间为 1~512，同一 compute 上所有**已打开项目**的 IOU 节点总数不能超过 512（409 "Cannot create a new IOU node (limit of 512...)"）。`--repair-links` 会报告网格帧里因上限未建成的残缺组
- **中断安全**：节点阶段失败时 try/finally 仍会为已完成的组补建链路，不会留下"有节点无链路"的孤儿；复制出的节点**自带源 nvram 配置**（IOU duplicate 行为），多组同时启动会 IP/hostname 冲突
- `link_create` 按 ≤100 条/批分块

## 实测记录（2026-08-07）

- 100-node-iou 项目（`d82d5ee5-65c6-49fa-873f-bdb0790b393a`）从 6 台 IOU 起点扩展：
  - 手工+脚本逐步复制到 16 组（96 节点 / 176 链路）
  - `--grid 10x10 --skip-existing` 补齐时撞 512 上限（建到 511 节点），脚本中断
  - `--repair-links` 补 759 条链路，删除残节点 R-511
  - **最终：85 组 mesh = 510 节点 / 935 链路**（10×10 帧的 row0-7 满 + row8 前 5 列）
- 相关经验见 `.claude/memory/100node-iou-ospf.md`（编址规则、OSPFv2/v3 AF 语法、工具坑）
