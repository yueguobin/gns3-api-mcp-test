# GNS3 3.1 dev — Kernel Datapath vs Userspace Relay: Four-Platform Comparison

**Scope.** A controlled re-test of the same experiment menu on four emulation platforms, before and after the GNS3 server's *kernel datapath* feature was removed:

| Platform | Field / project | Kernel-datapath build (baseline) | Relay-only build (re-test) |
|---|---|---|---|
| Docker containers (FRR) | `Kernel-DataPath-Docker-FRRDocker` | `3.1.0.dev7+2445e2e5e` | `3.1.0.dev7+38cc7cc0a` |
| QEMU VMs (FRR/Alpine) | `Kernel-DataPath-Qemu-FRRqemu` (+ `-virtio`) | `3.1.0.dev7+2445e2e5e` | `3.1.0.dev7+38cc7cc0a` |
| Cisco IOU (IOU L3) | `Kernel-DataPath-Iou-CiscoIOU` | `3.1.0.dev7+506a6bc94` | `3.1.0.dev7+38cc7cc0a` |
| Dynamips (c7200) | `Dynamips-Kernel-DataPath-test-Cisco7200` | kernel-datapath build (§10 record) | `3.1.0.dev7+38cc7cc0a` |

**Provenance.** All "relay-only" values are **measured** on server `3.1.0.dev7+38cc7cc0a` (2026-10-04/05) and recorded in four per-field reports (see §10). All "kernel-build" values are **quoted** from the earlier kernel-datapath baseline records. Anything marked *inferred* is a hypothesis, not a measurement. The Mixed-NOS field was intentionally left out of scope.

Each platform was tested with the same shape: an 11-router linear chain R1..R11, a dual parallel ECMP pair between R1 and R2, loopbacks `10.x.0.N/32`, two Ubuntu Docker hosts at both ends, OSPFv2 single area, and (IOU/Dynamips) a serial relay control link outside OSPF.

---

## 1. Executive summary

1. **The kernel datapath is gone from the API.** `link_get` no longer reports a `kernel_datapath` field; every link now runs on the uBridge **userspace relay**.
2. **Filter capability is cut from 13 types to 5** (frequency_drop / packet_loss / delay / corrupt / bpf) on **every** link, on **every** platform. The 8 kernel-only filters (rate, reorder, gemodel, duplicate, seed, limit, quota, window_drop) now return HTTP 409 with **no migration guidance**.
3. **Functional behavior: zero regression.** 22/22 OSPF adjacencies, ttl=53, 12-line traceroutes, ECMP, and stop/start survival were identical to the kernel builds on all four platforms.
4. **The 5 remaining filters behave identically** to the kernel build (bidirectional per-direction semantics: RTT loss = 1−(1−L)², RTT delay = 2× one-way). delay now strictly requires 2 parameters (`[X, 0]`).
5. **Performance impact is strongly platform-dependent:**
   - **Docker: severe.** E2E RTT ×5–6; throughput ÷14–25 on multi-stream; the 10–20 Gbps class collapses to a ~1.3 Gbps single-source ceiling.
   - **QEMU: moderate.** Latency unchanged (VM crossing dominates); single-stream throughput ÷2.3; the virtio advantage shrinks from ×5.1 to ×2.2 and multi-stream degrades to unstable.
   - **IOU and Dynamips: none measurable.** Their own forwarding stacks (IOL userspace process / MIPS emulation) are already slower than the relay, so the relay is invisible.
6. **Rule of thumb [inferred]:** the relay adds a fixed cost of ~0.1–0.2 ms per segment transit and caps a single source at roughly 1.2–3 Gbps. Platforms whose native per-hop cost is below those numbers are unaffected.

---

## 2. What changed at the platform/API layer

