"""Functions related to netlink manipulation for Wireguard, IPRoute and FDB on Linux."""
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from textwrap import wrap
from typing import Dict, List
import pyroute2

from wgkex.common.utils import mac2eui64
from wgkex.common import logger

_PEER_TIMEOUT_HOURS = 3


@dataclass
class WireGuardClient:
    """A Class representing a WireGuard client.

    Attributes:
        public_key: The public key to use for this client.
        domain: The domain for this client.
        remove: If this is to be removed or not.
    """

    public_key: str
    domain: str
    remove: bool

    @property
    def lladdr(self) -> str:
        """Compute the X for an (IPv6) Link-Local address.

        Returns:
            IPv6 Link-Local address of the WireGuard peer.
        """
        pub_key_hash = hashlib.md5()
        pub_key_hash.update(self.public_key.encode("ascii") + b"\n")
        hashed_key = pub_key_hash.hexdigest()
        hash_as_list = wrap(hashed_key, 2)
        current_mac_addr = ":".join(["02"] + hash_as_list[:5])

        return re.sub(
            r"/\d+$", "/128", mac2eui64(mac=current_mac_addr, prefix="fe80::/10")
        )

    @property
    def vx_interface(self) -> str:
        """Returns the name of the VxLAN interface associated with this lladdr."""
        return f"vx-{self.domain}"

    @property
    def wg_interface(self) -> str:
        """Returns the WireGuard peer interface."""
        return f"wg-{self.domain}"


def wg_flush_stale_peers(domain: str) -> List[Dict]:
    """Removes stale peers.

    Arguments:
        domain: The domain to detect peers on.

    Returns:
        The peers which we can remove.
    """
    logger.info("Searching for stale clients for %s", domain)
    stale_clients = [
        stale_client for stale_client in find_stale_wireguard_clients("wg-" + domain)
    ]
    logger.debug("Found stale clients: %s", stale_clients)
    logger.info("Searching for stale WireGuard clients.")
    stale_wireguard_clients = [
        WireGuardClient(public_key=stale_client, domain=domain, remove=True)
        for stale_client in stale_clients
    ]
    logger.debug("Found stable WireGuard clients: %s", stale_wireguard_clients)
    logger.info("Processing clients.")
    link_handled = [
        link_handler(stale_client) for stale_client in stale_wireguard_clients
    ]
    logger.debug("Handled the following clients: %s", link_handled)
    return link_handled


# pyroute2 stuff
def link_handler(client: WireGuardClient) -> Dict:
    """Updates fdb, route and WireGuard peers tables for a given WireGuard peer.

    Arguments:
        client: A WireGuard peer to manipulate.
    Returns:
        The outcome of each operation.
    """
    results = dict()
    # Updates WireGuard peers.
    results.update({"Wireguard": update_wireguard_peer(client)})
    logger.debug("Handling links for %s", client)
    try:
        # Updates routes to the WireGuard Peer.
        results.update({"Route": route_handler(client)})
        logger.info("Updated route for %s", client)
    except Exception as e:
        # TODO(ruairi): re-raise exception here.
        logger.error("Failed to update route for %s (%s)", client, e)
        results.update({"Route": e})
    # Updates WireGuard FDB.
    results.update({"Bridge FDB": bridge_fdb_handler(client)})
    logger.debug("Updated Bridge FDB for %s", client)
    return results


def bridge_fdb_handler(client: WireGuardClient) -> Dict:
    """Handles updates of FDB info towards WireGuard peers.

    Note that set will remove an FDB entry if remove is set to True.

    Arguments:
        client: The WireGuard peer to update.

    Returns:
        A dict.
    """
    # TODO(ruairi): Splice this into an add_ and remove_ function.
    with pyroute2.IPRoute() as ip:
        return ip.fdb(
            "del" if client.remove else "append",
            ifindex=ip.link_lookup(ifname=client.vx_interface)[0],
            lladdr="00:00:00:00:00:00",
            dst=re.sub(r"/\d+$", "", client.lladdr),
            NDA_IFINDEX=ip.link_lookup(ifname=client.wg_interface)[0],
        )


def update_wireguard_peer(client: WireGuardClient) -> Dict:
    """Handles updates of WireGuard peers to netlink.

    Note that set will remove a peer if remove is set to True.

    Arguments:
        client: The WireGuard peer to update.

    Returns:
        A dict.
    """
    # TODO(ruairi): Splice this into an add_ and remove_ function.
    with pyroute2.WireGuard() as wg:
        wg_peer = {
            "public_key": client.public_key,
            "allowed_ips": [client.lladdr],
            "remove": client.remove,
        }
        return wg.set(client.wg_interface, peer=wg_peer)


def route_handler(client: WireGuardClient) -> Dict:
    """Handles updates of routes towards WireGuard peers.

    Note that set will remove a route if remove is set to True.

    Arguments:
        client: The WireGuard peer to update.

    Returns:
        A dict.
    """
    # TODO(ruairi): Determine what Exceptions are raised by ip.route
    # TODO(ruairi): Splice this into an add_ and remove_ function.
    with pyroute2.IPRoute() as ip:
        return ip.route(
            "del" if client.remove else "replace",
            dst=client.lladdr,
            oif=ip.link_lookup(ifname=client.wg_interface)[0],
        )


def find_stale_wireguard_clients(wg_interface: str) -> List:
    """Fetches and returns a list of peers which have not had recent handshakes.

    Arguments:
        wg_interface: The WireGuard interface to query.

    Returns:
        # A list of peers which have not recently seen a handshake.
    """
    three_hrs_in_secs = int(
        (datetime.now() - timedelta(hours=_PEER_TIMEOUT_HOURS)).timestamp()
    )
    logger.info(
        "Starting search for stale wireguard peers for interface %s.", wg_interface
    )
    with pyroute2.WireGuard() as wg:
        all_clients = []
        peers_on_interface = wg.info(wg_interface)
        logger.info("Got infos: %s.", peers_on_interface)
        for peer in peers_on_interface:
            clients = peer.get_attr("WGDEVICE_A_PEERS")
            logger.info("Got clients: %s.", clients)
            if clients:
                all_clients.extend(clients)
        ret = [
            client.get_attr("WGPEER_A_PUBLIC_KEY").decode("utf-8")
            for client in all_clients
            if client.get_attr("WGPEER_A_LAST_HANDSHAKE_TIME").get("tv_sec", int())
            < three_hrs_in_secs
        ]
        return ret
