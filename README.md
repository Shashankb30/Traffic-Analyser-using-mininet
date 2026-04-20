# SDN Traffic Classification System

> SDN Mininet-based Simulation Project — Orange Problem  
> Built with **Ryu** OpenFlow 1.3 controller + **Mininet**

---

## Problem Statement

Traditional networks treat all traffic identically, making it hard to
monitor, prioritise, or analyse traffic patterns in real time.  This
project implements an **SDN-based Traffic Classification System** using
Mininet and a Ryu OpenFlow controller.

**The system:**
- Classifies every packet by protocol type: **TCP / UDP / ICMP / OTHER**
- Installs per-flow rules with protocol-specific match fields
- Maintains per-host and per-protocol packet & byte statistics
- Prints a live **traffic distribution report** every 15 seconds
- Demonstrates two test scenarios: mixed-protocol traffic and heavy load

---

## Repository Layout

```
sdn_traffic_classifier/
├── controller/
│   └── traffic_classifier.py   # Ryu controller (main SDN logic)
├── topology/
│   └── topology.py             # Mininet star topology (4 hosts, 1 switch)
├── tests/
│   └── test_scenarios.py       # Test plan + regression check commands
└── README.md
```

---

## Topology Diagram

```
          h1 (10.0.0.1)    h2 (10.0.0.2)
                \               /
                 +--- s1 (OVS)---+
                /               \
          h3 (10.0.0.3)    h4 (10.0.0.4)
                        |
              Ryu Controller (127.0.0.1:6633)
```

- **Switch**: OVS with OpenFlow 1.3
- **Links**: 10 Mbps, 5 ms RTT (TCLink)
- **Controller**: Ryu remote controller

---

## Setup & Execution

### Prerequisites

```bash
# Install Mininet
sudo apt-get install mininet

# Install Ryu
pip3 install ryu

# (Optional) Wireshark for packet capture
sudo apt-get install wireshark
```

### Step 1 — Start the Ryu Controller

```bash
ryu-manager controller/traffic_classifier.py --verbose
```

You should see:
```
loading app traffic_classifier.py
instantiating app traffic_classifier.py of TrafficClassifier
```

### Step 2 — Start the Mininet Topology (new terminal)

```bash
sudo python3 topology/topology.py
```

The Mininet CLI (`mininet>`) will appear after the topology starts.

### Step 3 — Run Test Scenarios

Inside the Mininet CLI:

```bash
# Scenario 1a — ICMP (ping)
mininet> h1 ping -c 10 h2

# Scenario 1b — TCP throughput
mininet> h1 iperf -s &
mininet> h2 iperf -c 10.0.0.1 -t 10

# Scenario 1c — UDP throughput
mininet> h3 iperf -u -s &
mininet> h4 iperf -u -c 10.0.0.3 -t 10 -b 5M

# Inspect flow table
mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s1
```

---

## SDN Logic & Flow Rule Design

### packet_in Handling

```
Packet arrives at switch
        ↓
  Switch checks flow table
        ↓  (no match → table-miss)
  Sends PacketIn to controller
        ↓
  Controller classifies protocol
  (TCP / UDP / ICMP / OTHER)
        ↓
  Installs OFPFlowMod with
  protocol-specific match fields
        ↓
  Forwards packet out correct port
```

### Match Fields per Protocol

| Protocol | eth_type | ip_proto | Extra fields          | Priority |
|----------|----------|----------|-----------------------|----------|
| ICMP     | 0x0800   | 1        | ipv4_src, ipv4_dst    | 20       |
| TCP      | 0x0800   | 6        | ipv4_src/dst, tcp ports | 20     |
| UDP      | 0x0800   | 17       | ipv4_src/dst, udp ports | 20     |
| OTHER    | —        | —        | eth_src, eth_dst      | 10       |
| miss     | —        | —        | (wildcard)            | 0        |

### Flow Timeouts

