import machine #type: ignore

import time


BUZZER_PIN = 4


def set_duty(pwm, duty_u16):
    if hasattr(pwm, "duty_u16"):
        pwm.duty_u16(duty_u16)
    else:
        pwm.duty(int(duty_u16 * 1023 / 65535))


def tone(freq, duration_ms, duty_u16=49152):
    print("tone", freq, "Hz on GPIO", BUZZER_PIN)
    pwm = machine.PWM(machine.Pin(BUZZER_PIN, machine.Pin.OUT))
    pwm.freq(freq)
    set_duty(pwm, duty_u16)
    time.sleep_ms(duration_ms)
    set_duty(pwm, 0)
    pwm.deinit()
    machine.Pin(BUZZER_PIN, machine.Pin.OUT).value(0)
    time.sleep_ms(120)


def click_test():
    pin = machine.Pin(BUZZER_PIN, machine.Pin.OUT)
    print("click test on GPIO", BUZZER_PIN)
    for _ in range(30):
        pin.value(1)
        time.sleep_ms(8)
        pin.value(0)
        time.sleep_ms(8)


def main():
    print("Starting buzzer test on GPIO", BUZZER_PIN)
    click_test()
    for freq in (500, 1000, 2000, 3000, 4000):
        tone(freq, 350)
    print("Buzzer test finished")


main()
