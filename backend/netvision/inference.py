"""L2 link inference from MAC tables + ARP + LLDP/CDP (issue #48, step 2).

``infer_l2_links`` is a PURE function: no DB access, no I/O, inputs are not
mutated, output order is deterministic (sorted). The caller loads the data.

Inputs (plain dicts, as stored in MongoDB):
  devices       [{id, ip, name?, device_type?, mac?}]
  fdb_docs      [{device_id, ports: {port: [mac, ...]}}]          (device_fdb)
  lldp_links    [{source_id, target_id, source_port?, target_port?}] (links)
  arp_entries   [{ip, mac, source_id?}]                            (arp_entries)
  opts          {unmanaged_min_macs: 2, virt_host_max_ips: 4}

Rules (issue #48):
  0. VRRP / HSRP virtual MACs are dropped first and reported in ``excluded``.
  1. A port with an LLDP/CDP neighbor is an uplink.
  2. A port where another managed switch's MAC is seen is an uplink.
     "Managed switch" = a device that has a MAC table (an fdb doc). A device's
     MACs = its ``mac`` field + ARP rows whose IP is the device IP.
     Switch-to-switch links:
       - mutual: A's port sees B and B's port sees A -> link with both ports;
       - one-way: only A sees B -> link from A's port; B's port is the B port
         that sees the most MACs from A's side (or unknown);
       - the local port is the port seeing the peer with the FEWEST MACs;
       - a candidate is dropped when a third switch X seen on the same port is
         between them (X sees the peer on a port that does not lead back), or
         when both sides see the same third switch (shared segment).
  3. Every other MAC is placed on the non-uplink port where it is seen. Seen on
     several non-uplink ports -> the port with the fewest MACs, then switch id,
     then port name; the choice is reported in ``ambiguities``.
  4. A port with >= unmanaged_min_macs placed MACs is an unmanaged segment: its
     endpoints carry ``segment_id`` and get no direct link.
  5. A MAC with more than virt_host_max_ips IPs is flagged
     ``virtualization_host`` (kept, not excluded).
"""
import ipaddress
from collections import defaultdict
from typing import Optional

from netvision.helpers import _is_placeholder, _normalize_ip, _normalize_mac, _valid_ip

DEFAULT_OPTS = {"unmanaged_min_macs": 2, "virt_host_max_ips": 4}


def virtual_mac_kind(mac: str) -> Optional[str]:
    """'vrrp' / 'hsrp' for first-hop-redundancy virtual MACs, else None. Expects a normalized MAC."""
    if mac.startswith(("00:00:5e:00:01:", "00:00:5e:00:02:")):  # VRRP IPv4 / IPv6
        return "vrrp"
    if mac.startswith(("00:00:0c:07:ac:", "00:00:0c:9f:f")):    # HSRP v1 / v2
        return "hsrp"
    return None


def _ip_key(ip: str):
    a = ipaddress.ip_address(ip)
    return (a.version, int(a))


def _canon_ip(ip) -> Optional[str]:
    if not isinstance(ip, str) or not _valid_ip(ip) or _is_placeholder(ip):
        return None
    return _normalize_ip(ip)


def _port(p) -> Optional[str]:
    p = str(p).strip() if p is not None else ""
    return p or None


