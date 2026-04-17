"""
SDN Traffic Classification System
===================================
Ryu OpenFlow Controller that classifies network traffic
by protocol type (TCP, UDP, ICMP) and maintains statistics.

Author: SDN Mininet Project
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4, tcp, udp, icmp
from ryu.lib import hub
import datetime
import logging

LOG = logging.getLogger('traffic_classifier')
LOG.setLevel(logging.INFO)


class TrafficClassifier(app_manager.RyuApp):
    """
    SDN Traffic Classification Controller

    Classifies incoming packets by protocol type (TCP, UDP, ICMP),
    installs flow rules for each protocol class, and maintains
    per-host, per-protocol traffic statistics.
    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    # Flow rule priorities
    PRIORITY_TABLE_MISS = 0
    PRIORITY_LEARNING   = 10
    PRIORITY_TCP        = 20
    PRIORITY_UDP        = 20
    PRIORITY_ICMP       = 20

    # Idle/hard timeouts (seconds)
    FLOW_IDLE_TIMEOUT = 30
    FLOW_HARD_TIMEOUT = 120

    def __init__(self, *args, **kwargs):
        super(TrafficClassifier, self).__init__(*args, **kwargs)

        # MAC address → output port mapping (per datapath)
        self.mac_to_port = {}

        # Traffic statistics: {dpid: {protocol: {src_ip: count}}}
        self.traffic_stats = {}

        # Global counters per protocol
        self.global_stats = {
            'TCP':  {'packets': 0, 'bytes': 0},
            'UDP':  {'packets': 0, 'bytes': 0},
            'ICMP': {'packets': 0, 'bytes': 0},
            'OTHER':{'packets': 0, 'bytes': 0},
        }

        # Flow event log
        self.flow_events = []

        # Start background stats printer
        self.monitor_thread = hub.spawn(self._stats_printer)

    # ------------------------------------------------------------------
    # OpenFlow event handlers
    # ------------------------------------------------------------------

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """Install table-miss flow entry when a switch connects."""
        datapath = ev.msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser

        # Table-miss: send all unmatched packets to controller
        match  = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self._add_flow(datapath, self.PRIORITY_TABLE_MISS, match, actions)

        self.mac_to_port.setdefault(datapath.id, {})
        self.traffic_stats.setdefault(datapath.id, {
            'TCP': {}, 'UDP': {}, 'ICMP': {}, 'OTHER': {}
        })
        LOG.info("Switch connected: DPID=%s", datapath.id)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """
        Handle packet_in events:
          1. Learn source MAC → port mapping.
          2. Classify packet protocol (TCP / UDP / ICMP / OTHER).
          3. Install a forwarding + classification flow rule.
          4. Update statistics.
          5. Forward the current packet.
        """
        msg      = ev.msg
        datapath = msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser
        dpid     = datapath.id
        in_port  = msg.match['in_port']

        pkt     = packet.Packet(msg.data)
        eth_pkt = pkt.get_protocol(ethernet.ethernet)
        if eth_pkt is None:
            return

        dst_mac = eth_pkt.dst
        src_mac = eth_pkt.src

        # Learn MAC → port
        self.mac_to_port[dpid][src_mac] = in_port
        out_port = (self.mac_to_port[dpid].get(dst_mac, ofproto.OFPP_FLOOD))

        # ---- Protocol classification ----
        proto, src_ip = self._classify(pkt)

        # Update statistics
        pkt_len = len(msg.data)
        self.global_stats[proto]['packets'] += 1
        self.global_stats[proto]['bytes']   += pkt_len

        per_sw = self.traffic_stats[dpid][proto]
        if src_ip:
            per_sw[src_ip] = per_sw.get(src_ip, 0) + 1

        # Log classification event
        self._log_event(dpid, in_port, src_mac, dst_mac, proto, src_ip, pkt_len)

        # ---- Install flow rule (only for known destination) ----
        actions = [parser.OFPActionOutput(out_port)]
        if out_port != ofproto.OFPP_FLOOD:
            match = self._build_match(parser, in_port, src_mac, dst_mac, proto, pkt)
            if match:
                self._add_flow(datapath,
                               self._proto_priority(proto),
                               match, actions,
                               idle_timeout=self.FLOW_IDLE_TIMEOUT,
                               hard_timeout=self.FLOW_HARD_TIMEOUT)

        # ---- Forward current packet ----
        data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        out  = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=data
        )
        datapath.send_msg(out)

    # ------------------------------------------------------------------
    # Helper: Protocol classification
    # ------------------------------------------------------------------

    def _classify(self, pkt):
        """
        Returns (protocol_name, src_ip) for the packet.
        protocol_name is one of: 'TCP', 'UDP', 'ICMP', 'OTHER'
        """
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt is None:
            return 'OTHER', None

        src_ip = ip_pkt.src

        if pkt.get_protocol(tcp.tcp):
            return 'TCP', src_ip
        if pkt.get_protocol(udp.udp):
            return 'UDP', src_ip
        if pkt.get_protocol(icmp.icmp):
            return 'ICMP', src_ip

        return 'OTHER', src_ip

    # ------------------------------------------------------------------
    # Helper: Build protocol-specific OpenFlow match
    # ------------------------------------------------------------------

    def _build_match(self, parser, in_port, src_mac, dst_mac, proto, pkt):
        """Build an OFPMatch object tailored to the detected protocol."""
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt is None:
            # Non-IP: simple L2 match
            return parser.OFPMatch(in_port=in_port,
                                   eth_src=src_mac,
                                   eth_dst=dst_mac)

        base = dict(in_port=in_port,
                    eth_type=0x0800,        # IPv4
                    ipv4_src=ip_pkt.src,
                    ipv4_dst=ip_pkt.dst)

        if proto == 'TCP':
            tcp_pkt = pkt.get_protocol(tcp.tcp)
            return parser.OFPMatch(**base,
                                   ip_proto=6,
                                   tcp_src=tcp_pkt.src_port,
                                   tcp_dst=tcp_pkt.dst_port)
        if proto == 'UDP':
            udp_pkt = pkt.get_protocol(udp.udp)
            return parser.OFPMatch(**base,
                                   ip_proto=17,
                                   udp_src=udp_pkt.src_port,
                                   udp_dst=udp_pkt.dst_port)
        if proto == 'ICMP':
            return parser.OFPMatch(**base, ip_proto=1)

        return parser.OFPMatch(**base)

    # ------------------------------------------------------------------
    # Helper: Add flow entry to switch
    # ------------------------------------------------------------------

    def _add_flow(self, datapath, priority, match, actions,
                  idle_timeout=0, hard_timeout=0):
        """Send OFPFlowMod to install a flow rule on the switch."""
        ofproto = datapath.ofproto
        parser  = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod  = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=inst,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout,
        )
        datapath.send_msg(mod)

    # ------------------------------------------------------------------
    # Helper: Priority mapping per protocol
    # ------------------------------------------------------------------

    def _proto_priority(self, proto):
        return {
            'TCP':  self.PRIORITY_TCP,
            'UDP':  self.PRIORITY_UDP,
            'ICMP': self.PRIORITY_ICMP,
        }.get(proto, self.PRIORITY_LEARNING)

    # ------------------------------------------------------------------
    # Helper: Log flow event
    # ------------------------------------------------------------------

    def _log_event(self, dpid, in_port, src_mac, dst_mac,
                   proto, src_ip, pkt_len):
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        entry = {
            'time': ts, 'dpid': dpid, 'in_port': in_port,
            'src_mac': src_mac, 'dst_mac': dst_mac,
            'proto': proto, 'src_ip': src_ip, 'bytes': pkt_len
        }
        self.flow_events.append(entry)
        LOG.info("[%s] dpid=%s port=%s %s → %s  [%s] %s bytes",
                 ts, dpid, in_port, src_mac, dst_mac, proto, pkt_len)

    # ------------------------------------------------------------------
    # Background thread: periodic statistics display
    # ------------------------------------------------------------------

    def _stats_printer(self):
        """Print traffic distribution every 15 seconds."""
        while True:
            hub.sleep(15)
            self._print_stats()

    def _print_stats(self):
        total_pkts = sum(v['packets'] for v in self.global_stats.values())
        if total_pkts == 0:
            return

        LOG.info("=" * 55)
        LOG.info("  TRAFFIC CLASSIFICATION REPORT")
        LOG.info("  Total packets captured: %d", total_pkts)
        LOG.info("-" * 55)
        LOG.info("  %-8s  %8s  %10s  %7s", "Protocol", "Packets", "Bytes", "Share")
        LOG.info("-" * 55)
        for proto, stats in self.global_stats.items():
            if stats['packets'] == 0:
                continue
            share = 100.0 * stats['packets'] / total_pkts
            LOG.info("  %-8s  %8d  %10d  %6.1f%%",
                     proto, stats['packets'], stats['bytes'], share)
        LOG.info("=" * 55)
