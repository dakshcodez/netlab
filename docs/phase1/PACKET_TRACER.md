# Phase 1: Packet Tracer Lab

An HQ + branch office network with VLSM addressing, VLANs, DHCP, and the same "trap" idea
used on the Mininet testbed: a slow direct WAN link vs a fast two-hop path through a core
router. RIP picks the slow link (fewer hops), OSPF picks the fast path (lower cost).

Save the finished file as `docs/phase1/netlab.pkt` (commit it).

## Topology

```
   PC-Eng1  PC-Sales1  PC-Admin1                         PC-BR1  PC-BR2
       \        |        /                                  \     /
        [  HQ-SW (2960)  ]  VLAN 10/20/30                  [ BR-SW (2960) ]
                |  trunk Fa0/1 ↔ Gi0/0                           |  Fa0/1 ↔ Gi0/0
            [ HQ-R 2911 ] Se0/0/0 ════ 64 kbps serial ════ Se0/0/0 [ BR-R 2911 ]
                | Gi0/1                                           | Gi0/1
                └──────────── Gi0/0 [ Core-R 2911 ] Gi0/1 ────────┘
                                  1 Gbps            1 Gbps
```

Add an **HWIC-2T** module to HQ-R and BR-R (power off → drag module → power on) for the
serial ports. Use a DCE serial cable with the clock on HQ-R's side.

## Addressing plan (VLSM)

Generated with our planner, which allocates the largest subnets first so each block stays aligned:

```bash
python -m netlab.addressing.vlsm 172.16.0.0/23 HQ-Eng=100 HQ-Sales=50 Branch-LAN=30 HQ-Admin=20 HQ-BR=2 HQ-Core=2 Core-BR=2
```

| Subnet     | Hosts | Usable | Network         | Mask            | Gateway / first | Last         | Broadcast    |
|------------|-------|--------|-----------------|-----------------|-----------------|--------------|--------------|
| HQ-Eng (VLAN 10)   | 100   | 126    | 172.16.0.0/25   | 255.255.255.128 | 172.16.0.1   | 172.16.0.126 | 172.16.0.127 |
| HQ-Sales (VLAN 20) | 50    | 62     | 172.16.0.128/26 | 255.255.255.192 | 172.16.0.129 | 172.16.0.190 | 172.16.0.191 |
| Branch-LAN | 30    | 30     | 172.16.0.192/27 | 255.255.255.224 | 172.16.0.193 | 172.16.0.222 | 172.16.0.223 |
| HQ-Admin (VLAN 30) | 20    | 30     | 172.16.0.224/27 | 255.255.255.224 | 172.16.0.225 | 172.16.0.254 | 172.16.0.255 |
| HQ-BR (serial)     | 2     | 2      | 172.16.1.0/30   | 255.255.255.252 | HQ .1, BR .2 |              | 172.16.1.3   |
| HQ-Core    | 2     | 2      | 172.16.1.4/30   | 255.255.255.252 | HQ .5, Core .6 |            | 172.16.1.7   |
| Core-BR    | 2     | 2      | 172.16.1.8/30   | 255.255.255.252 | Core .9, BR .10 |           | 172.16.1.11  |

A /23 is the smallest block that fits: 128 + 64 + 32 + 32 + 3×4 = 268 addresses > 256.

## Step 1: switch VLANs (HQ-SW)

```
enable
conf t
vlan 10
 name ENG
vlan 20
 name SALES
vlan 30
 name ADMIN
interface fa0/2
 switchport mode access
 switchport access vlan 10
interface fa0/3
 switchport mode access
 switchport access vlan 20
interface fa0/4
 switchport mode access
 switchport access vlan 30
interface fa0/1
 switchport mode trunk
end
```

## Step 2: router interfaces

**HQ-R** (router-on-a-stick for the VLANs):
```
conf t
interface gi0/0
 no shutdown
interface gi0/0.10
 encapsulation dot1Q 10
 ip address 172.16.0.1 255.255.255.128
interface gi0/0.20
 encapsulation dot1Q 20
 ip address 172.16.0.129 255.255.255.192
interface gi0/0.30
 encapsulation dot1Q 30
 ip address 172.16.0.225 255.255.255.224
interface gi0/1
 ip address 172.16.1.5 255.255.255.252
 no shutdown
interface se0/0/0
 ip address 172.16.1.1 255.255.255.252
 clock rate 64000
 bandwidth 64
 no shutdown
end
```

