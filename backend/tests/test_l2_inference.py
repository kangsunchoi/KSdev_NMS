"""Scenario tests for the pure L2 inference function (issue #48, step 2).

All data is hand-made; no DB or server involved.
"""
import copy
import random

import pytest

from netvision.helpers import _normalize_mac
from netvision.inference import infer_l2_links, virtual_mac_kind


# ---------------- MAC normalization ---------------- #
@pytest.mark.parametrize("raw", [
    "aa:bb:cc:dd:ee:ff", "AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", "AA-BB-CC-DD-EE-FF",
    "aabb.ccdd.eeff", "AABB.CCDD.EEFF", "aabbccddeeff", "AaBbCcDdEeFf", " aa:bb:cc:dd:ee:ff ",
    "aa bb cc dd ee ff",
])
def test_normalize_mac_valid(raw):
    assert _normalize_mac(raw) == "aa:bb:cc:dd:ee:ff"


def test_normalize_mac_pads_short_groups():
    assert _normalize_mac("0:1b:2:3:4:a") == "00:1b:02:03:04:0a"


@pytest.mark.parametrize("raw", [
    None, 5, "", "aa:bb:cc:dd:ee", "aa:bb:cc:dd:ee:ff:00", "gg:bb:cc:dd:ee:ff", "aa:bb-cc:dd:ee:ff",
    "aabb.ccdd.eef", "aabbccddeef", "aabbccddeeff0", "aaa:bb:cc:dd:ee:ff", "00:00:00:00:00:00",
    "ff:ff:ff:ff:ff:ff", "aa.bb.cc.dd.ee.ff",
])
def test_normalize_mac_invalid(raw):
    assert _normalize_mac(raw) is None


def test_virtual_mac_kind():
    assert virtual_mac_kind("00:00:5e:00:01:0a") == "vrrp"
    assert virtual_mac_kind("00:00:0c:07:ac:01") == "hsrp"
    assert virtual_mac_kind("00:00:0c:9f:f0:01") == "hsrp"
    assert virtual_mac_kind("00:00:0c:9f:e0:01") is None
    assert virtual_mac_kind("00:1b:1b:00:00:01") is None


# ---------------- scenario helpers ---------------- #
def mac(n: int) -> str:
    return f"02:00:00:00:{n // 256:02x}:{n % 256:02x}"


def dev(did, ip, device_type="switch", **kw):
    return {"id": did, "name": did.upper(), "ip": ip, "device_type": device_type, **kw}


def fdb(did, ports):
    return {"device_id": did, "ports": ports}


def arp(ip, m, source="gw"):
    return {"source_id": source, "ip": ip, "mac": m}


def run(devices, fdb_docs, links=(), arps=(), **opts):
    return infer_l2_links(list(devices), list(fdb_docs), list(links), list(arps), opts or None)


def ep(result, m):
    return next(e for e in result["endpoints"] if e["mac"] == m)


def link(result, a, b):
    hits = [lk for lk in result["links"] if {lk["source"], lk["target"]} == {a, b}]
    assert len(hits) <= 1
    return hits[0] if hits else None


def uplink_ports(result):
    return {(u["switch_id"], u["port"]) for u in result["uplinks"]}


SW1, SW2, SW3 = mac(1), mac(2), mac(3)
PLC, HMI, PC = mac(101), mac(102), mac(103)


# (a) LLDP between two switches; switch MACs unknown, so only LLDP marks the uplink
def test_a_lldp_uplink_plc_on_access_port():
    devices = [dev("sw1", "10.0.0.1"), dev("sw2", "10.0.0.2"),
               dev("plc", "10.0.0.11", "plc"), dev("hmi", "10.0.0.12", "hmi")]
    fdbs = [fdb("sw1", {"Gi1": [HMI], "Gi2": [PLC]}),
            fdb("sw2", {"Gi1": [PLC], "Gi5": [HMI]})]
    links = [{"source_id": "sw1", "target_id": "sw2", "source_port": "Gi1", "target_port": "Gi1"}]
    arps = [arp("10.0.0.11", PLC), arp("10.0.0.12", HMI)]
    r = run(devices, fdbs, links, arps)

    assert {("sw1", "Gi1"), ("sw2", "Gi1")} <= uplink_ports(r)
    assert all("lldp" in u["reasons"] for u in r["uplinks"])
    plc = ep(r, PLC)
    assert (plc["switch_id"], plc["port"], plc["device_id"], plc["ip"]) == ("sw1", "Gi2", "plc", "10.0.0.11")
    lk = link(r, "sw1", "plc")
    assert lk == {**lk, "kind": "inferred", "source": "sw1", "target": "plc", "source_port": "Gi2"}
    assert lk["evidence"]["rule"] == "access_port" and lk["evidence"]["mac"] == PLC
    assert link(r, "sw2", "plc") is None            # PLC MAC on the uplink is ignored
    assert link(r, "sw2", "hmi")["source_port"] == "Gi5"
    assert link(r, "sw1", "sw2") is None            # already an LLDP link: not re-inferred
    assert r["ambiguities"] == [] and r["segments"] == []


