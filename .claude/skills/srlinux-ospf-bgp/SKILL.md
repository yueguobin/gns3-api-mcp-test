---
name: srlinux-ospf-bgp
description: Configure Nokia SR Linux docker nodes (v26.x) in GNS3 with dual-stack OSPFv2+OSPFv3 and BGP uplinks — sr_cli syntax templates (instance/version/address-family/admin-state, peer-group, next-hop-groups, routing-policy), ws console push procedure (enter candidate private + commit save), and adjacency/session/ping verification. Trigger scenarios: user asks to configure OSPF/BGP on SR Linux routers, build an SRL full mesh, or troubleshoot SRLinux (sessions not coming up, config lost after restart, silent blackholes).
---

# SR Linux OSPF+BGP Configuration Skill (GNS3 docker nodes)

Configure SR Linux docker nodes in GNS3 (template `ghcr.io/nokia/srlinux:latest`, verified on v26.7.1) with dual-stack OSPFv2+v3 mesh plus border eBGP/iBGP. Everything below was verified on a 4-node full mesh with dual borders (2026-08-20, group ⑨).

## 1. Preliminaries: nodes and links

- Derive the interface map from `node_list`/`link_list`: **GNS3 adapter N ↔ port e1-N ↔ SR Linux `ethernet-1/N`** (adapter 0 = mgmt0); the `GNS3_INTERFACE_NAMES` env var confirms it.
- console_type is **docker_exec**; each ws attach spawns a fresh sr_cli (`A:root@srlinux#`, root context). Connection template per [[gns3-ws-console-usage]]: `{ printf '\r\n'; sleep 3; ...; } | timeout N websocat -t --no-close '<ws_url from node_console, copied byte-for-byte>'`.
- **Three syntax-discovery tools**: ① a wrong token makes the parser **enumerate the complete list of valid children** (`... ospf zzz` → Options are [...]); ② `tree /network-instance <container>` renders the schema (path takes **no list keys**); ③ `?` help truncates and the "press '?' again" state swallows subsequent commands — **never chain `?` probes**.
- `show` resolves **relative to the current context**; absolute paths `show /network-instance default ...` are the most reliable. For the route table use `info from state /network-instance default route-table` (the show form rejects family suffixes). The `[FACTORY]` banner in the prompt is normal display — it does NOT mean factory config.

## 2. Addressing scheme (group-⑨ style, reusable for any group number X)

- Link A↔B: `10.X.AB.0/24` with host part = node number + `2026:X:AB::N/64`; loopback lo0.0 = `10.X.N.N/32` + `2026:X:N::N/128`
- Border uplink interface (254 segment) carries three addresses: `10.254.254.NN/24` + `2026::NN/64` (side plane) + `2026:254:254::NN/64` (BGP plane)

## 3. Configuration templates (one per node, push block by block after `enter candidate private`)

**v26 hardened defaults: protocols and AFs are disabled by default — every one needs an explicit `admin-state enable`** (ospf instance, bgp, bgp afi-safi globally AND per group). Missing it produces "interface Adm Up / Oper Down, Tx Hello=0, zero neighbors" or "BGP neighbor rows never appear at all".

Internal node (interface block ×N + loopback + NI binding + two OSPF instances + static ECMP default):

```text
/interface ethernet-1/1 {
    admin-state enable
    subinterface 0 {
        admin-state enable
        ipv4 { admin-state enable
            address 10.X.12.1/24 }
        ipv6 { admin-state enable
            address 2026:X:12::1/64 }
    }
}
/interface lo0 { ...subinterface 0 with 10.X.1.1/32 + 2026:X:1::1/128... }
/network-instance default {
    interface ethernet-1/1.0 { }
    interface ethernet-1/2.0 { }
    interface ethernet-1/3.0 { }
    interface lo0.0 { }
    next-hop-groups {
        group DEFAULT4 {
            nexthop 1 { ip-address 10.X.13.3 }     ← border-1 directly connected address
            nexthop 2 { ip-address 10.X.14.4 }     ← border-2 directly connected address
        }
        group DEFAULT6 { ...same with v6... }
    }
    static-routes {
        route 0.0.0.0/0 { next-hop-group DEFAULT4 }
        route ::/0 { next-hop-group DEFAULT6 }
    }
}
/network-instance default protocols ospf {
    instance ospf-v2 {
        admin-state enable
        version ospf-v2                          ← value is ospf-v2/ospf-v3, NOT a number
        router-id 10.X.1.1
        area 0.0.0.0 {
            interface ethernet-1/1.0 { advertise-subnet true }   ← default advertises /32 only!
            ...
            interface lo0.0 { passive true }
        }
    }
    instance ospf-v3 {
        admin-state enable
        version ospf-v3
        address-family ipv6-unicast              ← mandatory on v3; forbidden on v2
        router-id 10.X.1.1
        area 0.0.0.0 { ...same as above... }
    }
}
commit save
```

