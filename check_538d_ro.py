"""Read-only state check for Goodix 27c6:538d.

Reuses goodix-fp-dump's Device/USBProtocol, but every outgoing frame goes
through a whitelist: only NOP, FIRMWARE_VERSION, PRESET_PSK_READ and READ_OTP
can reach the sensor. Anything else raises before touching the USB bus.

Usage (from anywhere): sudo .venv/bin/python check_538d_ro.py
"""

import hashlib
import os
import re
import sys

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "goodix-fp-dump")
sys.path.insert(0, REPO)

import goodix  # noqa: E402
import protocol  # noqa: E402
import driver_53xd  # noqa: E402  (constants only, main() is never called)

PRODUCT = 0x538d

ALLOWED_COMMANDS = {
    goodix.COMMAND_NOP: "nop",
    goodix.COMMAND_FIRMWARE_VERSION: "firmware_version",
    goodix.COMMAND_PRESET_PSK_READ_R: "preset_psk_read",
    goodix.COMMAND_READ_OTP: "read_otp",
}

_original_write = protocol.USBProtocol.write


def _guarded_write(self, data, timeout=5):
    if len(data) < 5 or data[0] != goodix.FLAGS_MESSAGE_PROTOCOL:
        raise PermissionError(f"Blocked non-protocol frame: {data[:8].hex()}")

    command = data[4]
    if command not in ALLOWED_COMMANDS:
        raise PermissionError(f"Blocked command 0x{command:02x}")

    print(f"[ro] -> 0x{command:02x} {ALLOWED_COMMANDS[command]}")
    return _original_write(self, data, timeout)


protocol.USBProtocol.write = _guarded_write


def predict_branch(firmware: str, valid_psk: bool):
    if re.fullmatch(driver_53xd.TARGET_FIRMWARE, firmware):
        if valid_psk:
            return "run_driver (image capture, nothing written to flash)"
        return "ERASE app (0xa4) then flash: the PSK is not zero"

    if re.fullmatch(driver_53xd.VALID_FIRMWARE, firmware):
        return "ERASE app (0xa4) then flash 13016: original firmware destroyed"

    if re.fullmatch(driver_53xd.IAP_FIRMWARE, firmware):
        if valid_psk:
            return "IAP mode: flash 13016 (0xf0) without rewriting the PSK"
        return "IAP mode: write the PSK (0xe0) then flash 13016 (0xf0)"

    return "'Invalid firmware': the script stops without writing anything"


def main():
    device = goodix.Device(PRODUCT, protocol.USBProtocol)
    device.nop()

    firmware = device.firmware_version()
    print(f"Firmware: {firmware}")

    reply = device.preset_psk_read(0xbb020001, len(driver_53xd.PMK_HASH), 0)
    if not reply[0]:
        valid_psk = False
        print("PSK: read refused by the sensor "
              "(run_538d.py would raise 'Failed to read PSK' here)")
    else:
        valid_psk = reply[1] == 0xbb020001 and reply[2] == driver_53xd.PMK_HASH
        print(f"PSK flags: 0x{reply[1]:08x}")
        print(f"PSK hash:  {reply[2].hex()}")
        print(f"PSK zero (sha256(0^32) = "
              f"{hashlib.sha256(bytes(32)).hexdigest()[:16]}...): {valid_psk}")

    if "_APP_" in firmware:
        print(f"OTP: {device.read_otp().hex()}")

    print(f"run_538d.py would do: {predict_branch(firmware, valid_psk)}")
    print(f"IAP expected by the script: {driver_53xd.IAP_FIRMWARE} "
          f"(cannot be checked in APP mode)")


if __name__ == "__main__":
    main()
