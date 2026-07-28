# Plano de robustez para o MVP

## Diagnóstico observado

Os testes indicaram que o principal problema não é a conectividade básica do
hotspot, mas a comunicação de aplicação de dois ESPs.

- Os 22 testes automatizados do repositório passaram.
- O servidor respondeu corretamente ao ciclo
  `register -> register_ack -> ping -> pong`.
- `172.20.10.5` e `172.20.10.6` responderam aos testes de rede sem perda, mas
  criaram repetidamente conexões TCP que terminaram em `TIME_WAIT`.
- `172.20.10.7` conseguiu manter uma sessão TCP estabelecida, embora tenha
  apresentado perda e picos de latência em uma das amostras.
- O servidor permaneceu estável durante os testes, com aproximadamente 15 MB
  de memória e três threads.

Esse comportamento indica que os ESPs conseguem alcançar o computador, mas
alguns encerram a conexão durante o handshake. As causas mais prováveis são:

1. servidor e placas executando versões diferentes do protocolo;
2. exceção no ESP antes de enviar ou validar o primeiro `register`;
3. código atualizado no computador, mas `main.py` antigo ainda gravado nas
   placas.

Um `git pull` no computador não atualiza os ESPs. Servidor, leitor NFC e
controladores de assento precisam usar a mesma versão do protocolo:

```json
{"v":1,"type":"register","role":"seat|nfc"}
```

Os arquivos `esp_config.py` atualmente gravados nas placas devem ser
preservados, pois as configurações mantidas no repositório estão
desatualizadas.

## Mudanças prioritárias

### 1. Sincronizar e identificar os firmwares

- Gravar nas placas as versões atuais de:
  - `ESP_NFC/src/esp_comunicando.py` como `main.py`;
  - `ESP_NFC/src/nfc_state.py`;
  - `ESP_Assentos/src/sensor_v1.py` como `main.py`;
  - `ESP_Assentos/src/seat_state.py`.
- Não sobrescrever os `esp_config.py` existentes nas placas.
- Incluir `firmware_version` e `build_id` na mensagem `register`.
- Fazer o servidor rejeitar versões incompatíveis com uma causa explícita.
- Imprimir a versão do firmware, `device_id`, `boot_id` e IP no boot.
- Verificar os hashes dos arquivos depois do upload.

### 2. Supervisionar as tarefas dos ESPs

As tarefas `nfc_loop`, `network_loop`, `buzzer_loop` e `sensor_loop` não podem
terminar silenciosamente.

- Reiniciar individualmente uma tarefa que termine inesperadamente.
- Registrar traceback, memória livre, uptime e motivo da reinicialização.
- Usar watchdog somente depois de implementar recuperação própria nas tarefas.
- Remover a leitura redundante da versão do PN532 durante a inicialização.
- Se uma tarefa essencial não puder ser recuperada, reiniciar a placa com o
  motivo registrado antes do reset.

### 3. Evitar tempestades de reconexão

- Usar backoff exponencial com jitter:
  `0,5 s -> 1 s -> 2 s -> 4 s -> 8 s -> 15 s`.
- Zerar o backoff somente depois de a sessão permanecer saudável por pelo
  menos 15 a 30 segundos.
- Aplicar timeout de cinco segundos ao registro.
- Limitar conexões que não enviam um `register` válido.
- Registrar no servidor o motivo do encerramento antes de imprimir
  `Dispositivo desconectado`.
- Incluir timestamp, IP, porta, dispositivo, papel e duração da sessão nos
  logs.

### 4. Implementar tolerância lógica à desconexão

Um socket TCP morto não pode ser mantido vivo. Keep-alive ajuda a detectar a
queda; a continuidade precisa ser implementada como estado da aplicação.

- `ONLINE`: amostra de assento recebida há menos de dois segundos.
- `DEGRADADO`: até cinco segundos adicionais aguardando reconexão.
- `OFFLINE`: janela de tolerância vencida.
- Durante `DEGRADADO`, preservar a identidade e o estado visual, mas não
  ativar o assento usando uma amostra antiga.
- Após reconexão e recebimento de uma amostra fresca, retornar imediatamente
  para `ONLINE`.
- Manter eventos NFC na fila por até 30 segundos.
- Reenviar o mesmo `event_id` depois da reconexão para impedir ativações
  duplicadas.

### 5. Ajustar heartbeat e timeouts