# (b) no LLDP: uplink detected from switch MACs seen in both directions
def test_b_mutual_switch_macs_without_lldp():
    devices = [dev("sw1", "10.0.0.1"), dev("sw2", "10.0.0.2"),
               dev("plc", "10.0.0.11", "plc"), dev("hmi", "10.0.0.12", "hmi")]
    fdbs = [fdb("sw1", {"Gi24": [SW2, HMI], "Gi3": [PLC]}),
            fdb("sw2", {"Gi1": [SW1, PLC], "Gi7": [HMI]})]
    arps = [arp("10.0.0.1", SW1), arp("10.0.0.2", SW2), arp("10.0.0.11", PLC), arp("10.0.0.12", HMI)]
    r = run(devices, fdbs, [], arps)

    assert uplink_ports(r) == {("sw1", "Gi24"), ("sw2", "Gi1")}
    lk = link(r, "sw1", "sw2")
    assert (lk["source"], lk["source_port"], lk["target"], lk["target_port"]) == ("sw1", "Gi24", "sw2", "Gi1")
    assert lk["kind"] == "inferred" and lk["evidence"]["rule"] == "mutual_switch_mac"
    assert (ep(r, PLC)["switch_id"], ep(r, PLC)["port"]) == ("sw1", "Gi3")
    assert (ep(r, HMI)["switch_id"], ep(r, HMI)["port"]) == ("sw2", "Gi7")
    assert link(r, "sw1", "plc") and link(r, "sw2", "hmi")
    assert not any(e["mac"] in (SW1, SW2) for e in r["endpoints"])  # switch MACs are not endpoints


def test_b_device_mac_field_counts_as_switch_mac():
    devices = [dev("sw1", "10.0.0.1", mac=SW1.upper()), dev("sw2", "10.0.0.2", mac=SW2.replace(":", "-")),
               dev("plc", "10.0.0.11", "plc")]
    fdbs = [fdb("sw1", {"Gi24": [SW2]}), fdb("sw2", {"Gi1": [SW1], "Gi2": [PLC]})]
    r = run(devices, fdbs, [], [arp("10.0.0.11", PLC)])
    assert link(r, "sw1", "sw2")["evidence"]["rule"] == "mutual_switch_mac"
    assert link(r, "sw2", "plc")["source_port"] == "Gi2"


def test_b_one_way_switch_mac_picks_peer_port():
    # collector behind sw1: sw1 learns sw2's MAC, sw2 never sees sw1's MAC
    col = mac(200)
    devices = [dev("sw1", "10.0.0.1"), dev("sw2", "10.0.0.2"), dev("plc", "10.0.0.11", "plc")]
    fdbs = [fdb("sw1", {"Gi24": [SW2, PLC], "Gi1": [col]}),
            fdb("sw2", {"Gi1": [col], "Gi2": [PLC]})]
    arps = [arp("10.0.0.2", SW2), arp("10.0.0.11", PLC), arp("10.0.0.250", col)]
    r = run(devices, fdbs, [], arps)
    lk = link(r, "sw1", "sw2")
    assert (lk["source"], lk["source_port"], lk["target"], lk["target_port"]) == ("sw1", "Gi24", "sw2", "Gi1")
    assert lk["evidence"]["rule"] == "one_way_switch_mac"
    assert ("sw2", "Gi1") in uplink_ports(r)
    # the collector MAC is placed at sw1 Gi1 only (sw2 Gi1 became an uplink)
    assert (ep(r, col)["switch_id"], ep(r, col)["port"]) == ("sw1", "Gi1")
    assert (ep(r, PLC)["switch_id"], ep(r, PLC)["port"]) == ("sw2", "Gi2")
    assert r["ambiguities"] == []