**Core-R:**
```
conf t
interface gi0/0
 ip address 172.16.1.6 255.255.255.252
 no shutdown
interface gi0/1
 ip address 172.16.1.9 255.255.255.252
 no shutdown
end
```

**BR-R:**
```
conf t
interface gi0/0
 ip address 172.16.0.193 255.255.255.224
 no shutdown
interface gi0/1
 ip address 172.16.1.10 255.255.255.252
 no shutdown
interface se0/0/0
 ip address 172.16.1.2 255.255.255.252
 bandwidth 64
 no shutdown
end
```

## Step 3: DHCP

**HQ-R:**
```
conf t
ip dhcp excluded-address 172.16.0.1
ip dhcp excluded-address 172.16.0.129
ip dhcp excluded-address 172.16.0.225
ip dhcp pool ENG
 network 172.16.0.0 255.255.255.128
 default-router 172.16.0.1
ip dhcp pool SALES
 network 172.16.0.128 255.255.255.192
 default-router 172.16.0.129
ip dhcp pool ADMIN
 network 172.16.0.224 255.255.255.224
 default-router 172.16.0.225
end
```

**BR-R:**
```
conf t
ip dhcp excluded-address 172.16.0.193
ip dhcp pool BRANCH
 network 172.16.0.192 255.255.255.224
 default-router 172.16.0.193
end
```

Set every PC to DHCP (Desktop → IP Configuration) and confirm it gets an address from the right pool.

## Step 4a: static routing (baseline)

Before using a routing protocol, configure static routes on all three routers so every LAN
is reachable. Then remove them (`no ip route ...`) before Step 4b. Point out in the report
how many routes you had to type by hand and what happens when a link fails.

## Step 4b: RIP v2

On **all three routers**:
```
conf t
router rip
 version 2
 no auto-summary
 network 172.16.0.0
 passive-interface gi0/0
end
```
(On Core-R leave out `passive-interface`.)

Verify on HQ-R:
```
show ip route rip        ! Branch-LAN 172.16.0.192/27 via 172.16.1.2 (Serial), [120/1]
show ip protocols
```
From PC-Eng1: `tracert 172.16.0.194` → goes **HQ-R → BR-R over the 64 kbps serial link**.

## Step 4c: OSPF

Remove RIP (`no router rip`) and configure on **all three routers**:
```
conf t
router ospf 1
 auto-cost reference-bandwidth 1000
 network 172.16.0.0 0.0.1.255 area 0
 passive-interface gi0/0
end
```
(On Core-R leave out `passive-interface`.) The reference bandwidth of 1000 Mbit/s matches
the testbed: a GigabitEthernet link costs 1 and the 64 kbps serial link costs 15625.

Verify on HQ-R:
```
show ip route ospf       ! Branch-LAN via 172.16.1.6 (Core-R), cost 3
show ip ospf neighbor
show ip ospf interface brief
```
`tracert` from PC-Eng1 now goes **HQ-R → Core-R → BR-R**.

## Step 5: observe convergence

1. Switch to **Simulation mode** and set the event filter to RIP / OSPF only.
2. With RIP running, shut the serial link (`interface se0/0/0`, `shutdown` on HQ-R) and watch
   the triggered updates. Repeat with OSPF and watch the LSA flood.
3. Note `show ip route` before and after on HQ-R.

The Packet Tracer timing isn't realistic. The real convergence numbers come from
`experiments/phase1_convergence.py` on the testbed. Packet Tracer is for showing the
messages each protocol sends.

## Screenshots for the report
- Topology with labels
- `show ip route` on HQ-R under RIP and under OSPF (the difference is the key point)
- `tracert` from PC-Eng1 under both protocols
- `show ip ospf neighbor`
- A simulation-mode capture of a RIP update and an OSPF LSU
