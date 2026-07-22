"""Unit tests for USB-only device filtering (no hardware required)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from device_installer import DeviceInfo, _dedupe_usb_devices, is_usb_connection  # noqa: E402


class IsUsbConnectionTests(unittest.TestCase):
    def test_whitelist_exact(self) -> None:
        for value in ("usb", "USB", "usbmux", "usbmuxd", " Usb "):
            self.assertTrue(is_usb_connection(value), value)

    def test_whitelist_prefix(self) -> None:
        self.assertTrue(is_usb_connection("USB"))
        self.assertTrue(is_usb_connection("ConnectionTypeUSB"))
        self.assertTrue(is_usb_connection("usb0"))

    def test_rejects_empty_and_unknown(self) -> None:
        self.assertFalse(is_usb_connection(None))
        self.assertFalse(is_usb_connection(""))
        self.assertFalse(is_usb_connection("ethernet"))
        self.assertFalse(is_usb_connection("unknown"))

    def test_rejects_network_wifi_variants(self) -> None:
        rejected = [
            "Network",
            "WiFi",
            "Wi-Fi",
            "wifi",
            "wireless",
            "bonjour",
            "mdns",
            "mDNS",
            "tunnel",
            "remote",
            "usb-network",
            "usb wifi",
            "ConnectionTypeNetwork",
        ]
        for value in rejected:
            self.assertFalse(is_usb_connection(value), value)


class DedupeUsbDevicesTests(unittest.TestCase):
    def test_filters_network_keeps_usb(self) -> None:
        devices = [
            DeviceInfo("aaa", "WiFi Phone", "iPhone14,2", "17.0", connection="Network"),
            DeviceInfo("bbb", "Cable Phone", "iPhone15,2", "18.0", connection="USB"),
            DeviceInfo("ccc", "Lan", "", "", connection="WiFi"),
        ]
        out = _dedupe_usb_devices(devices)
        self.assertEqual([d.udid for d in out], ["bbb"])
        self.assertEqual(out[0].name, "Cable Phone")

    def test_same_udid_usb_and_network_keeps_one_usb(self) -> None:
        devices = [
            DeviceInfo("same", "Net Name", "iPhone14,2", "17.0", connection="Network"),
            DeviceInfo("same", "USB Name", "iPhone14,2", "17.1", connection="USB"),
            DeviceInfo("same", "WiFi Again", "", "", connection="Wi-Fi"),
        ]
        out = _dedupe_usb_devices(devices)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].udid, "same")
        self.assertEqual(out[0].connection, "USB")
        self.assertEqual(out[0].name, "USB Name")

    def test_prefers_richer_usb_metadata(self) -> None:
        devices = [
            DeviceInfo("u1", "iPhone", "", "", connection="USB"),
            DeviceInfo("u1", "Artem iPhone", "iPhone15,3", "18.2", connection="usbmux"),
        ]
        out = _dedupe_usb_devices(devices)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].name, "Artem iPhone")
        self.assertEqual(out[0].model, "iPhone15,3")

    def test_stable_order_by_first_usb_seen(self) -> None:
        devices = [
            DeviceInfo("a", "A", "m1", "17", connection="USB"),
            DeviceInfo("b", "B", "m2", "18", connection="USB"),
            DeviceInfo("a", "A2", "m1b", "17.1", connection="USB"),
        ]
        out = _dedupe_usb_devices(devices)
        self.assertEqual([d.udid for d in out], ["a", "b"])
        # Equal richness → keep first-seen entry.
        self.assertEqual(out[0].name, "A")


if __name__ == "__main__":
    unittest.main()
