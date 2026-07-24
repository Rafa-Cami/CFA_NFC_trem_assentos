# NFC, sensores de assento e buzzer

Módulo do Projeto em MicroPython para ESP32-C3 SuperMini com PN532 em I2C com função de: ao aproximar um
cartao NFC do modulo PN532, o ESP32 imprime o UID no REPL e aciona um buzzer
passivo conectado ao GPIO4. 

## Hardware

Ligacoes usadas pela montagem atual:

| Componente | Pino | ESP32-C3 |
| --- | --- | --- |
| PN532 | SDA | GPIO8 |
| PN532 | SCL | GPIO9 |
| PN532 | VCC | 5v |
| PN532 | GND | GND |
| Buzzer passivo | + | GPIO4 |
| Buzzer passivo | - | GND |

O PN532 deve estar configurado para I2C e responder no endereco `0x24`.

Ligacoes usadas no ESP32-C3 dos assentos:

| Componente | ESP32-C3 | Estado ocupado |
| --- | --- | --- |
| Sensor capacitivo 1 | GPIO10 | nivel alto (`1`) |
| Sensor capacitivo 2 | GPIO7 | nivel alto (`1`) |
| LED do assento | GPIO5 | - |

Os dois sensores formam um unico estado agregado. Eles sao lidos a cada 500 ms
e cada sensor possui uma janela circular com suas 10 leituras mais recentes.
Se qualquer leitura nas duas janelas estiver ocupada, o assento inteiro sera
considerado ocupado. O estado somente passa para disponivel depois de 10 pares
consecutivos de leituras disponiveis. Durante os primeiros 5 segundos depois da
inicializacao, o estado tambem permanece ocupado.

## Estrutura Do Codigo

O projeto agora fica separado por modulo, cada um com sua propria pasta `src`:

- `servidor/src/`: codigo do PC/servidor TCP.
- `ESP_NFC/src/`: codigo do ESP32 com leitor NFC PN532.
- `ESP_Assentos/src/`: codigo do ESP32 que controla sensor/LED do assento.

O ESP dos assentos continua sendo cliente TCP: ele abre e mantem uma conexao
com o servidor do PC. Ao conectar, envia apenas um registro com seu `SEAT_ID`.
Nao ha heartbeat nem envio espontaneo de status. Quando o servidor recebe um
NFC, consulta o ultimo estado agregado pela conexao existente e, se o assento
estiver disponivel, solicita o acionamento do LED.

## Protocolo Do Assento

As mensagens continuam sendo JSON delimitado por quebra de linha:

```text
ESP -> PC: {"type":"seat_register","seat_id":"seat_1"}
PC  -> ESP: {"type":"get_status","request_id":17}
ESP -> PC: {"type":"seat_status","request_id":17,"status":"disponível"}
PC  -> ESP: {"type":"set_led","request_id":18,"value":1}
ESP -> PC: {"type":"set_led_result","request_id":18,"accepted":true}
```

O `request_id` permite ao servidor associar cada resposta a consulta correta.
O ESP recusa `set_led` quando o assento esta ocupado ou quando o LED ja esta
aceso.

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
Salve `esp_config.py` e `seat_state.py` na raiz do dispositivo e salve
`sensor_v1.py` como `main.py`. Cada ESP de assento deve usar um `SEAT_ID`
diferente.

Ao receber um NFC autorizado, o servidor consulta os assentos registrados em
ordem de `SEAT_ID`. O primeiro ESP que responder disponivel e aceitar o comando
tera o LED aceso. O LED apaga localmente assim que a janela agregada detectar
ocupacao.

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
python -m mpremote connect COM4 fs cp .\ESP_Assentos\src\seat_state.py :seat_state.py
python -m mpremote connect COM4 fs cp .\ESP_Assentos\src\sensor_v1.py :main.py
```

## Servidor No PC

Antes de ligar o ESP32 NFC, rode o servidor:

```powershell
python servidor\src\pc_server.py
```
