# [Postmortem] IPv6 NDP blackhole on GNS3 kernel-datapath links — root cause: host ebtables bridge-filter FORWARD drops, unscoped

> Status: **RESOLVED 2026-10-30, local host misconfiguration** — not a gns3-server/ubridge
> bug; no upstream issue will be filed. This document supersedes the earlier issue draft
> (`home-server-v6-NDP-multicast-issue-EN.md`, TAP-filter hypothesis). The hypothesis
> journey is kept below because the *disconfirming* evidence is the interesting part.
>
> 中文一句话：宿主 ebtables（iptables-nft bridge family）FORWARD 链 drop NDP NA/RS/RA
> 与 DHCP，且不带接口匹配——所有桥（含 GNS3 每链一个的 `gns3*` 桥）的端口间转发
> 全部被拦；NS 放行、NA 全丢 ⇒ ND 永远解析不完。收窄到 `--logical-out br-sw1`
> 后双场（IOU + FRR docker）复测全绿。

## Environment

- Host: home_server, Debian 12, kernel 6.1.0-42-amd64, gns3server 3.1.0.dev8 (controller
  at 192.168.1.3:3080, single local compute). Also runs the FlowNet lab stack in docker.
- Physical LAN isolation design (intentional, by the owner): clients behind `br-sw1`
  (bridge of enp1s0/enp2s0/eno1/enp4s0) may only obtain IPv6 addresses / default routes
  from this host itself. Enforced with an ebtables ruleset persisted at
  `/etc/ebtables/rules.v4` and loaded by `pre-up ebtables-restore < /etc/ebtables/rules.v4`
  on `br-sw1` in `/etc/network/interfaces`.
- GNS3 labs: kernel-datapath Ethernet links ⇒ one Linux bridge per link (`gns3*`),
  with TAP anchors (`gi*`) for IOU and veth anchors (`gv*`) for docker nodes.
  These bridges have **no physical port members** — lab traffic has no path to the LAN.

## Root cause

The live bridge-family filter (installed via ebtables-nft; `nft list ruleset` shows the
table flagged "managed by iptables-nft") contained, in `chain FORWARD`:

```
ether type ip  ip daddr 255.255.255.255 udp sport 68 dport 67  counter 56386 drop  # DHCPv4 bcast
ether type ip6 icmpv6 type 133  counter   351 drop   # Router Solicitation
ether type ip6 icmpv6 type 134  counter  1499 drop   # Router Advertisement
ether type ip  udp sport 68 dport 67      counter     0 drop
ether type ip6 udp sport 546 dport 547    counter    27 drop   # DHCPv6
ether type ip6 icmpv6 type 136  counter 21245 drop   # ← Neighbor Advertisement
```

**None of these rules matched on an interface.** The bridge family FORWARD hook sees
frames forwarded between ports of *every* bridge in the netns — including the GNS3
per-link bridges. INPUT/OUTPUT chain rules were properly scoped to `enp1s0`; only
FORWARD was global.

Consequences:

