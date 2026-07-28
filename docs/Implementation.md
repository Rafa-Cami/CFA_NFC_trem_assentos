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
- Um assento fica `ONLINE` com uma amostra de menos de dois segundos,
  `DEGRADADO` pelos cinco segundos seguintes e `OFFLINE` depois disso.
- Assentos degradados preservam identidade e estado visual, mas nunca são
  escolhidos para uma nova ativação.
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

O registro inclui `firmware_version`, `build_id`, `boot_id` e
`reconnect_attempt`. A versão embarcada é `1.1.0`; os builds aceitos são
`nfc-robustez-1` e `seat-robustez-1`. Uma incompatibilidade recebe
`register_ack` negativo com uma causa explícita. Os ESPs também exigem
`server_build_id = "server-robustez-1"` no ACK, impedindo que uma sessão antiga
pareça saudável.

Clientes enviam `ping` com `ping_id` a cada dois segundos sem tráfego e esperam
um `pong` correlacionado. Três falhas consecutivas encerram a sessão. A
reconexão usa backoff de 0,5 a 15 segundos com jitter e só volta ao início após
20 segundos de sessão saudável.

## Recuperação e observabilidade

As tarefas permanentes são supervisionadas e reiniciadas se terminarem. Três
falhas persistentes de uma tarefa essencial em 60 segundos reiniciam a placa;
um watchdog de oito segundos cobre o bloqueio completo do event loop. Ele é
armado cinco segundos após o boot, preservando uma janela segura para
manutenção via USB.

O PN532 usa timeout de ACK de 30 ms e timeout de busca de 180 ms. Ausência de
cartão e fim normal da busca não reinicializam o periférico. Erros de I2C,
frame e ACK são contados separadamente e provocam primeiro uma reconstrução do
I2C/PN532. A inicialização consulta diretamente o endereço `0x24`, evitando um
scan I2C completo que pode bloquear em um barramento degradado.

O servidor escreve logs JSON com data/hora, tempo monotônico, dispositivo,
papel, endereço, versão, build e motivo de desconexão. Os ESPs reportam uptime,
memória livre e contadores de recuperação sem imprimir uma linha para cada
busca vazia.

## Configuração e execução

O hotspot atual usa o SSID `Wesley`, e o servidor está em `172.20.10.2`. Esses
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

## Aceitação física

Depois dos testes automatizados:

1. manter o conjunto ativo por 30 a 60 minutos;
2. realizar 100 aproximações NFC e anotar sucesso, duplicidade e latência;
3. interromper o servidor por três e por dez segundos;
4. reiniciar um assento sem afetar o outro;
5. desligar e religar o hotspot;
6. interromper e restaurar SDA ou SCL do PN532;
7. confirmar que assentos degradados não são ativados.
