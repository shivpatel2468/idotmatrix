"""Panel backends: BLE (real hardware) and a simulator."""

from . import protocol
from .base import Device, DeviceInfo
from .sim import SimDevice

__all__ = ["Device", "DeviceInfo", "SimDevice", "protocol"]
