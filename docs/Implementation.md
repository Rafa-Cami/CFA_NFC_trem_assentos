# Implementação do sistema NFC e assentos

## Componentes

O protótipo integrado possui:

- um ESP32-C3 com leitor PN532 e buzzer;
- dois ESP32-C3 de assento, chamados Alberto e Bete;
- dois sensores capacitivos e um LED por assento;
- um PC executando o servidor TCP.

Todos os dispositivos precisam estar na mesma rede.

## Ligações

### NFC

| Componente | Pino |
| --- | --- |
| PN532 SDA | GPIO8 |
| PN532 SCL | GPIO9 |
| PN532 VCC | 3V3 |
| PN532 GND | GND |
| Buzzer | GPIO4 |

O PN532 deve estar no modo I2C e responder em `0x24`.

### Assentos

| Componente | Pino | Ocupado |
| --- | --- | --- |
| Sensor 1 | GPIO10 | nível alto |
| Sensor 2 | GPIO7 | nível alto |
| LED | GPIO5 | — |

## Regras

- Alberto e Bete são assentos independentes.
- Cada ESP lê os dois sensores imediatamente no boot e depois a cada 500 ms.
- O estado físico é `OCUPADO` se qualquer sensor estiver alto; caso contrário,
  é `DISPONIVEL`.
- O servidor mantém o TTL: cada observação ocupada redefine o vencimento para
  cinco segundos após aquela leitura.
- Um assento sem amostra por 1,5 segundo fica indisponível.
- Um cartão autorizado ativa todos os assentos online e disponíveis por cinco
  segundos.
- Uma nova aproximação válida recalcula os assentos e reinicia os cinco
  segundos.

## Confiabilidade NFC

O firmware de produção é `ESP_NFC/src/esp_comunicando.py`, gravado como
`main.py`. O polling PN532, a rede e o buzzer são tarefas cooperativas
independentes. Assim, conexão lenta ou Wi-Fi indisponível não interrompem a
consulta ao leitor.

Eventos ficam em uma FIFO de oito posições por no máximo 30 segundos. Cada
aproximação recebe um `event_id`; retransmissões usam o mesmo identificador para
que o servidor não repita a ativação.

## Rede e protocolo

O servidor escuta TCP em `0.0.0.0:5000`. As mensagens são objetos JSON UTF-8
terminados por newline, com versão `v:1` e tamanho máximo de 512 bytes.

Todos os clientes enviam `register` e aguardam `register_ack`. Depois:

- assentos enviam `seat_sample`;
- NFC envia `nfc_presented`;
- servidor envia `set_active`;
- respostas usam `command_id` ou `event_id`.

O protocolo antigo não é compatível. Atualize servidor e placas juntos.

## Configuração e execução

O hotspot atual usa o SSID `M27`, e o servidor está em `192.168.43.202`. Esses
valores devem estar nos arquivos `esp_config.py`. COM4 usa
`SEAT_ID = "Alberto"` e COM5 usa `SEAT_ID = "Bete"`.

Inicie o servidor:

```powershell
python servidor\src\pc_server.py
```

Mantenha o Thonny desconectado durante a operação, pois seu backend interrompe
o `main.py`.

## Arquivos embarcados

### COM3 — NFC

- `esp_config.py`;
- `nfc_state.py`;
- `esp_comunicando.py` como `main.py`.

### COM4 e COM5 — assentos

- `esp_config.py` individual;
- `seat_state.py`;
- `sensor_v1.py` como `main.py`.

Antes do upload, faça backup dos arquivos atuais. Depois compare SHA-256,
reinicie as placas e confirme os registros no log do servidor.
