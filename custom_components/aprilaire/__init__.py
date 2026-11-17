"""The Aprilaire integration (Enhanced for 6000-Series / Model 6003)."""

from homeassistant.const import CONF_HOST, CONF_PORT, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.device_registry import format_mac
from pyaprilaire.const import Attribute

from .coordinator import AprilaireConfigEntry, AprilaireCoordinator

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.HUMIDIFIER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


def normalize_mac(mac_address: str) -> str:
    """Return a MAC address in the zero-padded form pyaprilaire 0.10 reports.

    pyaprilaire 0.9.1 drops the leading zero of octets below 0x10
    ("b4:82:55:0:1a:5"). `format_mac` passes that through unchanged, except
    at exactly 12 characters, where it inserts a colon after every second
    character ("0:3:4a:1:2:3" becomes "0::3::4a::1::2::3"). Both shapes are
    undone here, matching the migration in Home Assistant core PR #186563.
    """
    if len(mac_address) == 17 and mac_address.count(":") == 10:
        mac_address = "".join(mac_address[i : i + 2] for i in range(0, 17, 3))

    return format_mac(":".join(octet.zfill(2) for octet in mac_address.split(":")))


def mac_matches_entry(reported_mac: str, unique_id: str | None) -> bool:
    """Compare a reported MAC with an entry's unique ID in either format.

    Core's pyaprilaire 0.10 migration rewrites the unique ID to the padded
    form. Comparing normalized values keeps this component working on entries
    created by it and on entries core has already migrated.
    """
    return unique_id is not None and normalize_mac(format_mac(reported_mac)) == normalize_mac(
        unique_id
    )


async def async_setup_entry(hass: HomeAssistant, entry: AprilaireConfigEntry) -> bool:
    """Set up a config entry for Aprilaire."""

    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]

    coordinator = AprilaireCoordinator(hass, entry, host, port)
    entry.async_on_unload(coordinator.async_stop)
    await coordinator.start_listen()

    async def ready_callback(ready: bool) -> None:
        if ready:
            if not mac_matches_entry(coordinator.data[Attribute.MAC_ADDRESS], entry.unique_id):
                raise ConfigEntryAuthFailed("Invalid MAC address")

            entry.runtime_data = coordinator

            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

            async def _async_close(_: Event) -> None:
                coordinator.stop_listen()

            entry.async_on_unload(
                hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_close)
            )
        else:
            coordinator.stop_listen()

            raise ConfigEntryNotReady("Failed to wait for ready")

    try:
        await coordinator.wait_for_ready(ready_callback)
    except BaseException:
        await coordinator.async_stop()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AprilaireConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
