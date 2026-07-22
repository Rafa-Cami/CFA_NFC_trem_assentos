# NFC Buzzer

Módulo do Projeto em MicroPython para ESP32-C3 SuperMini com PN532 em I2C com função de: ao aproximar um
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

## Estrutura Do Codigo

O projeto agora fica separado por modulo, cada um com sua propria pasta `src`:

- `servidor/src/`: codigo do PC/servidor TCP.
- `ESP_NFC/src/`: codigo do ESP32 com leitor NFC PN532.
- `ESP_Assentos/src/`: codigo do ESP32 que controla sensor/LED do assento.

## Arquivos Embarcados

Para o ESP32 com NFC, copie `ESP_NFC/src/esp_config.example.py` para
`ESP_NFC/src/esp_config.py` e ajuste `SSID`, `PASSWORD` e `HOST`. Esse arquivo
contem configuracoes locais e e ignorado pelo Git. Ajuste `NFC_UUIDS` em
`esp_comunicando.py` quando necessario.

No Thonny, salve `esp_config.py` na raiz do dispositivo com o mesmo nome e
salve `esp_comunicando.py` como `main.py`.

Para testar apenas o leitor NFC com buzzer, copie estes arquivos de
`ESP_NFC/src` para a raiz do filesystem MicroPython:

- `start.py`
- `nfc_buzzer.py`

Para o ESP32 dos assentos, copie `ESP_Assentos/src/esp_config.example.py` para
`ESP_Assentos/src/esp_config.py` e ajuste a rede, o IP do servidor e `SEAT_ID`.
Salve `esp_config.py` na raiz do dispositivo e salve `sensor_v1.py` como
`main.py`. Cada ESP de assento deve usar um `SEAT_ID` diferente.

O assento informa ao servidor quando o sensor esta inativo. Ao receber um NFC
autorizado, o servidor seleciona o primeiro assento livre e manda acender o
LED. O LED apaga quando o sensor detecta que alguem se sentou.

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
python -m mpremote connect COM3 fs cp .\ESP_NFC\src\esp_config.py :esp_config.py
python -m mpremote connect COM3 fs cp .\ESP_NFC\src\esp_comunicando.py :main.py
python -m mpremote connect COM4 fs cp .\ESP_Assentos\src\esp_config.py :esp_config.py
python -m mpremote connect COM4 fs cp .\ESP_Assentos\src\sensor_v1.py :main.py
```

## Servidor No PC

Antes de ligar o ESP32 NFC, rode o servidor:

```powershell
python servidor\src\pc_server.py
```
