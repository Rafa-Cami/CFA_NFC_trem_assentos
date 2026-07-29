"""Run directly on the NFC ESP with: mpremote connect COM3 run tools/nfc_diagnostic.py."""

import time

import main as firmware


def elapsed_ms(started_at):
    return time.ticks_diff(time.ticks_ms(), started_at)


print("NFC_DIAG_START")
i2c = firmware.create_i2c()
print("I2C_SCAN", [hex(address) for address in i2c.scan()])

reader = firmware.PN532_I2C(i2c, debug=False)
print("FIRMWARE_BEFORE", reader.get_firmware_version())
reader.SAM_configuration()

for poll_number in range(1, 21):
    started_at = time.ticks_ms()
    try:
        uid = reader.read_passive_target()
        if uid is None:
            result = "none"
        else:
            result = firmware.format_uid(uid)
        print("POLL", poll_number, result, elapsed_ms(started_at))
    except Exception as error:
        print(
            "POLL_ERROR",
            poll_number,
            type(error).__name__,
            str(error),
            elapsed_ms(started_at),
        )
    time.sleep_ms(100)

started_at = time.ticks_ms()
print("FIRMWARE_AFTER", reader.get_firmware_version(), elapsed_ms(started_at))

print("CARD_TEST_START", 45)
test_started_at = time.ticks_ms()
last_uid = None
absence_polls = 2
card_events = 0

while elapsed_ms(test_started_at) < 45000:
    try:
        uid = reader.read_passive_target()
    except Exception as error:
        print("CARD_TEST_ERROR", type(error).__name__, str(error))
        time.sleep_ms(100)
        continue

    if uid is None:
        absence_polls += 1
        if absence_polls >= 2:
            last_uid = None
        time.sleep_ms(50)
        continue

    absence_polls = 0
    uid_text = firmware.format_uid(uid)
    if uid_text != last_uid:
        card_events += 1
        last_uid = uid_text
        print("CARD", card_events, uid_text)
        firmware.success_beep()

    time.sleep_ms(50)

print("CARD_TEST_END", card_events)
print("FIRMWARE_FINAL", reader.get_firmware_version())
print("NFC_DIAG_END")