| | Kernel-datapath build | Relay-only build (current) |
|---|---|---|
| `link_get` → `kernel_datapath` | `true` on kernel links, `false` on relay links | **Key removed entirely** (not `false`) |
| `link_available_filters` | **13 types** | **5 types** (frequency_drop, packet_loss, delay, corrupt, bpf) |
| Requesting a kernel-only filter | Accepted on kernel links | **HTTP 409** `Invalid packet filter parameters: Unknown filter type: <name>` — **no guidance text** (the kernel build's relay-link 409s suggested deleting/recreating the link to switch datapath) |
| `delay` parameter validation | `[50]` accepted (jitter defaulted) | **Exactly 2 parameters required**: `delay expects 2 parameter(s), got 1` |
| Data plane | kernel (tc netem / eBPF, tap/veth anchored per platform) | uBridge userspace relay over UDP tunnels |

**Implementation evidence.** For QEMU the change is directly visible in `node_get` command_line [measured]: `-netdev tap,ifname=gq<node>e<N>p0,script=no` became `-netdev socket,id=gns3-N,udp=127.0.0.1:XXXXX,localaddr=…`. For IOU and Dynamips the relay fallback is [inferred] from two facts: the `kernel_datapath` field is gone, and their Ethernet links now expose exactly the same 5-filter set that the serial relay links always had (their kernel anchors — `iol_bridge add_nio_tap` for IOU, persistent TAPs for Dynamips — were removed with the feature).

---

## 3. Functional baseline — zero regression (all four platforms)

| Measurement | Kernel build [quoted] | Relay-only [measured] |
|---|---|---|
| OSPF adjacency | 22/22 Full | **22/22 Full**, zero-intervention cold boot (NVRAM / frr.conf auto-restore), all four platforms |
| host1→host2 ttl / traceroute | ttl=53 / 11 router hops | **ttl=53 / 12 lines** (11 routers + destination) |
| ECMP | dual next-hop toward far loopbacks | **dual next-hop preserved** (R1 traffic share 1:1) |
| Filter-free baseline after all tests | clean | **clean** (e.g., IOU 30/30 0%; Dynamips 30/30, 4/36/64 ms) |

---

## 4. Packet filters — 5 kept, 8 lost

### 4.1 The remaining five — kernel build → relay build, per platform

| Filter | Docker | QEMU | IOU | Dynamips |
|---|---|---|---|---|
| `delay` | [50,0]: 100.179 → **100.625 ms** (mdev 0.088) | [10,0]: 27.474 → **26.853 ms** | [50,0]: 100/101/102 → **100/100/102 ms** | [50,0]: avg 131 → **124/150/160 ms** (min Δ96 ≈ 2×50) |
| `delay`+jitter | [50,20]: mdev 27.167 → **27.035** | — | — | — |
| `packet_loss` | [30] n=61: 56% → **55.74%** | [10] n=200: 20.5% → **18.5%** (theory 19%) | [10] n=200: 15% → **18.5%** | [10] n=200: **19.0% → 19.5%** (161/200) |
| `corrupt` | [30] n=61: 53.3% → **57.38%** | [30] n=200: (6-node [50] 84%) → **53%** | [30] n=200: **52.5%** | [30] n=200: **51.5%** (theory 51%) |
| `bpf` (`icmp[icmptype]==8`) | 100% drop, OSPF untouched | 100% drop, OSPF untouched | 0/10, OSPF FULL both sides | 0/10, OSPF FULL both sides |
| `frequency_drop` [3] | n=61: 61.9% → **52.46%** | n=200: 56% → **49.5%** | n=200: 55.5% → **51% / 49%** | n=200: 58%/56% → **59.5% / 61%** |
| Serial relay link `delay` [50,0] | — | — | 121 → **120–121 ms** | 120/147/160 (Δ98) → **100/128/156** (Δ92) |

All five behaved item-for-item as in the kernel builds: 2× one-way delay, RTT loss = 1−(1−L)², BPF selectivity with control-plane untouched.

### 4.2 The eight filters that are gone

`rate`, `reorder`, `gemodel`, `duplicate`, `seed`, `limit`, `quota`, `window_drop` — every one returned 409 on every platform. This retires a whole class of experiments (rate shaping by frame length, packet reordering, Gilbert-Elliott burst loss, duplication, deterministic seeding, token-bucket quota, time-window outages) on the current build.

### 4.3 frequency_drop — a cross-platform discrepancy worth knowing

Theory for RTT loss under drop-every-3rd is 55.6%. Measured, relay-only:

| | Docker | QEMU | IOU | Dynamips |
|---|---|---|---|---|
| relay build | 52.5% | 49.5% | 49–51% | **59.5% / 61%** |
| kernel build [quoted] | 61.9% | 56% | 55.5% | 58% / 56% |

Docker/QEMU/IOU cluster near ~50%, Dynamips near ~60% — i.e. **"relay ⇒ ~50%" is not a universal signature**; Dynamips reproduces its own kernel-era bias direction. Best explanation [inferred]: the every-Nth counter counts *all* frames on the link (OSPF hellos, Ethernet keepalives, CDP), so the ping-visible drop rate drifts with each platform's background-frame mix ("mixed-flow phase"). Practical rule: validate frequency_drop precisely only on a quiet link (passive-interface + no CDP), and never judge filter health from a single short sample (n ≥ 200).

---

## 5. Performance impact per platform

### 5.1 Summary matrix

| Metric | Docker | QEMU | IOU | Dynamips |
|---|---|---|---|---|
| E2E RTT, kernel → relay | 0.36 → **1.9–2.2 ms (×5–6)** | 6.63 → **5.5–6.7 ms (flat)**¹ | 1.91 → **2.23 ms (≈, cross-session indicative)**¹ | 521 → **454–542 ms (flat)** |
| Direct link RTT | 0.099 → **0.32–0.54 ms** | — | single hop **0.54–0.55 ms** | per-hop ~30–40 ms (kernel ~45) |
| Single stream | 2.22 G → **1.28 G (÷1.7)** | 342 M → **139–148 M (÷2.3)** | 126 M → **128–131 M (flat)** | 524K/114K → **629K/104K (1 retr)** |
| Multi-stream | 16-str 19.4 G → **1.36 G (÷14)**; 32-str ÷17 | 16-str 171 M → **104–124 M** | 8-str 272 M → **181–209 M** | 8-str → 419K–1.47 M sender / 0 receiver |
| Multi-stream amplification | **lost** (single ≈ 16 ≈ 32 ≈ 1.2–1.4 G) | same decline shape as kernel, level halved | retained (platform > single ×1.5) | never existed (RTO collapse) |
| Notes | per-segment relay cost ~0.1–0.2 ms; converges with kernel at ≥5 ms delay (both cwnd-limited) | virtio copy: single 1.73 G → **305–320 M (÷5.4)**, multi-stream collapses; virtio leverage ×5.1 → ×2.2 | **no measurable degradation** — IOL userspace forwarding dominates; retransmissions dropped 1541 → ~530 | **no degradation** — MIPS emulation + idle-sleep dominate (2–3 orders below Docker) |

¹ Measured under controlled host CPU load (see §6-1).

### 5.2 Reading the matrix

- **Docker is the only field where the relay hurts badly.** Its kernel path was the fastest in the fleet (2.2 Gbps single, 19.4 Gbps ×16), so the relay's ~1.3 Gbps single-source ceiling and per-packet userspace cost are exposed. A dual-source test (2×16 streams, 1.24 + 1.25 G) shows the ceiling is *per source*, not one shared hard bottleneck; a 1-hop 2-segment test (3.0 G) shows throughput steps down with each relay segment [measured].
- **QEMU loses throughput but not latency.** Its bottleneck was already the VM crossing (~0.5 ms/VM, +0.52 ms/VM after relay vs +0.62 before), so latency is unchanged; throughput halves because relay forwards packet-by-packet and breaks the GSO/TSO super-frame amortization that virtio depends on [inferred].
- **IOU and Dynamips don't notice.** IOU's per-hop cost is its userspace IOL forwarder; Dynamips' is MIPS emulation + 30 ms idle-sleep slices. Both are so much slower than the relay that removing the kernel path is invisible in latency and throughput — including a *reduction* in TCP retransmissions for IOU (1541 → ~530) [measured].
- **Delay semantics hold everywhere**: full-chain anchors reproduce the kernel values (QEMU 11×5 ms: 108.81 ms/116 M vs kernel 109.47 ms/131 M; Dynamips 11×10 ms: Δavg ≈ +100 ms with the deterministic part visible in min; IOU single-hop min Δ96 ≈ 2×50) [measured].

---

## 6. Cross-cutting methodology findings

1. **Host CPU power-state sensitivity (RTT up to ~2×).** With an idle host, forwarded packets are slower than with a loaded host — reproducibly in both directions.
   - QEMU: full-chain RTT **10.2–11.0 ms idle ↔ 5.2–6.7 ms loaded**; adding 6 burn loops to the idle host snapped it back to 6.57 ms [measured].
   - IOU: **4.8–5.0 ms idle ↔ 2.2–2.3 ms loaded**, bidirectional, with only 3 busy cores on a 24-core host sufficient to suppress the effect [measured].
   - Explanation [inferred]: deep C-states / frequency scaling make each forwarding wake-up cost ~0.2–0.5 ms extra.
   - Consequence: RTT-class measurements must be taken under controlled load (a few `yes > /dev/null` burners) or the host state must be recorded. Cross-session absolute RTT values are indicative only.
2. **rp_filter × ECMP artifact (QEMU field).** Pinging a transit interface IP can show 100 % loss while the network is perfectly healthy: the reply's ECMP hash takes the "wrong" parallel leg and a strict `rp_filter=1` on the upstream node silently drops it. Proven by A/B (rp_filter 0 → pass, 1 → fail) and by `/proc/net/snmp` counters showing requests arriving and replies leaving [measured]. Verify connectivity via loopbacks or host E2E, not transit-interface pings.
3. **Sample sizes matter.** Packet-loss filters need n ≥ 200: duplicate[20] measured +62 % at n=100 vs +45 % at n=200 (theory +44 %). frequency_drop similarly needs a quiet link (see §4.3).
4. **Tooling adjustments for the current build.** `delay` requires 2 parameters — update automation (`[x]` → `[x, 0]`). Long pings still belong on local console TCP; consoles replay their scroll buffer (take the last summary); the Dynamips session additionally required telnet option negotiation (reply WONT/DONT to `IAC DO TERMINAL-TYPE`, or the console stays silent); Cisco IOS 15.2(4)M11 rejects `show ip ospf neighbor brief` and `show ip route <ip>/32` (use `<ip> <mask>`).

---

## 7. Node stop/start (lifecycle)

Passed on all four platforms with zero link rebuilds: Docker FRR-2 (3 links), QEMU FRR-qemu-2 (3 links), IOU R9, Dynamips R9 — in each case the node came back via its persisted config (NVRAM / frr.conf), OSPF returned to Full (Dynamips: after a ~40 s convergence window with transient loss), and host-to-host traffic returned to 0 % loss. The earlier (2026-09-30) "docker stop/start orphans the link L2" issue did not reproduce (relay path has no bridge-port orphaning) [measured].

---

## 8. Verdict — what kernel datapath bought you, per platform

| Platform | Filter value | Performance value | Practical impact of its removal |
|---|---|---|---|
| Docker | 8 kernel-only filters | **High** — the only platform in the fast-path class | **Severe**: RTT ×5–6, throughput ÷14–25, loss of multi-stream aggregation |
| QEMU | 8 kernel-only filters | Medium — throughput halved; virtio leverage ×5.1→×2.2, multi-stream unstable | **Moderate**: latency fine, capacity and virtio story degrade |
| IOU | 8 kernel-only filters (Ethernet links also fell back to the relay's 5) | None measurable | **Filter capability only** |
| Dynamips | 8 kernel-only filters (same fallback) | None measurable | **Filter capability only** |

**Bottom line.** On the current build every link is a userspace relay: treat 5 filters as the supported set, expect the relay's ~0.1–0.2 ms/segment and ~1.3 Gbps/source envelope to show only on platforms whose native forwarding beats it (Docker strongly; QEMU for throughput), and keep µs-class expectations for the platforms where the emulator itself is the bottleneck (IOU, Dynamips). The kernel datapath's remaining unique value on today's build is the 8 advanced filters.

---

## 9. Reproduction (menu used in all four fields)

```bash
# Platform
link_get(<link>)                      # no kernel_datapath key
link_available_filters(<link>)        # the 5 legacy types
link_update(<link>, filters={"rate": ["512kbit"]})   # 409 Unknown filter type (no guidance)
link_update(<link>, filters={"delay": [50]})         # 409 expects 2 parameter(s)

# Filters (n >= 200 for loss-type samples; quiet link for frequency_drop)
{"delay": [50, 0]}  {"packet_loss": [10]}  {"frequency_drop": [3]}
{"corrupt": [30]}   {"bpf": ["icmp[icmptype]==8"]}   filters={}   # clear + re-baseline

# Performance: iperf3 single/multi; RTT under controlled host load; delay curves on parallel legs
# Lifecycle: node_stop -> node_start on an interior node; verify NVRAM recovery, OSPF Full, E2E 0%
```

---

## 10. References (per-field reports, in Chinese)

| Field | Relay-only comparison report | Kernel-datapath baseline |
|---|---|---|
| Docker | `Kernel-DataPath-Docker-FRRDocker-无Kernel-对照实测.md` | `Packet-Filter-Test-方案与实施记录.md` + project README (2026-09-30) |
| QEMU | `Kernel-DataPath-Qemu-FRRqemu-无Kernel-对照实测.md` | `QEMU-Kernel-DataPath-Test-方案与实施记录.md` §10/§11 |
| IOU | `Kernel-DataPath-Iou-CiscoIOU-无Kernel-对照实测.md` | `IOU-Kernel-DataPath-Test-方案与实施记录.md` §5/§6/§10 |
| Dynamips | `Kernel-DataPath-Dynamips-Cisco7200-无Kernel-对照实测.md` | `Dynamips-Kernel-DataPath-Test-方案与实施记录.md` §1–§10 |

*All relay-only figures in this summary were measured via the GNS3 MCP API on server `3.1.0.dev7+38cc7cc0a` during the 2026-10-04/05 campaign; kernel-build figures are quoted from the baseline records above. Statements marked "inferred" are hypotheses consistent with the measurements, not independently proven mechanisms. Chinese edition: `Kernel-DataPath-无Kernel-四场对照汇总.md`.*
