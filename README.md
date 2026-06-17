# CFA_wearable_protecao_pessoal
Projeto em Grupo para a disciplina de Computação Física Aplicada

# Dispositivo Wearable de Emergência para Proteção Pessoal

Repositório criado para a documentação do projeto de um dispositivo wearable de emergência desenvolvido para a disciplina de Computação Física e Aplicações. O projeto consiste em um dispositivo discreto, utilizável como colar, pulseira ou chaveiro, capaz de acionar um alerta de emergência, emitir um alarme sonoro e enviar a localização da usuária para contatos previamente cadastrados por meio de um aplicativo móvel.

## 1. Introdução

### I. Contextualização

A violência e o assédio em espaços públicos representam uma preocupação constante para muitas mulheres. Em situações de risco, nem sempre é possível utilizar o celular para pedir ajuda de forma rápida e discreta.

Nesse contexto, dispositivos vestíveis (wearables) surgem como uma alternativa tecnológica capaz de aumentar a segurança pessoal. Esses dispositivos podem ser incorporados ao cotidiano de forma discreta, permitindo o acionamento rápido de mecanismos de emergência.

O projeto proposto consiste em um wearable equipado com um botão de emergência. Quando acionado, o dispositivo envia um sinal para um aplicativo móvel conectado via Bluetooth, que obtém a localização atual do celular e a compartilha com contatos de emergência previamente cadastrados. Simultaneamente, um alarme sonoro é ativado para chamar a atenção de pessoas próximas.

### II. Conceitos e Terminologia

* **Wearable:** dispositivo eletrônico vestível incorporado a acessórios ou roupas.
* **ESP32:** microcontrolador com conectividade Wi-Fi e Bluetooth integrado.
* **Bluetooth Low Energy (BLE):** protocolo de comunicação sem fio de baixo consumo energético.
* **GPS:** sistema global de posicionamento utilizado para determinar a localização geográfica.
* **Buzzer:** componente eletrônico utilizado para emissão de sinais sonoros.
* **Aplicativo móvel:** software responsável por receber os alertas do dispositivo e enviar a localização aos contatos cadastrados.

## 2. Objetivos

### I. Objetivo Geral

Desenvolver um dispositivo wearable de emergência capaz de auxiliar pessoas em situações de risco por meio do envio rápido de alertas e compartilhamento de localização.

### II. Objetivos Específicos

* Desenvolver um dispositivo portátil e discreto.
* Permitir o acionamento rápido por meio de um único botão.
* Emitir um alerta sonoro para chamar atenção de pessoas próximas.
* Estabelecer comunicação entre o dispositivo e um aplicativo móvel.
* Compartilhar automaticamente a localização da usuária com contatos de emergência.
* Criar uma solução de baixo custo utilizando componentes amplamente disponíveis.

## 3. Materiais e Métodos

### I. Componentes Utilizados

| Quantidade | Componente               |
| ---------- | ------------------------ |
| 1          | ESP32 DevKit V1          |
| 1          | Botão de emergência      |
| 1          | Buzzer ativo             |
| 1          | LED indicador            |
| 1          | Bateria Li-Po 3,7V       |
| 1          | Módulo carregador TP4056 |
| N          | Jumpers                  |
| 1          | Protoboard               |

### II. Arquitetura do Sistema

O sistema é composto por dois módulos principais:

#### Módulo Wearable

Responsável por:

* Monitorar o botão de emergência;
* Emitir o alerta sonoro;
* Enviar sinal de emergência via Bluetooth.

#### Aplicativo Móvel

Responsável por:

* Receber o sinal enviado pelo wearable;
* Obter a localização atual do dispositivo móvel;
* Gerar um link de localização;
* Encaminhar mensagens para contatos de emergência.

### III. Fluxo de Funcionamento

1. Usuária pressiona o botão de emergência.
2. O ESP32 identifica o acionamento.
3. O buzzer é ativado.
4. O ESP32 envia um alerta via Bluetooth.
5. O aplicativo recebe o alerta.
6. O aplicativo obtém a localização do celular.
7. Uma mensagem contendo a localização é enviada aos contatos cadastrados.

## 4. Desenvolvimento

### I. Implementação do Hardware

Inicialmente será desenvolvido um protótipo eletrônico utilizando protoboard para validação do circuito.

O ESP32 será responsável pela leitura do botão e acionamento do buzzer. A comunicação com o aplicativo ocorrerá através de Bluetooth Low Energy (BLE).

### II. Implementação do Aplicativo

O aplicativo móvel será responsável pela comunicação com o wearable e pela obtenção da localização geográfica.

Ao receber o alerta enviado pelo ESP32, o aplicativo gerará uma mensagem contendo:

* Data e horário do acionamento;
* Link para visualização da localização no Google Maps.

### III. Integração

Após a validação individual dos módulos de hardware e software, será realizada a integração completa do sistema para testes de funcionamento em tempo real.

## 5. Resultados Esperados

Espera-se que o dispositivo seja capaz de:

* Detectar corretamente o acionamento do botão de emergência;
* Emitir alerta sonoro imediatamente após o acionamento;
* Estabelecer comunicação com o aplicativo móvel;
* Compartilhar a localização da usuária em poucos segundos;
* Operar de forma portátil e discreta.

## 6. Trabalhos Futuros

Como possíveis evoluções do projeto, destacam-se:

* Integração com smartwatch.
* Envio de notificações para múltiplos contatos simultaneamente.
* Histórico de acionamentos.
* Integração com serviços de emergência.
* Miniaturização do hardware para uso em colares ou pulseiras.
* Desenvolvimento de aplicativo para múltiplas plataformas.

## 7. Organização do Repositório

## 8. Referências


Google Maps Platform Documentation.
