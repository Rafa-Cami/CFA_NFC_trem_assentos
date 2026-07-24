# Como reproduzir o projeto

## Componentes Estruturais

Para estruturar fisicamente o projeto, serão realizados 3 protótipos, dividos em 3 partes (módulo de leitura do Cartão NFC, o PC intermediário que servirá como Hotspot e o módulo dos assentos)

### Componentes Estruturais do primeiro protótipo

#### Módulo de leitura NFC: 

| Quantidade | Componente    |
| ---------- | ------------- |
| 1          | OLED ESP32 C3 |
| 1          | Leitor NFC  PN532 |
| 1          | Buzzer        |
| 1          | Protoboard    |
| n          | Jumpers       |

#### PC Intermediário Hotspot
- Um PC configurado como hotspot de conexão entre o módulo de leitura NFC e o módulo dos assentos

#### Módulo dos assentos:

| Quantidade | Componente      |
| ---------- | --------------- |
| 1          | OLED ESP32 C3   |
| 2          | LED             |
| 2          | Módulo sensor de toque capacitivo TTP223B |
| 1          | Protoboard      |
| N          | Jumpers         |

Ligacoes do modulo de assentos:

| Funcao | GPIO |
| --- | --- |
| Sensor capacitivo 1 | GPIO10 |
| Sensor capacitivo 2 | GPIO7 |
| LED | GPIO5 |

O firmware le os dois sensores a cada 500 ms e mantem as 10 leituras mais
recentes de cada um. Uma unica leitura ocupada em qualquer sensor mantem o
estado agregado ocupado ate que ela saia da janela de 5 segundos.

O ESP dos assentos abre uma conexao TCP persistente com o PC e envia apenas um
registro ao conectar. Os estados nao sao publicados periodicamente: depois de
um evento NFC, o servidor consulta o estado agregado pela conexao ja aberta e
solicita o LED somente se o ESP responder disponivel.

### Componentes Estruturais adicionais do segundo protótipo

Para o segundo protótipo, integraremos mais um módulo de assentos, portanto adicionaremos:

| Quantidade | Componente      |
| ---------- | --------------- |
| 1          | OLED ESP32 C3   |
| 2          | LED             |
| 2          | Sensor de Toque |
| 1          | Protoboard      |
| N          | Jumpers         |

### Componentes Estruturais adicionais do segundo protótipo

Para o terceiro protótipo, apenas mudaremos a lógica interna do circuito, de modo que não adicionaremos mais componentes físicos

## Passo a Passo
