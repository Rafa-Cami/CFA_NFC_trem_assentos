# ESP32-C3 SuperMini + PN532 I2C + passive buzzer test.
#
# Wiring used by the current protoboard:
# - PN532 SDA -> GPIO8
# - PN532 SCL -> GPIO9
# - buzzer +  -> GPIO4
# - buzzer -  -> GND

import machine
import pn532_i2c
import time


I2C_ID = 0
I2C_SDA_PIN = 8
I2C_SCL_PIN = 9
I2C_FREQ = 100000

PN532_I2C_ADDRESS = 0x24

BUZZER_PIN = 4
BUZZER_FREQ = 2200
BUZZER_DUTY_U16 = 49152


def _set_pwm_duty(pwm, duty_u16):
    if hasattr(pwm, "duty_u16"):
        pwm.duty_u16(duty_u16)
    else:
        pwm.duty(int(duty_u16 * 1023 / 65535))


def beep(duration_ms=120, frequency=BUZZER_FREQ):
    buzzer = machine.PWM(machine.Pin(BUZZER_PIN, machine.Pin.OUT))
    buzzer.freq(frequency)
    _set_pwm_duty(buzzer, BUZZER_DUTY_U16)
    time.sleep_ms(duration_ms)
    _set_pwm_duty(buzzer, 0)
    buzzer.deinit()
    machine.Pin(BUZZER_PIN, machine.Pin.OUT).value(0)


def success_beep():
    beep(80, 1800)
    time.sleep_ms(60)
    beep(130, 2600)


def format_uid(uid):
    return ":".join("{:02x}".format(byte) for byte in uid)


def create_i2c():
    return machine.I2C(
        I2C_ID,
        scl=machine.Pin(I2C_SCL_PIN),
        sda=machine.Pin(I2C_SDA_PIN),
        freq=I2C_FREQ,
    )


def main():
    print("Starting NFC buzzer test")
    print("I2C: SDA=GPIO{}, SCL=GPIO{}".format(I2C_SDA_PIN, I2C_SCL_PIN))
    print("Buzzer: GPIO{}".format(BUZZER_PIN))

    i2c = create_i2c()
    devices = i2c.scan()
    print("I2C devices:", [hex(device) for device in devices])

    if PN532_I2C_ADDRESS not in devices:
        print("PN532 not found at 0x24. Check SDA/SCL, VCC, GND and I2C mode.")
        for _ in range(3):
            beep(70, 500)
            time.sleep_ms(80)
        return

    pn532 = pn532_i2c.PN532_I2C(i2c, debug=False)
    ic, ver, rev, support = pn532.get_firmware_version()
    print("Found PN532 firmware version: {}.{}".format(ver, rev))

    pn532.SAM_configuration()
    success_beep()

    print("Waiting for NFC card...")
    last_uid = None

    while True:
        uid = pn532.read_passive_target(timeout=0.2)

        if uid is None:
            last_uid = None
            time.sleep_ms(100)
            continue

        if uid != last_uid:
            print("Found card UID:", format_uid(uid))
            success_beep()
            last_uid = uid

        time.sleep_ms(250)