Border node adds three blocks:

```text
/routing-policy {
    prefix-set DEFAULT-ONLY {
        prefix 0.0.0.0/0 mask-length-range exact { }
        prefix ::/0 mask-length-range exact { }
    }
    prefix-set AGG-ONLY {
        prefix 10.X.0.0/16 mask-length-range exact { }
        prefix 2026:X::/32 mask-length-range exact { }
    }
    policy OSPF-EXPORT-DEFAULT { statement 10 { match { protocol static
                prefix { prefix-set DEFAULT-ONLY } }        ← inside match: prefix prefix-set (nested block form)
            action { policy-result accept } }
        default-action { policy-result reject } }
    policy BGP-EXPORT { statement 10 { match { protocol static
                prefix { prefix-set AGG-ONLY } } action { policy-result accept } }
        statement 20 { match { protocol bgp } action { policy-result accept } }
        default-action { policy-result reject } }
    policy BGP-IMPORT-ALL { default-action { policy-result accept } }
}
/network-instance default {
    interface ethernet-1/34.0 { }                ← uplink port joins the NI too
    next-hop-groups { group BLACKHOLE { blackhole { } } }   ← Null0 equivalent (v26 has no next-hop discard)
    static-routes {
        route 10.X.0.0/16 { next-hop-group BLACKHOLE }      ← aggregate anchor → originated by BGP
        route 2026:X::/32 { next-hop-group BLACKHOLE }
        route 0.0.0.0/0 { next-hop-group BLACKHOLE
            preference 250 }                                 ← fallback default (only catches unknowns)
        route ::/0 { next-hop-group BLACKHOLE
            preference 250 }
    }
}
/network-instance default protocols bgp {
    admin-state enable
    autonomous-system 645XX
    router-id 10.X.N.N
    afi-safi ipv4-unicast { admin-state enable }
    afi-safi ipv6-unicast { admin-state enable }
    import-policy [ BGP-IMPORT-ALL ]            ← references use list syntax [ name ]
    export-policy [ BGP-EXPORT ]
    group ebgp-rs { peer-as <RS-AS>
        afi-safi ipv4-unicast { admin-state enable }
        afi-safi ipv6-unicast { admin-state enable } }
    group ibgp-core { peer-as 645XX
        afi-safi ipv4-unicast { admin-state enable }
        afi-safi ipv6-unicast { admin-state enable } }
    neighbor 10.254.254.101 { peer-group ebgp-rs }
    neighbor 10.254.254.102 { peer-group ebgp-rs }     ← neighbors MUST reference a peer-group!
    neighbor 10.254.254.<peer-border> { peer-group ibgp-core }
    neighbor 2026:254:254::101 {
        peer-group ebgp-rs
        transport { local-address 2026:254:254::NN }   ← v6 must pin the source (see pitfall table)
    }
    ...
}
```

Add `export-policy OSPF-EXPORT-DEFAULT` to both ospf instances (plain single-value reference). Note: **on v26 this export produces zero Type-5 LSAs for static routes in practice** (the table-connections destination-protocol enum only has bgp|gribi|isis|local|static — no ospf), which is why internal default routes come from static ECMP on internal nodes; the export-policy is kept as a semantic placeholder.

## 4. Push procedure

