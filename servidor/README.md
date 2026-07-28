# Servidor TCP

O servidor coordena os leitores NFC e os dois assentos. Execute na raiz:

```powershell
python servidor\src\pc_server.py
```

Ele escuta em `0.0.0.0:5000`. No Windows, libere a entrada TCP 5000 no
firewall e mantenha apenas uma instância do processo.

## Comportamento

- Alberto e Bete são assentos independentes.
- Cada amostra `OCUPADO` define o prazo do assento como cinco segundos após a
  observação. Novas amostras ocupadas substituem o prazo; não acumulam tempo.
- Uma amostra `DISPONIVEL` não encerra antecipadamente o TTL.
- Um assento com amostra de menos de dois segundos fica `ONLINE`; nos cinco
  segundos seguintes fica `DEGRADADO`; depois fica `OFFLINE`.
- Um assento degradado mantém seu registro e estado visual, mas não pode ser
  selecionado para nova ativação.
- Um NFC válido ativa em paralelo todos os assentos online e disponíveis por
  cinco segundos.
- Um novo evento NFC válido reinicia a janela de ativação.
- Eventos repetidos com o mesmo `event_id` devolvem o resultado armazenado sem
  repetir a ativação.

## Protocolo

O transporte continua sendo TCP com JSON UTF-8 delimitado por `\n`. Todo
cliente começa com um registro de versão 1:

```json
{"v":1,"type":"register","role":"seat","device_id":"Alberto","seat_id":"Alberto","boot_id":"...","firmware_version":"1.1.0","build_id":"seat-robustez-1","reconnect_attempt":0}
```

ou:

```json
{"v":1,"type":"register","role":"nfc","device_id":"nfc_reader","boot_id":"...","firmware_version":"1.1.0","build_id":"nfc-robustez-1","reconnect_attempt":0}
```

Principais mensagens:

```text
ESP -> PC: seat_sample
ESP -> PC: nfc_presented
PC  -> ESP: set_active
ESP -> PC: set_active_result
PC  -> ESP: nfc_result
ESP -> PC: ping
PC  -> ESP: pong
```

Mensagens antigas, como `{"nfc_1":1}`, não são aceitas. Servidor e os três
ESPs devem ser atualizados de forma coordenada.

O servidor exige o registro em cinco segundos, limita a oito handshakes
pendentes e devolve uma causa explícita quando protocolo, firmware ou build são
incompatíveis. Os logs são objetos JSON e incluem duração da sessão, última
atividade e motivo do encerramento.

## Rede

O `HOST` dos ESPs deve conter o IPv4 do servidor na mesma rede. Na implantação
atual, o hotspot é `Wesley` e o servidor é `172.20.10.2`.