# (c) daisy chain sw1 - sw2 - sw3, endpoint behind the far switch
def test_c_daisy_chain_three_switches():
    devices = [dev("sw1", "10.0.0.1"), dev("sw2", "10.0.0.2"), dev("sw3", "10.0.0.3"),
               dev("plc", "10.0.0.11", "plc")]
    fdbs = [fdb("sw1", {"Gi24": [SW2, SW3, PLC]}),
            fdb("sw2", {"Gi1": [SW1], "Gi2": [SW3, PLC]}),
            fdb("sw3", {"Gi1": [SW1, SW2], "Gi8": [PLC]})]
    arps = [arp("10.0.0.1", SW1), arp("10.0.0.2", SW2), arp("10.0.0.3", SW3), arp("10.0.0.11", PLC)]
    r = run(devices, fdbs, [], arps)

    switch_links = {(lk["source"], lk["source_port"], lk["target"], lk["target_port"])
                    for lk in r["links"] if lk["target"] != "plc"}
    assert switch_links == {("sw1", "Gi24", "sw2", "Gi1"), ("sw2", "Gi2", "sw3", "Gi1")}
    assert link(r, "sw1", "sw3") is None
    assert (ep(r, PLC)["switch_id"], ep(r, PLC)["port"]) == ("sw3", "Gi8")
    assert link(r, "sw3", "plc")["source_port"] == "Gi8"
    assert link(r, "sw1", "plc") is None and link(r, "sw2", "plc") is None


def test_c_daisy_chain_one_way_visibility():
    # collector behind sw1: each switch is only seen by the switches toward the collector
    col = mac(200)
    devices = [dev("sw1", "10.0.0.1"), dev("sw2", "10.0.0.2"), dev("sw3", "10.0.0.3"),
               dev("plc", "10.0.0.11", "plc")]
    fdbs = [fdb("sw1", {"Gi1": [col], "Gi24": [SW2, SW3, PLC]}),
            fdb("sw2", {"Gi1": [col], "Gi2": [SW3, PLC]}),
            fdb("sw3", {"Gi1": [col], "Gi8": [PLC]})]
    arps = [arp("10.0.0.2", SW2), arp("10.0.0.3", SW3), arp("10.0.0.11", PLC), arp("10.0.0.250", col)]
    r = run(devices, fdbs, [], arps)
    switch_links = {(lk["source"], lk["source_port"], lk["target"], lk["target_port"])
                    for lk in r["links"] if lk["evidence"]["rule"] == "one_way_switch_mac"}
    assert switch_links == {("sw1", "Gi24", "sw2", "Gi1"), ("sw2", "Gi2", "sw3", "Gi1")}
    assert (ep(r, PLC)["switch_id"], ep(r, PLC)["port"]) == ("sw3", "Gi8")
    assert (ep(r, col)["switch_id"], ep(r, col)["port"]) == ("sw1", "Gi1")


# (d) unmanaged hub with 3 MACs on one access port
def test_d_unmanaged_hub_is_segment_not_links():
    devices = [dev("sw1", "10.0.0.1"), dev("plc", "10.0.0.11", "plc"), dev("hmi", "10.0.0.12", "hmi")]
    fdbs = [fdb("sw1", {"Gi5": [PLC, HMI, PC], "Gi6": [mac(150)]})]
    arps = [arp("10.0.0.11", PLC), arp("10.0.0.12", HMI), arp("10.0.0.13", PC)]
    r = run(devices, fdbs, [], arps)
    assert r["segments"] == [{"id": "seg-sw1-Gi5", "switch_id": "sw1", "port": "Gi5", "mac_count": 3,
                              "macs": sorted([PLC, HMI, PC]), "device_ids": ["hmi", "plc"]}]
    assert {e["segment_id"] for e in r["endpoints"] if e["mac"] in (PLC, HMI, PC)} == {"seg-sw1-Gi5"}
    assert r["links"] == []                        # no direct link for any hub member
    assert ep(r, PC)["device_id"] is None and ep(r, PC)["ip"] == "10.0.0.13"
    assert ep(r, mac(150))["segment_id"] is None   # single unknown MAC: located, no device -> no link


