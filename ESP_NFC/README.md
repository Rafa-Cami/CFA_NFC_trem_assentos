# NFC, sensores de assento e buzzer

O projeto usa três ESP32-C3:

- COM3: PN532 e buzzer;
- COM4: assento Alberto;
- COM5: assento Bete.

## Hardware

| Componente | Pino |
| --- | --- |
| PN532 SDA | GPIO8 |
| PN532 SCL | GPIO9 |
| Buzzer | GPIO4 |
| Sensor de assento 1 | GPIO10 |
| Sensor de assento 2 | GPIO7 |
| LED do assento | GPIO5 |

Os sensores são ativos em nível alto.

## Funcionamento

O NFC usa tarefas independentes para consultar o PN532, manter a rede, enviar
eventos e tocar o buzzer. A rede não interrompe o polling. Uma aproximação
válida entra em uma fila de oito itens por até 30 segundos e é reenviada com o
mesmo `event_id` até receber uma resposta.

Um cartão mantido sobre o leitor gera apenas um evento. Duas consultas
consecutivas sem cartão rearmam o leitor. O PN532 usa uma tentativa passiva por
consulta para não deixar comandos antigos pendentes. O ACK usa timeout de
30 ms, a busca usa 180 ms e uma busca sem cartão não é tratada como falha do
periférico.

Cada assento lê GPIO10 e GPIO7 a cada 500 ms e reporta `OCUPADO` quando qualquer
entrada estiver alta; caso contrário, reporta `DISPONIVEL`. O servidor mantém o
TTL de cinco segundos. O ESP apenas mede e aplica concessões temporárias de LED.

Os firmwares usam protocolo 1, versão `1.1.0` e builds identificados no
registro. Tarefas permanentes são supervisionadas, o event loop é protegido
por watchdog e a conexão usa heartbeat de dois segundos, três falhas
consecutivas e backoff exponencial com jitter.

## Configuração

Os arquivos `ESP_NFC/src/esp_config.py` e
`ESP_Assentos/src/esp_config.py` contêm `SSID`, `PASSWORD` e `HOST`. O hotspot
atual é `Wesley`, e o servidor está em `172.20.10.2`.

Cada ESP de assento precisa de configuração própria:

```python
SEAT_ID = "Alberto"  # COM4
SEAT_ID = "Bete"     # COM5
```

## Upload

Feche o Thonny antes de usar `mpremote`.

```powershell
python -m mpremote connect COM3 fs cp .\ESP_NFC\src\esp_config.py :esp_config.py
python -m mpremote connect COM3 fs cp .\ESP_NFC\src\nfc_state.py :nfc_state.py
python -m mpremote connect COM3 fs cp .\ESP_NFC\src\esp_comunicando.py :main.py
python -m mpremote connect COM4 fs cp .\ESP_Assentos\src\seat_state.py :seat_state.py
python -m mpremote connect COM4 fs cp .\ESP_Assentos\src\sensor_v1.py :main.py
python -m mpremote connect COM5 fs cp .\ESP_Assentos\src\seat_state.py :seat_state.py
python -m mpremote connect COM5 fs cp .\ESP_Assentos\src\sensor_v1.py :main.py
```

Os `esp_config.py` contêm credenciais e são ignorados pelo Git. Preserve o
arquivo já gravado em cada placa durante atualizações de firmware. Depois,
inicie `servidor/src/pc_server.py` e reinicie as placas.

O teste isolado `start.py`/`nfc_buzzer.py` continua disponível para bancada,
mas não usa Wi-Fi nem o protocolo integrado.
