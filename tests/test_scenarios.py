#!/usr/bin/env python3
"""
SDN Traffic Classification – Automated Test Scenarios
======================================================
Run AFTER the Mininet topology is up and the Ryu controller is running.

Scenario 1: Protocol mix  (ICMP + TCP + UDP traffic, all allowed)
Scenario 2: Heavy TCP vs UDP  (throughput comparison + classification check)

Usage (inside Mininet CLI or external terminal):
    python3 tests/test_scenarios.py

Or copy-paste individual commands into the Mininet CLI.
"""

import subprocess
import sys
import time


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def run(cmd, desc=""):
    """Run a shell command, print output, return stdout."""
    print(f"\n>>> {desc}")
    print(f"    CMD: {cmd}")
    result = subprocess.run(cmd, shell=True,
                            capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[:300])
    return result.stdout


def separator(title=""):
    print("\n" + "=" * 60)
    if title:
        print(f"  {title}")
        print("=" * 60)


# -----------------------------------------------------------------------
# Scenario 1: Mixed protocol classification
# -----------------------------------------------------------------------

def scenario_1_mixed_traffic():
    separator("SCENARIO 1 — Mixed Protocol Traffic")
    print("""
  Goal : Generate ICMP, TCP, and UDP traffic between hosts.
         Verify the controller classifies each protocol correctly
         and installs the right flow rules.
  Expected:
    - h1 → h2 ICMP:  ping replies received, ICMP flows installed
    - h1 → h2 TCP:   iperf transfers succeed, TCP flows installed
    - h3 → h4 UDP:   iperf UDP transfers succeed, UDP flows installed
""")

    # --- ICMP ---
    separator("1a) ICMP (ping)")
    run("sudo mn --test pingall", "Ping-all (uses Mininet directly; skip if net is running)")
    print("\n  Inside Mininet CLI run:")
    print("    mininet> h1 ping -c 5 h2")
    print("  Expected: 5 packets transmitted, 5 received, 0% packet loss\n")

    # --- TCP ---
    separator("1b) TCP throughput (iperf)")
    print("\n  Inside Mininet CLI run:")
    print("    mininet> h1 iperf -s &")
    print("    mininet> h2 iperf -c 10.0.0.1 -t 5")
    print("  Expected: TCP transfer ~8-10 Mbps (link cap 10 Mbps)\n")

    # --- UDP ---
    separator("1c) UDP throughput (iperf)")
    print("\n  Inside Mininet CLI run:")
    print("    mininet> h3 iperf -u -s &")
    print("    mininet> h4 iperf -u -c 10.0.0.3 -t 5 -b 5M")
    print("  Expected: UDP ~5 Mbps, low jitter, Datagrams sent/received match\n")

    # --- Flow table check ---
    separator("1d) Flow table inspection (ovs-ofctl)")
    print("\n  Run in terminal:")
    print("    sudo ovs-ofctl -O OpenFlow13 dump-flows s1")
    print("\n  You should see entries matching:")
    print("    ip_proto=1  (ICMP)")
    print("    ip_proto=6  (TCP, with tcp_src/tcp_dst ports)")
    print("    ip_proto=17 (UDP, with udp_src/udp_dst ports)\n")


# -----------------------------------------------------------------------
# Scenario 2: Traffic distribution analysis
# -----------------------------------------------------------------------

def scenario_2_distribution():
    separator("SCENARIO 2 — Traffic Distribution Analysis")
    print("""
  Goal : Send bursts of each protocol type and observe the controller's
         classification statistics.  Validates that the share% values
         reported by the Ryu app match the traffic we generated.
  Expected:
    - After ICMP burst:  ICMP share rises
    - After TCP burst:   TCP dominates
    - After UDP burst:   UDP share visible
    - Controller log shows per-host breakdown
""")

    print("  Step-by-step inside Mininet CLI:\n")

    steps = [
        ("1", "ICMP burst (100 pings)",
         "h1 ping -c 100 -i 0.1 h2"),
        ("2", "TCP burst (30 s iperf)",
         "h1 iperf -s & ; h2 iperf -c 10.0.0.1 -t 30"),
        ("3", "UDP burst (30 s iperf, 8 Mbps)",
         "h3 iperf -u -s & ; h4 iperf -u -c 10.0.0.3 -t 30 -b 8M"),
        ("4", "Flow table snapshot",
         "sh ovs-ofctl -O OpenFlow13 dump-flows s1"),
        ("5", "Port stats",
         "sh ovs-ofctl -O OpenFlow13 dump-ports s1"),
    ]

    for num, desc, cmd in steps:
        print(f"  [{num}] {desc}")
        print(f"        mininet> {cmd}\n")

    separator("Validation Checklist")
    print("""
  After running both scenarios, verify:

  [ ] ovs-ofctl dump-flows shows flows for ip_proto 1, 6, and 17
  [ ] Ryu controller log prints the TRAFFIC CLASSIFICATION REPORT
       (appears every 15 s or check directly in terminal)
  [ ] ICMP: 0% loss in ping tests
  [ ] TCP:  iperf shows ~8-10 Mbps on 10 Mbps links
  [ ] UDP:  iperf shows ~5-8 Mbps, low jitter (<1 ms expected)
  [ ] Traffic share% in report roughly matches generated mix
""")


# -----------------------------------------------------------------------
# Regression checks (ovs-ofctl based)
# -----------------------------------------------------------------------

def regression_checks():
    separator("REGRESSION CHECKS — ovs-ofctl")
    print("\nRun these commands in your host terminal:\n")

    checks = [
        ("Flow count > 0",
         "sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep -c 'ip_proto'"),
        ("ICMP flow present",
         "sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep 'ip_proto=1'"),
        ("TCP flows present",
         "sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep 'ip_proto=6'"),
        ("UDP flows present",
         "sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep 'ip_proto=17'"),
        ("Packets matched > 0 (n_packets>0)",
         "sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep -v 'n_packets=0'"),
    ]

    for title, cmd in checks:
        print(f"  [{title}]")
        print(f"    $ {cmd}\n")


# -----------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------

if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("  SDN TRAFFIC CLASSIFICATION — TEST SCENARIOS")
    print("=" * 60)
    print("\nNOTE: This script prints the test plan.")
    print("      Run commands inside the Mininet CLI or host terminal.\n")

    scenario_1_mixed_traffic()
    scenario_2_distribution()
    regression_checks()

    print("\nAll scenario instructions printed. Good luck!\n")