def test_d_segment_threshold_option():
    devices = [dev("sw1", "10.0.0.1"), dev("plc", "10.0.0.11", "plc")]
    fdbs = [fdb("sw1", {"Gi5": [PLC, HMI]})]
    r = run(devices, fdbs, [], [arp("10.0.0.11", PLC)], unmanaged_min_macs=3)
    assert r["segments"] == [] and link(r, "sw1", "plc")["source_port"] == "Gi5"


# (e) VRRP / HSRP virtual MACs are excluded
def test_e_virtual_macs_excluded():
    vrrp, hsrp1, hsrp2, rtr = "00:00:5E:00:01:0A", "0000.0c07.ac01", "00-00-0c-9f-f0-02", mac(120)
    devices = [dev("sw1", "10.0.0.1"), dev("rtr", "10.0.0.253", "router")]
    fdbs = [fdb("sw1", {"Gi48": [rtr, vrrp, hsrp1, hsrp2]})]
    arps = [arp("10.0.0.253", rtr), arp("10.0.0.254", vrrp)]
    r = run(devices, fdbs, [], arps)
    ex = {e["mac"]: e for e in r["excluded"]}
    assert ex["00:00:5e:00:01:0a"]["reason"] == "vrrp"
    assert ex["00:00:5e:00:01:0a"]["ips"] == ["10.0.0.254"]
    assert ex["00:00:0c:07:ac:01"]["reason"] == "hsrp" and ex["00:00:0c:9f:f0:02"]["reason"] == "hsrp"
    assert ex["00:00:0c:07:ac:01"]["seen_on"] == [{"switch_id": "sw1", "port": "Gi48"}]
    assert [e["mac"] for e in r["endpoints"]] == [rtr]
    # with the virtual MACs gone the port holds one MAC -> direct link, not a segment
    assert r["segments"] == [] and link(r, "sw1", "rtr")["source_port"] == "Gi48"


def test_e_virtualization_host_flagged():
    vm_host = mac(130)
    devices = [dev("sw1", "10.0.0.1")]
    fdbs = [fdb("sw1", {"Gi9": [vm_host]})]
    arps = [arp(f"10.0.1.{i}", vm_host) for i in range(1, 7)]
    r = run(devices, fdbs, [], arps, virt_host_max_ips=4)
    e = ep(r, vm_host)
    assert e["virtualization_host"] is True and len(e["ips"]) == 6 and e["ip"] == "10.0.1.1"
    assert run(devices, fdbs, [], arps[:4], virt_host_max_ips=4)["endpoints"][0]["virtualization_host"] is False


# (f) MAC on two access ports: deterministic choice, ambiguity reported
def _scenario_f():
    devices = [dev("sw1", "10.0.0.1"), dev("sw2", "10.0.0.2"), dev("plc", "10.0.0.11", "plc")]
    fdbs = [fdb("sw1", {"Gi3": [PLC, mac(160)]}),       # 2 MACs
            fdb("sw2", {"Gi4": [PLC]})]                  # 1 MAC -> chosen
    return devices, fdbs, [arp("10.0.0.11", PLC)]


def test_f_mac_on_two_access_ports():
    devices, fdbs, arps = _scenario_f()
    r = run(devices, fdbs, [], arps)
    assert (ep(r, PLC)["switch_id"], ep(r, PLC)["port"]) == ("sw2", "Gi4")
    amb = [a for a in r["ambiguities"] if a["type"] == "mac_on_multiple_access_ports"]
    assert len(amb) == 1 and amb[0]["mac"] == PLC
    assert amb[0]["chosen"] == {"switch_id": "sw2", "port": "Gi4"}
    assert {(c["switch_id"], c["port"]) for c in amb[0]["candidates"]} == {("sw1", "Gi3"), ("sw2", "Gi4")}
    assert link(r, "sw2", "plc") and link(r, "sw1", "plc") is None


def test_f_result_is_deterministic_and_inputs_untouched():
    devices, fdbs, arps = _scenario_f()
    before = copy.deepcopy((devices, fdbs, arps))
    first = run(devices, fdbs, [], arps)
    assert (devices, fdbs, arps) == before
    rnd = random.Random(48)
    for _ in range(5):
        d2, f2, a2 = copy.deepcopy(devices), copy.deepcopy(fdbs), copy.deepcopy(arps)
        rnd.shuffle(d2)
        rnd.shuffle(f2)
        for doc in f2:  # reorder ports and MACs
            items = list(doc["ports"].items())
            rnd.shuffle(items)
            doc["ports"] = {p: rnd.sample(m, len(m)) for p, m in items}
        assert run(d2, f2, [], a2) == first


