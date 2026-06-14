---
name: gns3-mcp-template-batching
description: GNS3 MCP batch config — prefer template+vars over per-node config_commands
metadata:
  node_type: memory
  type: feedback
  originSessionId: be22a483-e694-47a9-bdb5-1f23d2d44538
---

When batch-configuring multiple GNS3 nodes with `device_config_send` / `device_command_run`, **prefer `template` (Jinja2) + per-node `vars`** over hand-writing full `config_commands` / `commands` arrays for each node.

**Why:** The tools' `template` parameter is designed exactly for configs that share structure and differ only in variables (docs: "Use with vars in each device to reduce token usage for batch config"). Hand-writing per-node command arrays is both token-heavy and error-prone (typos in IPs / AS numbers). The user pointed out — after the 4-AS BGP lab — that I never used the template parameter throughout.

**How to apply:** When ≥2 nodes share the same config/query structure with only a few variables differing, use template. E.g.:
- next-hop-self (8 borders): `template: "router bgp {{ as }}\naddress-family ipv4\nneighbor {{ rr }} next-hop-self"`, per-node `vars: {as, rr}`
- OSPF (5 nodes): `template: "router ospf 1\nrouter-id 10.{{as}}.{{rid}}.1\nnetwork 10.{{as}}.0.0 0.0.255.255 area 0"` + vars
- eBGP `network` statements, iBGP neighbors — same idea
Exception: when per-node structure differs a lot (e.g., intra-AS interface config where interface counts differ), still use per-node `config_commands`.

**Availability & gotchas (verified 2026-06-14):** `template`+`vars` now renders correctly in the backend (both `device_command_run` and `device_config_send`); `diagnostic_commands` echoes the rendered command so you can verify substitution. Two gotchas:
1. **Multiple vars-differing commands on the SAME node:** the current backend (2026-06-14, after three revisions: v1 lost data → v2 duplicated → v3) **merges same-`device_name` entries into ONE result entry**; `output` is the combined stream of all commands and `diagnostic_commands` lists them in order. Functionally fine (no loss, no duplication, splittable by command echo). Two minor caveats: ① output isn't pre-split per command — to get the i-th result programmatically you parse by command order; ② `len(result) != len(input)` (grouped by device) — don't index results by input position, look up by `device_name`. For the easiest per-command results, a single-entry multi-line template works too (same shape).
2. Previously this backend didn't render template at all (`KeyError 'commands'` / `'config_commands'`, template ignored, `{{x}}` sent literally) — a bug, fixed 2026-06-14.

**device_config_send batch-config practical points (2026-06-14, loopback×20 + add-path pilot):**
- `device_config_send` + template works for batch config; one call covers many nodes, rendering correct per node.
- **Don't judge success by `status:success` alone** — it only means "commands entered config mode, flow completed"; real IOS errors (`% overlaps` / `% Incomplete command` / `% Invalid input`) hide in the `output` text. After a batch, **scan each node's output for `%` lines**. (Example: setting an RR's Loopback1=10.x.13.1 overlapped its e0/3; the 4 RRs' status was still `success` but `output` showed `% overlaps with Ethernet0/3` — caught only by scanning `%`.)
- **Check for conflicts before batching:** compare new IPs against existing interface subnets; test a new command's syntax on one node first (`neighbor X advertise additional-paths` on this IOS needs a qualifier `all`; the pilot caught `% Incomplete command`).
- **Pilot first:** test rendering + syntax + effect on 1-2 nodes, then scale to all. The add-path pilot revealed "no benefit in this topology," saving 20 nodes of pointless config (see [[gns3-bgp-lab]] add-path entry).
- **Rollback:** `no <original-cmd>` to remove + `show run | include <keyword>` to verify cleared; if a change wasn't `write memory`'d, reload reverts running-config automatically (startup not polluted).

Related: [[gns3-bgp-lab]].