- **NS (type 135) was not in the drop list** — neighbor solicitations always reached the
  peer (which learned the sender's MAC from the SLLAO and happily replied…).
- **NA (type 136) was dropped in both directions** — the reply never completed the
  handshake. Sender stays INCOMPLETE / `Address unreachable`; peer's cached entry loops
  STALE→DELAY→PROBE forever.
- IPv4 unicast and ARP were never in the list — hence "IPv4 unaffected", BGP-over-v4
  14/14 sessions, etc.
- The drop counters are the confession: 21,245 NAs and 56k DHCP broadcasts discarded.

## Why the earlier "signals" pointed elsewhere

Every observation that steered us to multicast-group state and the TAP filter is
reproducible from "NS passes, NA dies" + ordinary kernel neighbor-state dynamics:

| Observation | Real mechanism |
|---|---|
| v4 perfect, v6 dead | Rules drop NDP/DHCP only; ARP and v4 unicast pass |
| Per-link / per-group "lottery" (LL groups healthy, `ff02::1:ff00:N` black) | Entry states diverged by traffic history: any received NS with a given source re-creates a STALE entry for that source (SLLAO). LL-sourced NS flows (PROBEs, pings) kept LL entries alive; a fresh GUA needs a real NA once — which never comes |
| Minutes-long blackout, then sudden permanent recovery | The rule is constant; the *symptom* is stateful. Sustained pings both ways → each side's multicast NS keeps re-teaching the peer STALE → traffic flows in bursts → self-sustaining STALE loop = "recovered for good" |
| One-directional NDP on a link | Each direction's resolution state is independent (one side holds a STALE entry, the other is INCOMPLETE) |
| "A static rule would drop consistently, so it can't be a rule" | Wrong in an instructive way: the rule *did* drop consistently (every NA, both directions, always). The visible outcome varied because endpoint neighbor state (STALE windows) masks a constant drop |
| BGP sessions stuck OpenSent with half-open TCP | Connection grabbed during a STALE window, OPEN retransmits lost when the window closed — a flash window, not a flash of connectivity |

The last row of the earlier argument is the key methodological lesson: **a constant L2
drop + stateful L3 caches produces time-varying symptoms**. Don't rule out static causes
because the symptom oscillates.

## The TAP-filter hypothesis, and how it fell

Earlier draft (kept for the record): frames bridge→TAP pass `tun_net_xmit()` →
`check_filter()`; the multicast hash bitmap is registered from userspace via ioctl; a
racy registration blackholes exactly that solicited-node group. This fit the per-group
evidence perfectly and had kernel-source backing.

**Falsifier**: after scoping the ebtables rules, a *fresh* IOU node start (the scenario
that "always" reproduced the blackhole) resolved NDP on the first ping — 10/10, 1 ms,
neighbor table REACH on first entry. With the constant NA drop removed, nothing
intermittent remains. The per-group/time-varying evidence that motivated the hypothesis
is fully generated by neighbor-cache dynamics (table above).

Kept from that investigation: the `ip -s link show <tap>` tx_dropped + `tcpdump -i <tap>`
triangulation is a good tool if a *real* TAP filter issue is ever suspected. It simply
wasn't the cause here.

## Evidence chain that actually closed it

1. **Two minimal labs** (2 nodes + 1 link each): `IPv6-ND-IOU-Test` (IOU) and
   `IPv6-ND-FRR-Test` (FRR docker, appliance `gns3/frr:latest`, FRR 10.3). Same signature
   in both ⇒ platform-level, node-type-independent.
2. **Link captures**: NS visible on the wire (and peer reacted — proving delivery);
   NA from the responder visible at bridge ingress but the requester's neighbor entry
   never advanced ⇒ death between bridge ingress and egress port.
   FRR side: kernel ping stats 478 sent / 11 received / RTT up to 2048 ms — near-total
   loss with rare STALE-window successes.
3. **Healthy-baseline diff** against a known-good host running the same gns3-server
   datapath layout (`gns3*` bridges + `gv*`/`gi*` anchors): br_netfilter sysctls,
   conntrack occupancy, tc qdiscs, bridge port flags — all clean, which *narrowed* the
   search to the one thing unread without root: the nft ruleset.
4. **`sudo nft list ruleset`** — the bridge filter table with live drop counters (above).
5. **Fix + A/B retest** — see matrix below.

## Fix

`/etc/ebtables/rules.v4`: every FORWARD rule scoped with `--logical-out br-sw1`
(`meta obrname "br-sw1"` in nft terms). The design intent (clients on br-sw1 only get
v6 config from this host) is preserved exactly — those frames still cross br-sw1 ports
and still die; gns3* bridges never carry them because they have no physical members.

```bash
sudo install -m 755 rules.v4 /etc/ebtables/rules.v4
sudo ebtables-restore < /etc/ebtables/rules.v4      # atomic replace; clears the old global rules
sudo nft list ruleset | sed -n '/table bridge filter/,/^}/p'   # every FORWARD line must show meta obrname "br-sw1"
```

Persistence: the `pre-up ebtables-restore` on br-sw1 reloads the file at every boot.

**Repo drift lesson**: the canonical file on the server (ebtables-save of 2024-05-03,
including the NA rule) was never committed back to the config repo, which still held the
2024-04-21 version missing four rules. When auditing, diff *live* + *server file* +
*repo* — in that order of authority.

## Verification matrix (post-fix)

| Lab | Test | Result |
|---|---|---|
| IOU (fresh start after host reboot) | first `ping 2001:1::2` | **10/10, RTT 1/1/5 ms, neighbor REACH on first entry** |
| FRR docker | R1→R2 v6 / v4 | 5/5 @ 0.12 ms, `REACHABLE` / 5/5 @ 0.12 ms, ARP `REACHABLE` |
| FRR docker | R2→R1 v6 / v4 | 5/5 @ 0.06 ms / 5/5 @ 0.07 ms |
| br-sw1 isolation still working | scoped DHCP-drop counter | incrementing on br-sw1 traffic only |

An earlier "v4 ARP INCOMPLETE" reading in the FRR lab turned out to be an unapplied
interface config (pushed while the console was flooded by a runaway ping), not a rule
effect — the ruleset contains no ARP matches.

## Obsolete guidance from the blackhole era

- Interface-flap + sustained-ping "recovery recipe" — no longer needed; NDP is instant.
- eBGP-over-IPv6 link-local neighbors as a workaround — no longer necessary (harmless
  if kept).
- `clear bgp` for OpenSent stand-offs — orthogonal BGP collision handling, still valid.

## Reproduction / canary rig

The two 2-node labs are kept on home_server as IPv6-ND canaries: after any host or
gns3-server change, start the pair and first-ping must be 100%. A single delayed ping
means something started dropping NA again — check
`sudo nft list ruleset | sed -n '/table bridge filter/,/^}/p'` counters first.