def test_f_tie_broken_by_switch_id_then_port():
    devices = [dev("sw-b", "10.0.0.2"), dev("sw-a", "10.0.0.1")]
    fdbs = [fdb("sw-b", {"Gi1": [PLC]}), fdb("sw-a", {"Gi9": [PLC]})]
    r = run(devices, fdbs)
    assert (ep(r, PLC)["switch_id"], ep(r, PLC)["port"]) == ("sw-a", "Gi9")


# (g) MAC in FDB but not in ARP
def test_g_fdb_mac_without_arp():
    devices = [dev("sw1", "10.0.0.1")]
    r = run(devices, [fdb("sw1", {"Gi2": ["AA-BB-CC-00-00-01"]})])
    e = ep(r, "aa:bb:cc:00:00:01")
    assert e["ip"] is None and e["ips"] == [] and e["device_id"] is None
    assert (e["switch_id"], e["port"], e["located"], e["via"]) == ("sw1", "Gi2", True, "fdb")
    assert r["links"] == []                      # no device -> location only, no link


# ---------------- other edge cases ---------------- #
def test_mac_seen_only_on_uplinks_is_unlocated():
    devices = [dev("sw1", "10.0.0.1"), dev("sw2", "10.0.0.2")]
    fdbs = [fdb("sw1", {"Gi24": [SW2, PC]}), fdb("sw2", {"Gi1": [SW1, PC]})]
    r = run(devices, fdbs, [], [arp("10.0.0.1", SW1), arp("10.0.0.2", SW2)])
    e = ep(r, PC)
    assert e["located"] is False and e["switch_id"] is None and len(e["seen_on"]) == 2


def test_endpoint_with_lldp_is_located_via_lldp_without_duplicate_link():
    devices = [dev("sw1", "10.0.0.1"), dev("plc", "10.0.0.11", "plc")]
    fdbs = [fdb("sw1", {"Gi2": [PLC]})]
    links = [{"source_id": "sw1", "target_id": "plc", "source_port": "Gi2", "target_port": "X1"}]
    r = run(devices, fdbs, links, [arp("10.0.0.11", PLC)])
    e = ep(r, PLC)
    assert (e["switch_id"], e["port"], e["via"]) == ("sw1", "Gi2", "lldp")
    assert r["links"] == []


def test_shared_mac_between_devices_is_reported_not_attributed():
    devices = [dev("sw1", "10.0.0.1"), dev("a", "10.0.0.21", "plc"), dev("b", "10.0.0.22", "plc")]
    proxy = mac(140)
    r = run(devices, [fdb("sw1", {"Gi3": [proxy]})], [], [arp("10.0.0.21", proxy), arp("10.0.0.22", proxy)])
    assert ep(r, proxy)["device_id"] is None
    assert any(a["type"] == "mac_shared_by_devices" and a["device_ids"] == ["a", "b"] for a in r["ambiguities"])


def test_three_switches_on_one_hub_infer_no_switch_links():
    devices = [dev("sw1", "10.0.0.1"), dev("sw2", "10.0.0.2"), dev("sw3", "10.0.0.3")]
    fdbs = [fdb("sw1", {"Gi1": [SW2, SW3]}), fdb("sw2", {"Gi1": [SW1, SW3]}), fdb("sw3", {"Gi1": [SW1, SW2]})]
    arps = [arp("10.0.0.1", SW1), arp("10.0.0.2", SW2), arp("10.0.0.3", SW3)]
    r = run(devices, fdbs, [], arps)
    assert r["links"] == []
    assert any(a["type"] == "switches_share_segment" for a in r["ambiguities"])
    assert uplink_ports(r) == {("sw1", "Gi1"), ("sw2", "Gi1"), ("sw3", "Gi1")}


def test_empty_inputs():
    r = run([], [])
    assert {k: r[k] for k in ("endpoints", "links", "uplinks", "excluded")} == {
        "endpoints": [], "links": [], "uplinks": [], "excluded": []}
