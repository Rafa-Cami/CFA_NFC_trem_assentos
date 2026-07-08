# NFC Buzzer

Projeto MicroPython para ESP32-C3 SuperMini com PN532 em I2C. Ao aproximar um
cartao NFC do modulo PN532, o ESP32 imprime o UID no REPL e aciona um buzzer
passivo conectado ao GPIO4.

## Hardware

Ligacoes usadas pela montagem atual:

| Componente | Pino | ESP32-C3 |
| --- | --- | --- |
| PN532 | SDA | GPIO8 |
| PN532 | SCL | GPIO9 |
| PN532 | VCC | 3V3 |
| PN532 | GND | GND |
| Buzzer passivo | + | GPIO4 |
| Buzzer passivo | - | GND |

O PN532 deve estar configurado para I2C e responder no endereco `0x24`.

## Arquivos Embarcados

Copie estes arquivos da pasta `src` para a raiz do filesystem MicroPython:

- `start.py`
- `nfc_buzzer.py`
- `pn532_i2c.py`
- `adafruit_pn532.py`

## Uso

No Thonny, conecte ao ESP32 e execute no REPL:

```python
import start
```

Saida esperada na inicializacao:

```text
Starting NFC buzzer test
I2C: SDA=GPIO8, SCL=GPIO9
Buzzer: GPIO4
I2C devices: ['0x24']
Found PN532 firmware version: 1.6
Waiting for NFC card...
```

Ao aproximar um cartao:

```text
Found card UID: d3:8e:18:06
```

Para parar o loop no Thonny, use `Ctrl+C` ou `Ctrl+F2`.

## Upload Com mpremote

Feche ou desconecte o backend do Thonny antes de usar `mpremote`, pois a porta
serial nao pode ser usada por dois programas ao mesmo tempo.

```powershell
python -m mpremote connect COM3 fs cp .\src\start.py :start.py
python -m mpremote connect COM3 fs cp .\src\nfc_buzzer.py :nfc_buzzer.py
python -m mpremote connect COM3 fs cp .\src\pn532_i2c.py :pn532_i2c.py
python -m mpremote connect COM3 fs cp .\src\adafruit_pn532.py :adafruit_pn532.py
```
