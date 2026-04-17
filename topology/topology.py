#!/usr/bin/env python3
"""
Mininet Topology for SDN Traffic Classification
================================================
Creates a simple star topology:
  - 1 OpenFlow switch (s1)
  - 4 hosts (h1 … h4)
  - Connected to external Ryu controller (127.0.0.1:6633)

Usage:
    sudo python3 topology.py
"""

from mininet.net    import Mininet
from mininet.node   import RemoteController, OVSKernelSwitch
from mininet.link   import TCLink
from mininet.log    import setLogLevel, info
from mininet.cli    import CLI
from mininet.topo   import Topo


class StarTopo(Topo):
    """
    Star topology: 4 hosts connected to a single switch.

          h1    h2
           \   /
            s1
           /   \
          h3    h4
    """

    def build(self):
        # Create switch
        s1 = self.addSwitch('s1', protocols='OpenFlow13')

        # Create hosts with static IPs
        hosts = [
            ('h1', '10.0.0.1/24', '00:00:00:00:00:01'),
            ('h2', '10.0.0.2/24', '00:00:00:00:00:02'),
            ('h3', '10.0.0.3/24', '00:00:00:00:00:03'),
            ('h4', '10.0.0.4/24', '00:00:00:00:00:04'),
        ]
        for name, ip, mac in hosts:
            h = self.addHost(name, ip=ip, mac=mac)
            # 10 Mbps links with 5 ms delay for realistic iperf/ping output
            self.addLink(h, s1, cls=TCLink, bw=10, delay='5ms')


def run():
    setLogLevel('info')
    topo = StarTopo()

    net = Mininet(
        topo=topo,
        controller=lambda name: RemoteController(
            name, ip='127.0.0.1', port=6633),
        switch=OVSKernelSwitch,
        link=TCLink,
        autoSetMacs=False,
    )

    net.start()
    info("\n*** Topology started — 4 hosts, 1 switch\n")
    info("*** Controller: 127.0.0.1:6633  (start Ryu first!)\n")
    info("*** IP layout:\n")
    for h in net.hosts:
        info("    %-4s  %s\n" % (h.name, h.IP()))

    info("\n*** Suggested test commands (run inside CLI):\n")
    info("    h1 ping -c 4 h2             # ICMP test\n")
    info("    h1 iperf -s &               # TCP throughput server\n")
    info("    h2 iperf -c 10.0.0.1        # TCP throughput client\n")
    info("    h3 iperf -u -s &            # UDP server\n")
    info("    h4 iperf -u -c 10.0.0.3    # UDP client\n")
    info("    sh ovs-ofctl dump-flows s1  # Show flow table\n\n")

    CLI(net)
    net.stop()


if __name__ == '__main__':
    run()