- **idle_timeout = 30 s** — removes stale flows after inactivity
- **hard_timeout = 120 s** — maximum flow lifetime

---

## Expected Output

### Ryu Controller Log

```
[09:12:01] dpid=1 port=1 00:00:00:00:00:01 → 00:00:00:00:00:02  [ICMP] 98 bytes
[09:12:01] dpid=1 port=2 00:00:00:00:00:02 → 00:00:00:00:00:01  [ICMP] 98 bytes
[09:12:05] dpid=1 port=1 00:00:00:00:00:01 → 00:00:00:00:00:02  [TCP] 74 bytes
...
=======================================================
  TRAFFIC CLASSIFICATION REPORT
  Total packets captured: 248
-------------------------------------------------------
  Protocol   Packets       Bytes   Share
-------------------------------------------------------
  TCP              142       72456   57.3%
  UDP               68       34816   27.4%
  ICMP              38        3724   15.3%
=======================================================
```

### ovs-ofctl dump-flows

```
cookie=0x0, table=0, n_packets=38, ip,ip_proto=1 actions=output:2
cookie=0x0, table=0, n_packets=142, tcp,nw_src=10.0.0.1,tcp_src=5001 actions=output:2
cookie=0x0, table=0, n_packets=68, udp,nw_src=10.0.0.3,udp_dst=5001 actions=output:4
```

### iperf TCP

```
Client connecting to 10.0.0.1, TCP port 5001
[  3]  0.0-10.0 sec   11.2 MBytes   9.38 Mbits/sec
```

### iperf UDP

```
Client connecting to 10.0.0.3, UDP port 5001
[  3]  0.0-10.0 sec  5.96 MBytes  5.00 Mbits/sec
Sent 4284 datagrams
```

---

## Test Scenarios

### Scenario 1 — Mixed Protocol Traffic

| Test        | Command                                   | Expected Result                     |
|-------------|-------------------------------------------|-------------------------------------|
| ICMP        | `h1 ping -c 10 h2`                        | 0% loss, RTT ~10 ms                 |
| TCP         | `h2 iperf -c 10.0.0.1 -t 10`             | ~9-10 Mbps                          |
| UDP         | `h4 iperf -u -c 10.0.0.3 -b 5M -t 10`   | ~5 Mbps, low jitter                 |
| Flow table  | `ovs-ofctl dump-flows s1`                 | ip_proto=1, 6, 17 entries visible   |

### Scenario 2 — Traffic Distribution

Generate sequential bursts and verify controller stats:

1. 100 ICMP pings (`h1 ping -c 100 -i 0.1 h2`)
2. 30 s TCP iperf
3. 30 s UDP iperf at 8 Mbps

The Ryu log should show a shift in share% matching traffic generated.

---

## Regression Checks

```bash
# Check at least one classified flow exists
sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep -c 'ip_proto'

# Verify each protocol class is present
sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep 'ip_proto=1'   # ICMP
sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep 'ip_proto=6'   # TCP
sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep 'ip_proto=17'  # UDP

# Confirm flows have matched packets (n_packets > 0)
sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep -v 'n_packets=0'
```

---

## Performance Observations

| Metric            | Value (typical)          | Tool          |
|-------------------|--------------------------|---------------|
| ICMP RTT (10 Mbps)| ~10 ms                   | ping          |
| TCP throughput    | ~9-10 Mbps               | iperf         |
| UDP throughput    | ~5-8 Mbps (target rate)  | iperf -u      |
| Flow install time | <2 ms (first packet)     | controller log|
| Idle flow timeout | 30 s                     | OFPFlowMod    |

---

## References

1. Mininet Documentation — http://mininet.org/
2. Ryu SDN Framework — https://ryu.readthedocs.io/
3. OpenFlow 1.3 Specification — https://opennetworking.org/
4. Open vSwitch — https://www.openvswitch.org/
5. iPerf2 User Documentation — https://iperf.fr/

---



