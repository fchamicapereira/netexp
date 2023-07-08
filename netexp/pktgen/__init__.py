from abc import ABCMeta, abstractmethod


class Pktgen(metaclass=ABCMeta):
    @abstractmethod
    def set_params(self, pkt_size, nb_src, nb_dst) -> None:
        pass

    @abstractmethod
    def set_pcap(self, pcap: str) -> None:
        pass

    @abstractmethod
    def get_mean_pkt_size(self) -> float:
        pass

    @abstractmethod
    def launch(self) -> None:
        pass
    
    @abstractmethod
    def start(self, capacity: float, nb_pkts: int = 0) -> None:
        pass

    @abstractmethod
    def set_rate(self, capacity: float) -> None:
        pass

    @abstractmethod
    def wait_transmission_done(self) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def clean_stats(self) -> None:
        pass

    @abstractmethod
    def close(self) -> None:
        pass

    @abstractmethod
    def get_nb_rx_pkts(self) -> int:
        pass

    @abstractmethod
    def get_nb_rx_bytes(self) -> int:
        pass

    @abstractmethod
    def get_nb_tx_pkts(self) -> int:
        pass

    @abstractmethod
    def get_nb_tx_bytes(self) -> int:
        pass

    @abstractmethod
    def get_rx_throughput(self) -> int:
        pass

    @abstractmethod
    def get_tx_throughput(self) -> int:
        pass
