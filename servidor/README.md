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
- Um assento sem amostra por 1,5 segundo é considerado offline.
- Um NFC válido ativa em paralelo todos os assentos online e disponíveis por
  cinco segundos.
- Um novo evento NFC válido reinicia a janela de ativação.
- Eventos repetidos com o mesmo `event_id` devolvem o resultado armazenado sem
  repetir a ativação.

## Protocolo

O transporte continua sendo TCP com JSON UTF-8 delimitado por `\n`. Todo
cliente começa com um registro de versão 1:

```json
{"v":1,"type":"register","role":"seat","device_id":"Alberto","seat_id":"Alberto","boot_id":"..."}
```

ou:

```json
{"v":1,"type":"register","role":"nfc","device_id":"nfc_reader","boot_id":"..."}
```

Principais mensagens:

```text
ESP -> PC: seat_sample
ESP -> PC: nfc_presented
PC  -> ESP: set_active
ESP -> PC: set_active_result
PC  -> ESP: nfc_result
```

Mensagens antigas, como `{"nfc_1":1}`, não são aceitas. Servidor e os três
ESPs devem ser atualizados de forma coordenada.

## Rede

O `HOST` dos ESPs deve conter o IPv4 do servidor na mesma rede. Na implantação
atual, o hotspot é `M27` e o servidor é `192.168.43.202`.
