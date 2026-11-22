"""Where a registered data source may point (ADR-0023).

Registering connections is an admin feature and the database credentials stay the primary control,
but the backend runs inside the stack's network. Without a check, a "data source" could point at
NEXUS's own application database or at the Ollama API, or use the connection test to probe
link-local addresses such as a cloud metadata service. This check refuses those targets before any
driver opens a socket.

Residual risk (documented in ADR-0023): the driver resolves the host again when it connects, so a
DNS record that changes between the check and the connection (DNS rebinding) is not covered.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable

from nexus.config import Settings

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], Awaitable[frozenset[IpAddress]]]


def _normalize(address: IpAddress) -> IpAddress:
    """``::ffff:169.254.169.254`` is the IPv4 address in disguise: check it as IPv4."""
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


async def resolve(host: str, port: int) -> frozenset[IpAddress]:
    """Every address the system resolver returns for ``host`` (TCP)."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return frozenset(_normalize(ipaddress.ip_address(info[4][0])) for info in infos)


def _forbidden_range(address: IpAddress) -> bool:
    # ``::1`` lies inside ``::/8``, which Python reports as reserved: loopback is not forbidden
    # (a database on the same host is a legitimate source in development).
    return (
        address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or (address.is_reserved and not address.is_loopback)
    )


def internal_services(settings: Settings) -> tuple[tuple[str, str, int], ...]:
    """(label, host, port) of the stack's own services that are never a data source."""
    ollama = settings.ollama.base_url
    return (
        ("base de datos de la aplicación", settings.app_db.host, settings.app_db.port),
        ("Ollama", ollama.host or "", ollama.port or 80),
    )


async def target_problem(
    host: str, port: int, settings: Settings, *, resolver: Resolver = resolve
) -> str | None:
    """A human (Spanish) reason why ``host:port`` may not be registered, or ``None`` if it may."""
    try:
        addresses = await resolver(host, port)
    except (OSError, UnicodeError, ValueError):
        addresses = frozenset()
    if not addresses:
        return f"No se pudo resolver el host «{host}»."
    if any(_forbidden_range(address) for address in addresses):
        return (
            f"El host «{host}» resuelve a una dirección no permitida para una fuente de datos "
            "(enlace local, multicast, reservada o no especificada)."
        )
    for label, service_host, service_port in internal_services(settings):
        if service_port != port or not service_host:
            continue
        try:
            internal = await resolver(service_host, service_port)
        except (OSError, UnicodeError, ValueError):
            continue
        if addresses & internal:
            return (
                f"«{host}:{port}» es un servicio interno de NEXUS ({label}) y no puede registrarse "
                "como fuente de datos."
            )
    return None
