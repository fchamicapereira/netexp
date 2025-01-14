import ipaddress
import time

from typing import Any, Optional, Iterable, Union, TextIO

from netexp.helpers import LocalHost, RemoteHost
from netexp.pktgen import Pktgen
from netexp.helpers import (
    get_ssh_client,
    posix_shell,
    remote_command,
    run_console_commands,
    watch_command,
    get_host_from_hostname,
)


class DpdkConfig:
    """Represent DPDK command-line options.

    Attributes:
        cores: List of cores to run on.
        mem_channels: Number of memory channels to use.
        drivers: Load external drivers. Can be a single shared object file, or
          a directory containing multiple driver shared objects.
        mem_alloc: Amount of memory to preallocate at startup.
        mem_ranks: Set number of memory ranks.
        xen_dom0: Support application running on Xen Domain0 without hugetlbfs.
        syslog: Set syslog facility.
        socket_mem: Preallocate specified amounts of memory per socket.
        huge_dir: Use specified hugetlbfs directory instead of autodetected
          ones. This can be a sub-directory within a hugetlbfs mountpoint.
        proc_type: Set the type of the current process. (`primary`,
          `secondary`, or `auto`)
        file_prefix: Use a different shared data file prefix for a DPDK
          process. This option allows running multiple independent DPDK
          primary/secondary processes under different prefixes.
        pci_block_list: Skip probing specified PCI device to prevent EAL from
          using it.
        pci_allow_list: Add PCI devices in to the list of devices to probe.
        vdev: Add a virtual device using the format:
          `<driver><id>[,key=val, ...]`.
        vmware_tsc_map: Use VMware TSC map instead of native RDTSC.
        base_virtaddr: Attempt to use a different starting address for all
          memory maps of the primary DPDK process. This can be helpful if
          secondary processes cannot start due to conflicts in address map.
        vfio_intr: Use specified interrupt mode for devices bound to VFIO
          kernel driver. (`legacy`, `msi`, or `msix`)
        create_uio_dev: Create `/dev/uioX` files for devices bound to igb_uio
         kernel driver (usually done by the igb_uio driver itself).
        extra_opt: Extra command-line options.

    Examples:
        Obtaining the DPDK configuration in command-line option format:

        >>> dpdk_config = DpdkConfig([0, 2], 4, pci_allow_list='05:00.0')
        >>> str(dpdk_config)
        '-l 0,2 -n 4 -a 05:00.0'
    """

    def __init__(
        self,
        cores: Iterable[int],
        mem_channels: int,
        drivers: Optional[Iterable[str]] = None,
        mem_alloc: Optional[int] = None,
        mem_ranks: Optional[int] = None,
        xen_dom0: bool = False,
        syslog: bool = False,
        socket_mem: Optional[Iterable[int]] = None,
        huge_dir: Optional[str] = None,
        proc_type: Optional[str] = None,
        file_prefix: Optional[str] = None,
        pci_block_list: Optional[Iterable[str]] = None,
        pci_allow_list: Optional[Iterable[str]] = None,
        vdev: Optional[str] = None,
        vmware_tsc_map: bool = False,
        base_virtaddr: Optional[str] = None,
        vfio_intr: Optional[str] = None,
        create_uio_dev: bool = False,
        extra_opt: Optional[str] = None,
    ) -> None:
        self.cores = cores
        self.mem_channels = mem_channels
        self.drivers = drivers
        self.mem_alloc = mem_alloc
        self.mem_ranks = mem_ranks
        self.xen_dom0 = xen_dom0
        self.syslog = syslog
        self.socket_mem = socket_mem
        self.huge_dir = huge_dir
        self.proc_type = proc_type
        self.file_prefix = file_prefix
        self.pci_block_list = pci_block_list
        self.pci_allow_list = pci_allow_list
        self.vdev = vdev
        self.vmware_tsc_map = vmware_tsc_map
        self.base_virtaddr = base_virtaddr
        self.vfio_intr = vfio_intr
        self.create_uio_dev = create_uio_dev
        self.extra_opt = extra_opt

        if drivers is not None and not isinstance(drivers, list):
            self.drivers = [self.drivers]

        if pci_allow_list is not None and not isinstance(pci_allow_list, list):
            self.pci_allow_list = [self.pci_allow_list]

        if pci_block_list is not None and not isinstance(pci_block_list, list):
            self.pci_block_list = [self.pci_block_list]

    def __str__(self) -> str:
        opts = "-l " + ",".join(str(c) for c in self.cores)
        opts += f" -n {self.mem_channels}"

        if self.drivers is not None:
            for driver in self.drivers:
                opts += f" -d {driver}"

        if self.mem_alloc is not None:
            opts += f" -m {self.mem_alloc}"

        if self.mem_ranks is not None:
            opts += f" -r {self.mem_ranks}"

        if self.xen_dom0:
            opts += " --xen-dom0"

        if self.syslog:
            opts += " --syslog"

        if self.socket_mem is not None:
            opt = ",".join(str(sm) for sm in self.socket_mem)
            opts += f" --socket-mem {opt}"

        if self.huge_dir is not None:
            opts += f" --huge-dir {self.huge_dir}"

        if self.proc_type is not None:
            opts += f" --proc-type {self.proc_type}"

        if self.file_prefix is not None:
            opts += f" --file-prefix {self.file_prefix}"

        if self.pci_block_list is not None:
            for pci_block_list in self.pci_block_list:
                opts += f" -b {pci_block_list}"

        if self.pci_allow_list is not None:
            for pci_allow_list in self.pci_allow_list:
                opts += f" -a {pci_allow_list}"

        if self.vdev is not None:
            opts += f" --vdev {self.vdev}"

        if self.vmware_tsc_map:
            opts += " --vmware-tsc-map"

        if self.base_virtaddr is not None:
            opts += f" --base-virt-addr {self.base_virtaddr}"

        if self.vfio_intr is not None:
            opts += f" --vfio-intr {self.vfio_intr}"

        if self.create_uio_dev:
            opts += " --create-uio-dev"

        if self.extra_opt is not None:
            opts += self.extra_opt

        return opts