def infer_l2_links(devices, fdb_docs, lldp_links, arp_entries, opts=None) -> dict:
    o = {**DEFAULT_OPTS, **(opts or {})}
    min_macs = max(2, int(o["unmanaged_min_macs"]))
    virt_max = int(o["virt_host_max_ips"])
    stats = defaultdict(int)
    ambiguities = []

    dev_by_id = {d["id"]: d for d in devices if d.get("id")}
    dev_by_ip = {}
    for did in sorted(dev_by_id):
        ip = _canon_ip(dev_by_id[did].get("ip"))
        if ip:
            dev_by_ip.setdefault(ip, did)

    # ---- ARP: MAC -> IPs ----
    mac_ips = defaultdict(set)
    for e in arp_entries:
        mac, ip = _normalize_mac(e.get("mac")), _canon_ip(e.get("ip"))
        if not mac or not ip:
            stats["arp_rows_invalid"] += 1
            continue
        mac_ips[mac].add(ip)

    # ---- MAC table: (switch, port) -> MACs; drop virtual MACs ----
    excluded = {}
    ports = defaultdict(lambda: defaultdict(set))  # switch -> port -> {mac}
    for doc in fdb_docs:
        sw = doc.get("device_id")
        if sw not in dev_by_id:
            continue
        ports.setdefault(sw, defaultdict(set))  # an empty table still makes it a managed switch
        for raw_port, macs in (doc.get("ports") or {}).items():
            p = _port(raw_port)
            if not p:
                continue
            for raw in macs or []:
                mac = _normalize_mac(raw)
                if not mac:
                    stats["fdb_macs_invalid"] += 1
                    continue
                kind = virtual_mac_kind(mac)
                if kind:
                    ex = excluded.setdefault(mac, {"mac": mac, "reason": kind, "seen_on": set()})
                    ex["seen_on"].add((sw, p))
                    continue
                ports[sw][p].add(mac)
    for mac in mac_ips:
        kind = virtual_mac_kind(mac)
        if kind:
            excluded.setdefault(mac, {"mac": mac, "reason": kind, "seen_on": set()})
    switches = set(ports)

    # ---- MAC -> owning device: explicit device.mac wins, then a unique ARP IP match ----
    mac_owner = {}
    explicit = defaultdict(set)
    for did, d in dev_by_id.items():
        m = _normalize_mac(d.get("mac"))
        if m:
            explicit[m].add(did)
    for mac in sorted(set(explicit) | set(mac_ips)):
        if mac in excluded:
            continue
        cands = explicit.get(mac) or {dev_by_ip[ip] for ip in mac_ips.get(mac, ()) if ip in dev_by_ip}
        if len(cands) == 1:
            mac_owner[mac] = next(iter(cands))
        elif len(cands) > 1:
            ambiguities.append({"type": "mac_shared_by_devices", "mac": mac, "device_ids": sorted(cands),
                                "rule": "MAC not attributed to any device"})
    switch_of_mac = {m: d for m, d in mac_owner.items() if d in switches}
    own_macs = defaultdict(set)
    for m, d in switch_of_mac.items():
        own_macs[d].add(m)
    for sw in switches:  # a switch's own MAC in its own table is not a neighbor
        for p in ports[sw]:
            ports[sw][p] -= own_macs[sw]

    def mac_count(sw, p) -> int:
        return len(ports[sw].get(p, ()))

    # D(s, p): other managed switches whose MAC is seen on (s, p)
    seen_sw = {(sw, p): {switch_of_mac[m] for m in macs if m in switch_of_mac and switch_of_mac[m] != sw}
               for sw in switches for p, macs in ports[sw].items()}

    # ---- rule 1 + 2: uplinks ----
    uplinks = defaultdict(lambda: {"reasons": set(), "neighbors": set()})
    lldp_pairs = set()
    lldp_at = defaultdict(set)  # (switch, port) -> LLDP neighbor ids
    for lk in lldp_links:
        a, b = lk.get("source_id"), lk.get("target_id")
        if not a or not b or a == b:
            continue
        lldp_pairs.add(frozenset((a, b)))
        for sw, p, nb in ((a, _port(lk.get("source_port")), b), (b, _port(lk.get("target_port")), a)):
            if p:
                lldp_at[(sw, p)].add(nb)
                if sw in switches:
                    uplinks[(sw, p)]["reasons"].add("lldp")
                    uplinks[(sw, p)]["neighbors"].add(nb)
    for key, peers in seen_sw.items():
        if peers:
            uplinks[key]["reasons"].add("switch_mac")
            uplinks[key]["neighbors"].update(peers)

    # ---- rule 2: switch-to-switch links ----
    def port_toward(a, b) -> Optional[str]:
        cands = [p for p in ports[a] if b in seen_sw[(a, p)]]
        return min(cands, key=lambda p: (mac_count(a, p), p)) if cands else None

    def shadowed(a, pa, b) -> Optional[str]:
        """A switch X seen on (a, pa) that sits between a and b, if any."""
        for x in sorted(seen_sw[(a, pa)] - {b}):
            for q in ports[x]:
                if b in seen_sw[(x, q)] and a not in seen_sw[(x, q)]:
                    return x
        return None

    toward = {}
    for a in sorted(switches):
        for b in sorted(switches - {a}):
            p = port_toward(a, b)
            if p:
                toward[(a, b)] = p

    links = []
    done = set()
    for (a, b), pa in sorted(toward.items()):
        pair = frozenset((a, b))
        if pair in done:
            continue
        if pair in lldp_pairs:
            done.add(pair)
            stats["switch_pairs_already_lldp"] += 1
            continue
        if shadowed(a, pa, b):
            continue
        pb = toward.get((b, a))
        if pb is not None:
            if shadowed(b, pb, a):
                continue
            shared = seen_sw[(a, pa)] & seen_sw[(b, pb)]
            if shared:
                ambiguities.append({"type": "switches_share_segment", "switch_ids": sorted(pair),
                                    "also_seen_on_both_sides": sorted(shared),
                                    "rule": "no direct link inferred"})
                done.add(pair)
                continue
            src, sp, dst, dp = (a, pa, b, pb) if a < b else (b, pb, a, pa)
            evidence = {"rule": "mutual_switch_mac", "source_port_mac_count": mac_count(src, sp),
                        "target_port_mac_count": mac_count(dst, dp)}
        else:
            # one-way: only a sees b. b's port toward a = the b port sharing most MACs with a's side
            a_side = set(own_macs[a])
            for p, macs in ports[a].items():
                if p != pa:
                    a_side |= macs
            scored = [(len(ports[b][q] & a_side), q) for q in ports[b]]
            scored = [(n, q) for n, q in scored if n > 0]
            pb = None
            if scored:
                pb = min(scored, key=lambda t: (-t[0], mac_count(b, t[1]), t[1]))[1]
                uplinks[(b, pb)]["reasons"].add("peer_port_inferred")
                uplinks[(b, pb)]["neighbors"].add(a)
            src, sp, dst, dp = a, pa, b, pb
            evidence = {"rule": "one_way_switch_mac", "source_port_mac_count": mac_count(a, pa),
                        "target_port_shared_macs": max((n for n, q in scored if q == pb), default=0)}
        done.add(pair)
        evidence["peer_macs"] = sorted(own_macs[dst])
        links.append({"id": f"inf-{src}-{dst}", "kind": "inferred", "source": src, "target": dst,
                      "source_port": sp, "target_port": dp, "evidence": evidence})

    by_port = defaultdict(list)
    for lk in links:
        by_port[(lk["source"], lk["source_port"])].append(lk["target"])
        if lk["target_port"]:
            by_port[(lk["target"], lk["target_port"])].append(lk["source"])
    for (sw, p), peers in sorted(by_port.items()):
        if len(peers) > 1:
            ambiguities.append({"type": "multiple_switches_behind_port", "switch_id": sw, "port": p,
                                "switch_ids": sorted(peers), "rule": "unmanaged switch in between?"})

    # ---- rule 3: endpoints ----
    uplink_keys = set(uplinks)
    seen_at = defaultdict(set)
    for sw in switches:
        for p, macs in ports[sw].items():
            for m in macs:
                if m not in switch_of_mac:
                    seen_at[m].add((sw, p))

    endpoints = []
    placed = defaultdict(list)  # (switch, port) -> endpoints placed there by FDB
    for mac in sorted(seen_at):
        seen = sorted(seen_at[mac])
        access = [k for k in seen if k not in uplink_keys]
        owner = mac_owner.get(mac)
        ips = sorted(mac_ips.get(mac, ()), key=_ip_key)
        owner_ip = _canon_ip(dev_by_id[owner].get("ip")) if owner else None
        ep = {"mac": mac, "ip": owner_ip if owner_ip in ips else (ips[0] if ips else None), "ips": ips,
              "device_id": owner, "device_name": dev_by_id[owner].get("name") if owner else None,
              "switch_id": None, "port": None, "located": False, "via": None, "segment_id": None,
              "virtualization_host": len(ips) > virt_max,
              "seen_on": [{"switch_id": s, "port": p} for s, p in seen]}
        if access:
            chosen = min(access, key=lambda k: (mac_count(*k), k[0], k[1]))
            if len(access) > 1:
                ambiguities.append({
                    "type": "mac_on_multiple_access_ports", "mac": mac,
                    "candidates": [{"switch_id": s, "port": p, "mac_count": mac_count(s, p)} for s, p in access],
                    "chosen": {"switch_id": chosen[0], "port": chosen[1]},
                    "rule": "fewest MACs, then switch id, then port"})
            ep.update(switch_id=chosen[0], port=chosen[1], located=True, via="fdb")
            placed[chosen].append(ep)
        else:
            via_lldp = [k for k in seen if owner and owner in lldp_at.get(k, ())]
            if via_lldp:
                ep.update(switch_id=via_lldp[0][0], port=via_lldp[0][1], located=True, via="lldp")
        endpoints.append(ep)

    # ---- rule 4: unmanaged segments vs direct links ----
    segments = []
    for (sw, p), eps in sorted(placed.items()):
        if len(eps) >= min_macs:
            seg_id = f"seg-{sw}-{p}"
            for ep in eps:
                ep["segment_id"] = seg_id
            segments.append({"id": seg_id, "switch_id": sw, "port": p, "mac_count": len(eps),
                             "macs": [ep["mac"] for ep in eps],
                             "device_ids": sorted({ep["device_id"] for ep in eps if ep["device_id"]})})
            continue
        ep = eps[0]
        did = ep["device_id"]
        if not did or did == sw or frozenset((sw, did)) in lldp_pairs:
            continue
        links.append({"id": f"inf-{sw}-{did}", "kind": "inferred", "source": sw, "target": did,
                      "source_port": p, "target_port": None,
                      "evidence": {"rule": "access_port", "mac": ep["mac"], "ip": ep["ip"],
                                   "ip_from_arp": bool(ep["ips"]), "seen_on_ports": len(ep["seen_on"])}})

    stats.update(switches=len(switches), endpoints=len(endpoints),
                 endpoints_located=sum(1 for e in endpoints if e["located"]),
                 arp_macs=len(mac_ips), arp_only_macs=len(set(mac_ips) - set(seen_at) - set(switch_of_mac)
                                                          - set(excluded)))
    return {
        "endpoints": endpoints,
        "links": sorted(links, key=lambda lk: (lk["source"], lk["target"])),
        "uplinks": [{"switch_id": sw, "port": p, "reasons": sorted(u["reasons"]),
                     "neighbors": sorted(u["neighbors"]), "mac_count": mac_count(sw, p)}
                    for (sw, p), u in sorted(uplinks.items())],
        "excluded": [{"mac": ex["mac"], "reason": ex["reason"],
                      "seen_on": [{"switch_id": s, "port": p} for s, p in sorted(ex["seen_on"])],
                      "ips": sorted(mac_ips.get(ex["mac"], ()), key=_ip_key)}
                     for _, ex in sorted(excluded.items())],
        "segments": segments,
        "ambiguities": ambiguities,
        "stats": dict(stats),
    }
