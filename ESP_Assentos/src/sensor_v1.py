from machine import Pin
import time

# Configuração dos pinos
sensor = Pin(10, Pin.IN)    # Saída (OUT) do TTP223B
led = Pin(5, Pin.OUT)       # LED externo

print("=== Sensor de Toque TTP223B ===")

while True:
    valor = sensor.value()

    print(valor)

    if valor == 0:
        led.on()      # Acende o LED ao detectar toque
    else:
        led.off()     # Apaga o LED quando não há toque

    time.sleep_ms(50)
    
#asyncio threads