class DpdkPktgen(Pktgen):
    """Wrapper for DPDK pktgen.

    It assumes that DPDK pktgen can be executed remotely by running `pktgen`.
    It also requires that DPDK pktgen be built with Lua support (e.g.,
    `meson build -Denable_lua=true`).

    Attributes:
        pktgen_server: The remote host to run DPDK Pktgen on.
        dpdk_config: CLI config to pass to DPDK.
        port_map: Port map using DPDK Pktgen port map syntax.
        max_throughput: Maximum throughput supported by the NIC.
        port: Default port to use, only relevant with multiple interfaces.
        pcap: Path to pcap file.
        config_file: DPDK Pktgen configuration file.
        log_file: Log file.
        promiscuous: Enable promiscuous mode (accept all packets that arrive at
          the interface).
        numa_support: Enable NUMA support.
        extra_opt: Extra DPDK pktgen command-line options.
    """

    def __init__(
        self,
        pktgen_server: str,
        dpdk_config: Union[str, DpdkConfig],
        port_map: str,
        max_throughput: float,
        rx_port: int = 0,
        tx_port: int = 0,
        pcap: Optional[str] = None,
        config_file: Optional[str] = None,
        log_file: Optional[str] = None,
        promiscuous: bool = False,
        numa_support: bool = False,
        extra_opt: Optional[str] = None,
    ) -> None:
        self.hostname = pktgen_server
        self.pktgen_ssh_client = get_ssh_client(pktgen_server)
        self.dpdk_config = dpdk_config
        self.port_map = port_map
        self.max_throughput = max_throughput
        self.rx_port = rx_port
        self.tx_port = tx_port
        self.pcap = pcap
        self.use_pcap = pcap != None
        self.config_file = config_file
        self.log_file = log_file
        self.promiscuous = promiscuous
        self.numa_support = numa_support
        self.extra_opt = extra_opt

        self.pktgen_active = False
        self.launch()
    
    def set_pcap(self, pcap: str) -> None:
        changed = (not self.use_pcap) or (self.pcap != pcap)

        self.use_pcap = True
        self.pcap = pcap

        if self.pktgen_active and changed:
            self.close()
            self.launch()
            time.sleep(1)
            self.wait_ready(stdout=False, stderr=False)
    
    def launch(self) -> None:
        assert not self.pktgen_active

        pktgen_options = f'-m "{self.port_map}"'

        if self.use_pcap:
            assert self.pcap
            pktgen_options += f" -s {self.tx_port}:{self.pcap}"

        if self.config_file is not None:
            pktgen_options += f" -f {self.config_file}"

        if self.log_file is not None:
            pktgen_options += f" -l {self.log_file}"

        if self.promiscuous:
            pktgen_options += " -P"

        if self.numa_support:
            pktgen_options += " -N"

        if self.extra_opt is not None:
            pktgen_options += self.extra_opt
        
        if self.log_file:
            log_file = open(self.log_file, "a")
        else:
            log_file = False

        remote_cmd = f"sudo pktgen {self.dpdk_config} -- {pktgen_options}"
        self.pktgen = remote_command(
            self.pktgen_ssh_client, remote_cmd, pty=True, print_command=log_file
        )
        self.pktgen_active = True
        self.ready = False

        self.remote_cmd = remote_cmd
        self.target_pkt_tx = 0
    
    def get_mean_pkt_size(self) -> float:
        log_file: Union[bool, TextIO] = False

        if self.log_file:
            log_file = open(self.log_file, "a")

        host = get_host_from_hostname(self.hostname)
        remote_cmd =  f"capinfos -z {self.pcap}"

        capinfos_cmd = host.run_command(
            remote_cmd,
            print_command=log_file,
        )

        output = capinfos_cmd.watch(stdout=log_file, stderr=log_file)
        status = capinfos_cmd.recv_exit_status()

        if status != 0:
            raise RuntimeError("Error processing remote pcap")

        try:
            parsed_output = output.split(" ")[-2]
            mean_pcap_pkt_size = float(parsed_output)
        except (IndexError, ValueError):
            raise RuntimeError(
                f'Error processing remote pcap (capinfos output: "{output}"'
            )

        return mean_pcap_pkt_size

    def wait_ready(self, stdout: bool = True, stderr: bool = True) -> None:
        assert self.pktgen_active

        # Wait to see if we actually managed to run pktgen successfuly.
        # Typically we fail here if we forgot to bind ports to DPDK,
        # or allocate hugepages.
        if self.pktgen.exit_status_ready() and self.pktgen.recv_exit_status() != 0:
            self.pktgen_active = False
            raise Exception("Cannot run pktgen")
        
        watch_command(
            self.pktgen,
            keyboard_int=self.pktgen.close,
            stop_pattern="\r\nPktgen:/>",
            stdout=stdout,
            stderr=stderr,
        )
        self.ready = True

    def commands(self, cmds, timeout: float = 0.5) -> None:
        assert self.pktgen_active
        run_console_commands(
            self.pktgen,
            cmds,
            timeout=timeout,
            console_pattern="\r\nPktgen:/> ",
        )
    
    def _send(self, str):
        self.pktgen.send(bytes(str, "utf-8"))

    def set_params(
        self,
        pkt_size: int,
        nb_src: int,
        nb_dst: int,
        init_ip: Any = None,
        init_port: int = 0,
        tx_port: Optional[int] = None,
    ) -> None:
        init_ip = init_ip or "192.168.0.0"
        max_src_ip = ipaddress.ip_address(init_ip) + nb_src - 1
        max_dst_ip = ipaddress.ip_address(init_ip) + nb_dst - 1

        if tx_port is None:
            tx_port = self.tx_port

        if not self.ready:
            self.wait_ready(stdout=False, stderr=False)

        commands = [
            f"range {tx_port} dst port start {init_port}",
            f"range {tx_port} src ip max {max_src_ip}",
            f"range {tx_port} dst ip max {max_dst_ip}",
            f"range {tx_port} size start {pkt_size}",
            f"range {tx_port} size min {pkt_size}",
            f"range {tx_port} size max {pkt_size}",
        ]

        self.commands(commands)

    def start(
        self, capacity: float, nb_pkts: int = 0, tx_port: Optional[int] = None
    ) -> None:
        assert self.pktgen_active

        tx_port = tx_port or self.tx_port

        if not self.ready:
            self.wait_ready(stdout=False, stderr=False)

        commands = []
        if self.use_pcap:
            commands += [f"enable {tx_port} pcap"]

        self.target_pkt_tx = self.get_nb_tx_pkts() + nb_pkts

        commands += [
            f"set {tx_port} count {nb_pkts}",
            f"set {tx_port} rate {capacity}",
            f"start {tx_port}",
        ]

        self.commands(commands)
    
    def set_rate(self, capacity: float, tx_port: Optional[int] = None) -> None:
        assert capacity > 0 and capacity <= 100
        tx_port = tx_port or self.tx_port
        self.commands(f"set {tx_port} rate {capacity}")

    def wait_transmission_done(self) -> None:
        assert self.pktgen_active

        pkts_tx = 0
        while pkts_tx < self.target_pkt_tx:
            time.sleep(1)

            old_pkt_tx = pkts_tx
            pkts_tx = self.get_nb_tx_pkts()

            if old_pkt_tx == pkts_tx:
                raise RuntimeError("Pktgen is not making progress")

    def stop(self, tx_port: Optional[int] = None) -> None:
        assert self.pktgen_active
        self.commands(f"stop {tx_port or self.tx_port}")

    def clear(self) -> None:
        assert self.pktgen_active
        self.commands("clr\n")

    def clean_stats(self) -> None:
        assert self.pktgen_active
        return self.clear()

    def close(self) -> None:
        if self.pktgen_active:
            self._send("quit\n")
            time.sleep(0.1)
            self.pktgen_active = False

    def _get_stats(self, subtype: str, stat_name: str, port: int) -> int:
        assert self.pktgen_active
        self._send(
            f"\nlua 'print(pktgen.portStats(\"all\", \"{subtype}\")[{port}]."
            f"{stat_name})'\n"
        )
        output = watch_command(
            self.pktgen,
            keyboard_int=lambda: self._send("\x03"),
            stop_pattern="\r\n\\d+\r\n",
        )
        lines = output.split("\r\n")
        lines = [ln for ln in lines if ln.isdigit()]

        return int(lines[-1])

    def get_pkts_rx_rate(self, port: Optional[int] = None) -> int:
        return self._get_stats("rate", "pkts_rx", port or self.rx_port)

    def get_pkts_tx_rate(self, port: Optional[int] = None) -> int:
        return self._get_stats("rate", "pkts_tx", port or self.tx_port)

    def get_mbits_rx(self, port: Optional[int] = None) -> int:
        return self._get_stats("rate", "mbits_rx", port or self.rx_port)

    def get_mbits_tx(self, port: Optional[int] = None) -> int:
        return self._get_stats("rate", "mbits_rx", port or self.tx_port)

    def get_nb_rx_pkts(self, port: Optional[int] = None) -> int:
        return self._get_stats("port", "ipackets", port or self.rx_port)

    def get_nb_rx_bytes(self, port: Optional[int] = None) -> int:
        return self._get_stats("port", "ibytes", port or self.rx_port)
    
    def get_nb_tx_pkts(self, port: Optional[int] = None) -> int:
        return self._get_stats("port", "opackets", port or self.tx_port)

    def get_nb_tx_bytes(self, port: Optional[int] = None) -> int:
        return self._get_stats("port", "obytes", port or self.tx_port)

    def get_rx_throughput(self, port: Optional[int] = None) -> int:
        return self.get_mbits_rx(self.rx_port) * 1_000_000

    def get_tx_throughput(self, port: Optional[int] = None) -> int:
        return self.get_mbits_tx(self.tx_port) * 1_000_000

    def enter_interactive(self) -> None:
        posix_shell(self.pktgen)

    def __del__(self) -> None:
        self.close()
        self.pktgen_ssh_client.close()
        del self.pktgen_ssh_client
