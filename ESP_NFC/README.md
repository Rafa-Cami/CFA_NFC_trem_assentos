# NFC, sensores de assento e buzzer

Módulo do Projeto em MicroPython para ESP32-C3 SuperMini com PN532 em I2C.
O firmware de producao (`esp_comunicando.py`, gravado como `main.py`) le o
cartao NFC, envia o evento ao servidor do PC via TCP e aciona o buzzer
conforme a resposta (sucesso, sem assento livre ou cartao nao autorizado).
Existe tambem um teste isolado de bancada (`start.py` + `nfc_buzzer.py`) que
apenas imprime o UID no REPL e apita — **esse teste nao tem rede e nao fala
com o servidor**.

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

Ligacoes usadas no ESP32-C3 dos assentos:

| Componente | ESP32-C3 | Estado ocupado |
| --- | --- | --- |
| Sensor capacitivo 1 | GPIO10 | nivel alto (`1`) |
| Sensor capacitivo 2 | GPIO7 | nivel alto (`1`) |
| Resistor para LED| - | - |
| LED do assento | GPIO5 | - |

Os dois sensores formam um unico estado agregado e sao lidos a cada 500 ms.
Se qualquer sensor indicar ocupacao, o assento permanece ocupado por 5 segundos
contados a partir da leitura ocupada mais recente. Uma nova deteccao em qualquer
sensor reinicia essa janela. Sem deteccoes nos ultimos 5 segundos, inclusive
logo depois da inicializacao, o assento fica disponivel.

## Estrutura Do Codigo

O projeto agora fica separado por modulo, cada um com sua propria pasta `src`:

- `servidor/src/`: codigo do PC/servidor TCP.
- `ESP_NFC/src/`: codigo do ESP32 com leitor NFC PN532.
- `ESP_Assentos/src/`: codigo do ESP32 que controla sensor/LED do assento.

O ESP dos assentos continua sendo cliente TCP: ele abre e mantem uma conexao
com o servidor do PC. Ao conectar, envia um registro com seu `SEAT_ID` e depois
um heartbeat a cada 500 ms com o estado agregado. O servidor deixa de selecionar
um assento se nao receber heartbeat por 1,5 segundo. Quando recebe um NFC, usa o
estado recente armazenado e solicita o acionamento do LED ao primeiro assento
disponivel.

## Protocolo Do Assento

As mensagens continuam sendo JSON delimitado por quebra de linha:

```text
ESP -> PC: {"type":"seat_register","seat_id":"seat_1"}
ESP -> PC: {"type":"seat_heartbeat","seat_id":"seat_1","status":"disponível","led":0}
PC  -> ESP: {"type":"set_led","request_id":17,"value":1}
ESP -> PC: {"type":"set_led_result","request_id":17,"accepted":true}
```

O `request_id` permite ao servidor associar a resposta ao comando correto.
O ESP recusa `set_led` quando o assento esta ocupado ou quando o LED ja esta
aceso.

## Arquivos Embarcados

Para o ESP32 com NFC, copie `ESP_NFC/src/esp_config.example.py` para
`ESP_NFC/src/esp_config.py` e ajuste `SSID`, `PASSWORD` e `HOST`. Esse arquivo
contem configuracoes locais e e ignorado pelo Git. Ajuste `NFC_UUIDS` em
`esp_comunicando.py` quando necessario.

No Thonny, salve `esp_config.py` na raiz do dispositivo com o mesmo nome e
salve `esp_comunicando.py` como `main.py`.

Somente para testar o leitor NFC com buzzer de forma isolada (sem rede),
copie estes arquivos de `ESP_NFC/src` para a raiz do filesystem MicroPython:

- `start.py`
- `nfc_buzzer.py`

Nao use esse modo no MVP integrado: `nfc_buzzer.py` nao se conecta ao Wi-Fi
nem ao servidor.

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

O firmware de producao roda sozinho ao ligar a placa: `esp_comunicando.py`
gravado como `main.py` conecta no Wi-Fi, abre a conexao TCP com o servidor e
fica aguardando cartoes. Basta iniciar o servidor no PC e energizar o ESP32.

Saida esperada na inicializacao (visivel em um monitor serial):

```text
Starting NFC + TCP/IP
I2C: SDA=GPIO8, SCL=GPIO9
Buzzer: GPIO4
Connected to Wi-Fi
ESP32 IP: 192.168.x.x
I2C devices: ['0x24']
Found PN532 firmware version: 1.6
Waiting for NFC card...
Connecting to PC 192.168.x.x:5000...
Connected to PC
```

Ao aproximar um cartao autorizado:

```text
Found card UID: d3:8e:18:06
Sent: {'nfc_1': 1}
PC response: {'status': 'ok', ...}
```

**Atencao (Thonny):** ao conectar o Thonny na porta serial da placa, ele
interrompe o `main.py` em execucao e deixa o ESP parado no REPL — o NFC para
de se comunicar com o servidor. Durante a operacao do MVP, mantenha o Thonny
fechado/desconectado. Para voltar a operar apos usar o Thonny, desconecte-o e
reinicie a placa (botao reset ou `python -m mpremote connect COM3 reset`).

### Teste isolado (bancada, sem rede)

Com `start.py` e `nfc_buzzer.py` gravados, execute no REPL do Thonny:

```python
import start
```

Saida esperada: `Starting NFC buzzer test` e o UID dos cartoes aproximados.
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
