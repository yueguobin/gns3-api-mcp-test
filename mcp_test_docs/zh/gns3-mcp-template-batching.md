---
name: gns3-mcp-template-batching
description: GNS3 MCP 批量配置优先用 template+vars，而非逐节点手写 config_commands
metadata: 
  node_type: memory
  type: feedback
  originSessionId: be22a483-e694-47a9-bdb5-1f23d2d44538
---

用 `device_config_send` / `device_command_run` 批量配置多个 GNS3 节点时，**优先用 `template`（Jinja2）+ 每节点 `vars`**，而不是给每个节点手写完整的 `config_commands`/`commands` 数组。

**Why:** 这些工具的 `template` 参数正是为结构相同、只差变量的批量配置设计的（文档原话："Use with vars in each device to reduce token usage for batch config"）。手写逐节点命令数组在重复场景下既费 token、又易抄错（IP/AS 号写错）。用户在 4-AS BGP 实验配置后明确指出我全程没用过 template 参数。

**How to apply:** 当 ≥2 个节点的配置/查询结构一致、只有少数变量不同时，用 template。例如：
- next-hop-self（8 border）：`template: "router bgp {{ as }}\naddress-family ipv4\nneighbor {{ rr }} next-hop-self"`，每节点 `vars: {as, rr}`
- OSPF（5 节点）：`template: "router ospf 1\nrouter-id 10.{{as}}.{{rid}}.1\nnetwork 10.{{as}}.0.0 0.0.255.255 area 0"` + vars
- eBGP network 通告、iBGP neighbor 同理
例外：每节点结构差异大（如接口数不同的域内接口配置）时仍用逐节点 config_commands。

**可用性与坑（2026-06-14 实测）：** `template`+`vars` 后端现已正常渲染（`device_command_run`/`device_config_send` 均可），`diagnostic_commands` 回显渲染后真实命令可核对替换是否正确。两条坑：
1. **同一节点跑多条不同 vars 命令**：现行后端(2026-06-14，经 v1丢数据→v2冗余→v3 三次改动)把同 `device_name` 多条目**合并成 1 个结果条目**，output 为全部命令的合并流、`diagnostic_commands` 有序对应。功能上 OK（不丢、不冗、可按命令回显切分）。仅两点次要注意：①无预切好的逐条 output，要程序化取第 i 条得自己按命令顺序解析；②`len(返回)!=len(输入)`（按设备归组），别用输入下标取结果，按 `device_name` 取。要最省事的逐命令结果，仍可用单条目多行模板（返回形态其实一样）。
2. 此前该后端的 template 完全不渲染（`KeyError 'commands'`/`'config_commands'`、忽略 template、字面量下发 `{{x}}`），属 bug，2026-06-14 已修。

**device_config_send 批量配置实测要点（2026-06-14，loopback×20 + add-path pilot）：**
- `device_config_send` + template 批量改配置可用，一次调用覆盖多节点，渲染逐节点正确。
- **判配置成败别只看 `status:success`**——它只代表"命令进 config 模式、流程走完"；IOS 真实错误（`% overlaps` / `% Incomplete command` / `% Invalid input`）藏在 `output` 文本里。批量后**逐节点扫 output 的 `%` 行**。（实例：给 RR 配 Loopback1=10.x.13.1 撞其 e0/3，4 台 RR 的 status 仍是 success，但 output 出现 `% overlaps with Ethernet0/3`，靠扫 `%` 才发现。）
- **批量前先查冲突**：新 IP 对比现有接口子网；新命令先在 1 台试对语法（`neighbor X advertise additional-paths` 本 IOS 需带限定词 `all`，pilot 阶段抓到 `% Incomplete command`）。
- **pilot 先行**：1-2 台试渲染+语法+效果，再扩全量。add-path pilot 据此发现"此拓扑无收益"，省了 20 台无效配置（见 [[gns3-bgp-lab]] 的 add-path 条目）。
- **回滚**：`no <原命令>` 删除 + `show run | include <关键字>` 验证已清；若改动没 `write memory`，reload 自动还原 running-config（startup 未被污染）。

关联 [[gns3-bgp-lab]]。