- Enviar ping de aplicação a cada dois segundos.
- Declarar desconexão somente após três falhas consecutivas, aproximadamente
  seis segundos.
- Ativar `SO_KEEPALIVE` no servidor como proteção secundária.
- Aplicar timeout a `writer.drain()` e `reader.readline()` nos firmwares.
- Manter amostras de assento a cada 500 ms, mas não encerrar a sessão por uma
  única amostra atrasada.

### 6. Reduzir instabilidade do Wi-Fi

Como o MVP é alimentado continuamente, desabilitar a economia de energia do
Wi-Fi pode reduzir a latência:

```python
try:
    wifi.config(pm=wifi.PM_NONE)
except (AttributeError, OSError):
    pass
```

Essa configuração aumenta o consumo de energia. Deve ser validada com a versão
de MicroPython instalada nas placas.

Para a demonstração final, preferir um roteador dedicado de 2,4 GHz. Um hotspot
de celular pode alterar endereços, aplicar economia de energia ou apresentar
latência variável.

## Robustez do PN532

A configuração de uma tentativa passiva
(`MxRtyPassiveActivation = 0`) está de acordo com o manual do PN532. O envio de
ACK para abortar uma operação pendente também é suportado.

Mesmo assim, aplicar os seguintes aprimoramentos:

- separar o timeout de ACK, aproximadamente 30 ms, do timeout de busca, entre
  150 e 200 ms;
- não reinicializar o ESP inteiro após apenas três falhas;
- tentar primeiro reinicializar I2C e PN532;
- reiniciar o ESP somente após falhas persistentes;
- garantir que a recuperação do PN532 ceda tempo ao event loop para não
  bloquear rede e heartbeat;
- registrar separadamente ausência de cartão, timeout, erro de frame e erro de
  I2C;
- usar alimentação estável, fios I2C curtos, terra comum e capacitores de
  desacoplamento próximos ao ESP e ao PN532.

## Observabilidade mínima

Cada log deve incluir:

- timestamp monotônico e data/hora do servidor;
- `device_id`, papel, IP e porta;
- `firmware_version`, `build_id` e `boot_id`;
- motivo de conexão e desconexão;
- quantidade de tentativas de reconexão;
- último heartbeat ou amostra;
- quantidade de erros do PN532 e recuperações executadas;
- memória livre e uptime do ESP.

Evitar mensagens genéricas como apenas `Dispositivo desconectado`. O log deve
permitir distinguir:

- Wi-Fi perdido;
- conexão TCP recusada;
- timeout de registro;
- protocolo incompatível;
- heartbeat vencido;
- servidor encerrado;
- erro do PN532;
- tarefa interna encerrada.

## Testes de aceitação

Antes de considerar o MVP final:

1. Executar todos os testes automatizados.
2. Manter o sistema completo ativo por 30 a 60 minutos sem tempestade de
   reconexões ou tarefas encerradas.
3. Fazer 100 aproximações NFC e registrar sucesso, duplicidade e latência.
4. Desligar o servidor por três segundos e confirmar:
   - reconexão automática;
   - entrega de evento pendente;
   - apenas uma ativação por `event_id`.
5. Desligar o servidor por dez segundos e confirmar a transição
   `ONLINE -> DEGRADADO -> OFFLINE`.
6. Reiniciar apenas um assento e confirmar que o outro continua operacional.
7. Desligar e religar o hotspot e confirmar recuperação automática.
8. Interromper temporariamente SDA ou SCL do PN532 e confirmar recuperação
   depois de restaurar a ligação.
9. Confirmar que um assento degradado não é ativado com estado antigo.
10. Confirmar que cartões inválidos não ativam assentos.
11. Confirmar que uma segunda leitura válida reinicia corretamente a janela de
    ativação.
12. Verificar que todas as placas e o servidor reportam a mesma versão do
    protocolo e do firmware.

## Próxima sessão de diagnóstico

Conectar `172.20.10.5` e `172.20.10.6` por USB, uma placa por vez, e capturar o
console serial desde o boot. Procurar especialmente por:

- erro em `writer.drain()`;
- timeout aguardando `register_ack`;
- mensagem de protocolo rejeitada;
- exceção não tratada em tarefa assíncrona;
- reinicialização por watchdog ou brownout;
- falta de memória;
- falha de I2C ou PN532.

Essa captura permitirá distinguir definitivamente firmware desatualizado de
uma exceção no handshake.
