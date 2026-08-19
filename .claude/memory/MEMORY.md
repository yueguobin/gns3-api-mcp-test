# Memory Index

- [MCP 后端优化记录](mcp-backend-optimization.md) — 批量接口提速/精简、auto_close、命名受 default_name_format 控制
- [MCP 坏工具规避](gns3-mcp-broken-tools.md) — template_list / device_command_run 报错的绕过方法（反查 template_id；用 do 前缀跑 show/ping）
- [MCP 返回双重包裹](gns3-mcp-double-envelope.md) — 结果 text 里套 {"type":"text","text":"..."}，取数据要先解包（用 _lib/gns3_mcp.py 的 _unwrap_envelope）
- [WS Console 连接姿势](gns3-ws-console-usage.md) — websocat -t --no-close + 用 node_console 返回的 URL（别改 127.0.0.1）+ 保持 stdin；改文件用 base64 编码避免 \r 污染
- [IOL bridge 不支持 delay filter](iol-bridge-no-delay-filter.md) — packet filter（delay/corrupt/loss）只在 dynamips/qemu 侧链路可用，IOU 链路报 409
- [优先看 MCP 工具描述](prefer-mcp-tool-desc-over-stale-memory.md) — 用法以工具自带 description 为准，别照搬陈旧 memory
- [容器重启只走 MCP](container-restart-via-mcp-only.md) — node_stop→node_start，禁用 docker CLI/exec/软重启
- [Full-mesh 单网关环路](fullmesh-single-gateway-loop.md) — full-mesh 多节点单网关上联时，网关不直连的网段走默认路由成环；补明细路由 + ip_forward
- [mark-test IPv6 部署](mark-test-ipv6.md) — 2026::/48+OSPFv3，规则 10.X.Y.Z→2026:X:Y::Z；跨平台语法（传统/AF/ospf6）；DAD DUP sticky、重置地址丢 OSPF、区域汇总用 /32 三大坑
- [100-node-iou OSPF](100node-iou-ospf.md) — 6×IOU L3 单区 OSPFv2/v3(AF)；编址 Lo=10.1.0.N/2026::N、链路=10.1.AB.0/30/2026:AB::；transit 改 point-to-point；device_show_run 同设备别发 2 条
- [1000-FRR-Node OSPF](1000-frr-node.md) — FRR 10.3 full-mesh 双栈 OSPFv2/v3；6 节点原型→复制 1002 节点/2505 链路；无 instance 模式、ospf6 router-id、裸 exit 掉 bash、ws timeout 贴输入时长、link_create 不带 label 会变 "4/0"（fix_link_labels.py 批修）
- [建节点用默认名](node-naming-use-default.md) — node_create 不自定义 name，沿用模板 default_name_format，除非用户明确要求
- [100-FRR-Node](100-frr-node.md) — 17 组六边形 full-mesh=102节点/255链路(FRRDockerLite 模板)；ping 矩阵比邻居表计数可靠、.venv 跑 replicate_mesh
- [uBridge 正常](ubridge-normal.md) — 链路不通别归咎 uBridge、别 link_reset/重启节点瞎修
- [Cisco telnet 不走 WS](cisco-telnet-no-ws.md) — cisco_ios_telnet 节点只用 device_config_send/device_show_run，websocat 仅限 docker 节点
- [XRd 节点 device 工具可用](xrd-node-device-config.md) — docker XRd 走 device_config_send/show_run；commit 手动、config 后补 end（两工具共享会话）；分页已修（08-17 更新）；server 更新会丢 XRd 配置、中途更新要 /mcp 重连
- [BGP 双 RR 双栈](bgp-rr-dual-stack.md) — AS64599 route-server 挂九组客户端全互通：①=10.1/16/②=10.2/16/④=10.3/16/=10.4/16(FRRDocker+2Ubuntu 星型单边界.44，ospf6 接口级 ipv6 ospf6 area，console 落 vtysh)/⑤=10.5/16(FRRDocker2-5 full-mesh 双边界.55/.56，staged 全是 10.4 克隆；RS console 也落 vtysh 了)/⑥=10.6/16(IOL串口PPP)/⑦=10.7/16(dynamips 7200串口PPP，R4/R8≠⑥组R-3/R-4)/⑧=10.8/16(XRd 24.4，eBGP 必挂 route-policy PASS、enforce-first-as 用 disable、AF 下敲 neighbor 会跳出 AF)/⑨=10.9/16(SRLinux v26.7.1 docker×4 双边界.99/.100→Switch2，OSPF 注默认不可行→内部静态 ECMP 默认)，边界 Null0+BGP 汇总+OSPF 注默认；staged 配置常有 area 错/克隆/缺 ipv6 unicast-routing、链路假死用 link_reset 单链路修复、node_links 不显示≠链路不存在
- [SR Linux v26 GNS3 坑清单](srlinux-v26-gns3.md) — admin-state 全家显式 enable、neighbor 强制 peer-group、nexthop 必须 ip-address 子叶（空{}=静默黑洞）、v6 双地址要 transport local-address、match 写 prefix prefix-set、OSPF export 对 static 无效、save startup、show 绝对路径
