<p align="center">
  <img src="./docs/priorizahlogo.png" width="100" alt="Logo do Priorizah" /><br/>
  <b>Priorizah: sistema de sensores para assentos preferenciais</b><br/>
  <span>🚈 Projeto de NFC, sensores de ocupação e sinalização visual</span>
</p>

## 📍 Visão geral

O Priorizah é um projeto desenvolvido na disciplina de
[CFA](https://github.com/FNakano/CFA) para sinalizar assentos preferenciais
disponíveis quando um cartão ou chaveiro NFC autorizado é apresentado.

O MVP utiliza três ESP32-C3:

- um ESP32 com leitor PN532 e buzzer para identificar o cartão;
- dois ESP32 de assento, cada um com dois sensores capacitivos e um LED;
- um computador que executa o servidor TCP e coordena os dispositivos.

O leitor NFC informa o evento ao servidor, o servidor consulta todos os
assentos conectados e acende o LED de **todos os assentos disponíveis**.
Quando qualquer sensor de um assento detecta que uma pessoa sentou, o LED
desse assento apaga imediatamente.

## 🗺️ Motivação

A iniciativa foi inspirada no sistema usado no metrô da Coreia do Sul e no
aplicativo
[Pink Light](https://play.google.com/store/apps/details?id=kr.doweb.pinklight&hl=pt_BR).
O objetivo é ajudar passageiros a perceber a chegada de uma pessoa com direito
ao assento preferencial, sem exigir uma solicitação verbal.

O projeto considera pessoas com deficiência, pessoas com crianças de colo,
idosos, obesos, gestantes, pessoas com mobilidade reduzida e pessoas autistas.
Como referências técnicas, foram consultados o
[CardForRPG](https://github.com/Felipe256/CardForRPG), o
[SMAC](https://github.com/Anemaygi/SMAC/tree/master/projeto) e o
[estudo de caso do Pink Light](https://publicadministration.un.org/unpsa/en/Home/Case-Details-Public?PreScreeningGUID=399fae3c-5002-4a93-af5e-88691160b86c&ReadOnly=Yes).

O sistema auxilia a sinalização, mas não substitui a colaboração dos
passageiros. Em uma aplicação real, lotação, visibilidade dos LEDs e acesso ao
leitor NFC também precisam ser considerados.

## 👩‍🦯 Fluxo de uso do MVP

1. A pessoa aproxima um cartão ou chaveiro autorizado do PN532.
2. O leitor envia ao servidor um evento NFC identificado.
3. O servidor consulta todos os assentos registrados.
4. Cada assento disponível recebe o comando para acender o LED por até
   10 segundos.
5. LEDs já acesos permanecem com o prazo original; uma nova leitura NFC não
   reinicia o temporizador.
6. Assentos ocupados não são ativados.
7. Quando qualquer sensor detecta ocupação, o LED correspondente apaga
   imediatamente e o servidor recebe o motivo `occupied`.
8. Se ninguém sentar, o LED apaga automaticamente após 10 segundos e o
   servidor recebe o motivo `timeout`.

Se não houver assento disponível, o leitor NFC produz o feedback sonoro de
erro. Anúncio no sistema de som do vagão ainda não faz parte do MVP.

Quando uma pessoa deixa um assento, ele volta a ser considerado disponível
depois que a janela de ocupação expira. O LED **não** acende automaticamente:
ele só será ligado após um novo evento NFC autorizado.

## 🗂️ Arquitetura do repositório

| Bloco | Arquivos principais | Responsabilidade |
| --- | --- | --- |
| Leitor NFC | `ESP_NFC/src/esp_comunicando.py` | PN532, autorização do UID, buzzer e comunicação TCP |
| Teste isolado do NFC | `ESP_NFC/src/start.py` e `nfc_buzzer.py` | Teste de bancada sem Wi-Fi e sem servidor |
| Assentos | `ESP_Assentos/src/sensor_v1.py` e `seat_state.py` | Sensores, janela de ocupação, LED e cliente TCP |
| Servidor | `servidor/src/pc_server.py` | Registro dos dispositivos, consulta e ativação dos assentos |
| Testes | `tests/` | Estado do assento, protocolo e concorrência do servidor |

O firmware de produção do NFC é `esp_comunicando.py`, gravado no dispositivo
como `/main.py`. Os arquivos `start.py` e `nfc_buzzer.py` são apenas para teste
isolado do PN532 e não participam do fluxo integrado.

## 🔧 Hardware e pinagem

### Leitor NFC

| Componente | Pino do componente | ESP32-C3 |
| --- | --- | --- |
| PN532 | SDA | GPIO8 |
| PN532 | SCL | GPIO9 |
| PN532 | VCC | 3V3 |
| PN532 | GND | GND |
| Buzzer passivo | positivo | GPIO4 |
| Buzzer passivo | negativo | GND |

O PN532 deve estar configurado em modo I²C e responder no endereço `0x24`.

### Cada assento

| Componente | ESP32-C3 | Estado ocupado |
| --- | --- | --- |
| Sensor capacitivo 1 | GPIO10 | nível alto (`1`) |
| Sensor capacitivo 2 | GPIO7 | nível alto (`1`) |
| LED do assento | GPIO5 | — |

O MVP completo utiliza:

- 3 ESP32-C3 SuperMini;
- 1 PN532;
- 1 buzzer passivo;
- 4 sensores capacitivos TTP223B;
- 2 LEDs com resistores adequados;
- protoboards, jumpers e um computador para o servidor.

## 🪑 Estado dos assentos

Cada ESP de assento lê GPIO10 e GPIO7 a cada 500 ms. O estado consolidado usa
uma janela deslizante de 10 amostras:

- se qualquer sensor tiver uma leitura alta dentro da janela, o estado é
  `ocupado`;
- após 10 leituras livres desde a última detecção, equivalentes a 5 segundos,
  o estado volta para `disponível`;
- após a inicialização, o assento permanece conservadoramente como `ocupado`
  até completar as primeiras 10 leituras livres.

O LED só aceita ativação quando o assento está disponível e o LED ainda está
apagado. Depois de ativado:

- permanece aceso por no máximo 10 segundos;
- uma nova ativação não renova o prazo;
- apaga imediatamente se GPIO10 ou GPIO7 detectar ocupação;
- apaga ao perder a conexão com o servidor.

## 🌐 Comunicação

Todos os dispositivos e o computador precisam estar na mesma rede. O servidor
escuta em `0.0.0.0:5000`, enquanto os ESPs usam `HOST` para alcançar o IPv4 do
computador nessa rede.

A comunicação utiliza TCP persistente e mensagens JSON delimitadas por quebra
de linha. Os comandos de assento usam `request_id`, permitindo correlacionar
respostas mesmo com vários clientes conectados. O servidor considera uma
consulta sem resposta por 1 segundo como falha e remove aquela conexão.

O NFC envia `ping` a cada 2 segundos. O `pong` correspondente confirma a
conexão e transporta a disponibilidade do PN532 por meio de `reader_ready`.
Os assentos não enviam heartbeat periódico: eles permanecem conectados,
respondem às consultas do servidor e emitem eventos quando o LED apaga.

### Mensagens do protocolo

| Mensagem | Fluxo | Finalidade |
| --- | --- | --- |
| `seat_register` | Assento → servidor | Registrar o `seat_id` |
| `get_status` | Servidor → assento | Consultar ocupação e estado do LED |
| `seat_status` | Assento → servidor | Responder `status`, `led_on` e tempo restante |
| `set_led` | Servidor → assento | Solicitar ativação ou desativação do LED |
| `set_led_result` | Assento → servidor | Confirmar ou rejeitar o comando |
| `seat_led_state` | Assento → servidor | Informar desligamento por `occupied` ou `timeout` |
| `nfc_register` | NFC → servidor | Registrar `device_id` e `reader_ready` |
| `nfc_register_ack` | Servidor → NFC | Confirmar o registro |
| `nfc_presented` | NFC → servidor | Enviar `event_id` e índice do cartão autorizado |
| `nfc_result` | Servidor → NFC | Informar resultado e `seat_ids` ativados |
| `ping` / `pong` | NFC ↔ servidor | Verificar a sessão a cada 2 segundos |

O servidor ainda aceita mensagens legadas no formato `nfc_1`, `nfc_2` etc.,
mas o firmware de produção usa `nfc_presented`.

## ⚙️ Configuração

Nunca publique SSID, senha ou endereços privados reais no README ou em commits.
Use os arquivos de exemplo como base:

```powershell
Copy-Item .\ESP_NFC\src\esp_config.example.py .\ESP_NFC\src\esp_config.py
Copy-Item .\ESP_Assentos\src\esp_config.example.py .\ESP_Assentos\src\esp_config.py
```

Configuração do NFC:

```python
SSID = "NOME_DA_REDE"
PASSWORD = "SENHA_DA_REDE"
HOST = "192.168.0.100"
```

Configuração de cada assento:

```python
SSID = "NOME_DA_REDE"
PASSWORD = "SENHA_DA_REDE"
HOST = "192.168.0.100"
SEAT_ID = "assento_1"
```

Cada placa de assento precisa de um `SEAT_ID` exclusivo. Prepare uma cópia
local de `esp_config.py` para cada placa e verifique `git status` antes de
qualquer commit para não publicar credenciais.

Os UIDs autorizados são definidos em `NFC_UUIDS`, dentro de
`ESP_NFC/src/esp_comunicando.py`.

## 📤 Gravação nos ESP32

Instale o `mpremote` e feche o backend do Thonny antes de acessar as portas:

```powershell
python -m pip install mpremote
```

As portas abaixo representam a montagem usada durante o desenvolvimento.
Confirme as portas do seu computador antes de gravar:

- COM3: leitor NFC;
- COM4: Alberto;
- COM5: Bete.

Grave o NFC:

```powershell
python -m mpremote connect COM3 fs cp .\ESP_NFC\src\esp_config.py :esp_config.py
python -m mpremote connect COM3 fs cp .\ESP_NFC\src\esp_comunicando.py :main.py
```

Grave Alberto usando a configuração preparada para esse assento:

```powershell
python -m mpremote connect COM4 fs cp C:\caminho\alberto\esp_config.py :esp_config.py
python -m mpremote connect COM4 fs cp .\ESP_Assentos\src\seat_state.py :seat_state.py
python -m mpremote connect COM4 fs cp .\ESP_Assentos\src\sensor_v1.py :main.py
```

Grave Bete usando sua própria configuração:

```powershell
python -m mpremote connect COM5 fs cp C:\caminho\bete\esp_config.py :esp_config.py
python -m mpremote connect COM5 fs cp .\ESP_Assentos\src\seat_state.py :seat_state.py
python -m mpremote connect COM5 fs cp .\ESP_Assentos\src\sensor_v1.py :main.py
```

Reinicie as placas após conferir os arquivos:

```powershell
python -m mpremote connect COM3 reset
python -m mpremote connect COM4 reset
python -m mpremote connect COM5 reset
```

## ▶️ Execução

No diretório raiz, inicie apenas uma instância do servidor:

```powershell
python .\servidor\src\pc_server.py
```

Saída esperada:

```text
Servidor ouvindo na porta 5000
Leitor NFC registrado: nfc_reader (...)
PN532 pronto: nfc_reader
Assento registrado: Alberto (...)
Assento registrado: Bete (...)
```

Ao aproximar um cartão autorizado com os dois assentos disponíveis:

```text
NFC recebido: nfc_1 = 1
LED ativado no assento Alberto; desligamento em 10 s
LED ativado no assento Bete; desligamento em 10 s
```

Quando uma pessoa sentar:

```text
LED apagado no assento Alberto: occupied
```

## ✅ Testes

Execute a suíte a partir da raiz:

```powershell
python -m unittest discover -s tests -v
```

A suíte atual contém 18 testes cobrindo:

- janela de ocupação dos dois sensores;
- ativação e desligamento do LED;
- desligamento imediato ao detectar ocupação;
- timeout do LED;
- registro e substituição de conexões;
- correlação por `request_id`;
- ativação de todos os assentos disponíveis;
- concorrência entre eventos NFC;
- registro e heartbeat do leitor NFC.

Os sensores, LEDs, buzzer e PN532 também precisam de validação física após a
gravação.

## 🩺 Diagnóstico

### Os ESPs não conectam ao servidor

- confirme que todos estão na mesma rede;
- use no `HOST` o IPv4 do computador acessível pelos ESPs;
- libere a porta TCP 5000 no firewall;
- verifique se existe apenas uma instância de `pc_server.py`;
- confirme que o servidor está escutando em `0.0.0.0:5000`.

No Windows, consulte a porta com:

```powershell
Get-NetTCPConnection -LocalPort 5000
```

### O PN532 não responde

Se o console mostrar `PN532 initialization deferred` ou
`PN532 still unavailable`, confira:

- alimentação em 3V3 e GND;
- SDA em GPIO8 e SCL em GPIO9;
- PN532 configurado para I²C;
- endereço esperado `0x24`.

A ausência de cartão não faz o PN532 desaparecer do barramento; esse erro
indica falha de comunicação com o módulo, montagem ou alimentação.

### O firmware para ao abrir o Thonny

O Thonny pode interromper o `/main.py` ao assumir a porta serial. Durante o
MVP, deixe o backend desconectado. Depois de usar o REPL, desconecte o Thonny e
reinicie a placa.

## 📢 Próximas evoluções

- integrar o sistema ao alto-falante do vagão;
- adicionar confirmação visual no leitor NFC;
- suportar múltiplos leitores NFC no mesmo vagão;
- avaliar sensores de presença com maior alcance;
- criar monitoramento e painel operacional;
- ampliar os testes físicos de perda de rede e falhas do barramento I²C.