- Feed block configs **line by line at 0.15s/line** (while-read loop). **Consecutive same-leaf list lines inside one block (e.g. two ipv6 address lines on one interface) race the paste and get dropped/misplaced** — push the second address as a separate single-line path command: `/interface ethernet-1/34 subinterface 0 ipv6 address 2026:254:254::NN/64`
- **There is no `;` multi-statement separator!** `{ A; B }` folds the semicolon into the value (leafref becomes `"X;"`) and commit fails with "Leafref ... does not exist". Multiple leaves = separate lines or separate single-line commands.
- Config changes require `enter candidate private` first; **commands sent in running mode silently do nothing** (no error, no effect).
- Finish with **`commit save`** (commit + persist to /etc/opt/srlinux/config.json in one step). **Do NOT use `save startup`** — it prints the same success message but is not loaded after a gns3server restart (all four nodes came back factory, verified); `save config` does not exist.
- Commits are atomic: one error invalidates everything; the error path is in "Error in /path"; the candidate survives so you can fix and re-commit.
- After commit save you are back in running — **re-enter candidate private before pushing any follow-up config**.

## 5. Verification

```text
show /network-instance default protocols ospf instance ospf-v2 neighbor   → expect N-1 full
show /network-instance default protocols ospf instance ospf-v3 neighbor
show /network-instance default protocols bgp neighbor                     → expect 6 established + the Summary line
info from state /network-instance default route-table                     → static/OSPF/BGP routes and next-hop-groups
ping network-instance default 10.254.254.101 -c 3                          ← Linux-style flags: -c count -I source -t ttl
```

- Zero neighbors → check `show .../ospf instance ospf-v2 status` for **OSPF Admin Status** (disable = missing admin-state enable).
- v6 sessions stuck in connect/active while ping works → check the neighbor's transport local-address.
- Remote subnet pings time out (timeout, NOT "network unreachable") → `info from state ... next-hop-groups` and check whether the **nexthops carry ip-address** (empty `{}` entries are dropped; an empty group = silent blackhole).

## 6. Pitfall quick reference

| Symptom | Cause | Fix |
|---|---|---|
| OSPF interfaces Adm Up/Oper Down, 0 neighbors | instance missing admin-state enable | add it to both instances |
| commit rejects version value | `version 2` | `version ospf-v2` / `ospf-v3` |
| v3 commit: must have address family | v3 missing AF | `address-family ipv6-unicast` (v2 must NOT have it) |
| commit: neighbor peer-group Mandatory | v26 neighbors require a group | `neighbor X { peer-group <g> }`, peer-as lives on the group |
| commit: Leafref "X;" does not exist | `;` used to join leaves | split into lines/single-line commands, resend to overwrite |
| BGP neighbor rows never appear | afi-safi not enabled | enable globally AND on every group |
| v6 sessions connect/active, ping fine | source selection on dual-v6 uplink | `transport { local-address 2026:254:254::NN }` |
| remote subnet ping times out (not unreachable) | empty nexthop `{}` dropped → empty NHG | `nexthop 1 { ip-address X }`; verify with info from state |
| OSPF only learns /32s, no link subnets | missing advertise-subnet | `advertise-subnet true` on transit interfaces |
| OSPF export-policy yields no Type-5 | v26 mechanism absent for statics | static ECMP defaults on internal nodes instead |
| prefix-set rejected inside match | flat `prefix-set X` | `prefix { prefix-set X }` block, or one-liner `match prefix prefix-set X` |
| import/export-policy: Expected '[' | they are lists | `import-policy [ name ]` |
| config gone after gns3server restart | used save startup | re-push + `commit save` (survives node stop/start, verified) |
| no `next-hop discard` on static routes | v26 model change | next-hop-groups group + `blackhole { }` |
| show network-instance → usage/Unknown token | context-relative show, family suffix rejected | absolute `show /network-instance ...`; state via `info from state` |
| commands swallowed after `?` help | truncated help state | don't chain `?`; use wrong-token error enumeration |

## 7. Related

- memory: [[srlinux-v26-gns3]] (full pitfall log), [[bgp-rr-dual-stack]] (group-⑨ topology and three-piece border pattern), [[gns3-ws-console-usage]] (ws connection template)
