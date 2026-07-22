# Projeto de Cartões de identificação para pessoas com direito a assentos preferenciais

O projeto de cartões de identificação, desenvolvido na disciplina de CFA, tem como objetivo desenvolver um projeto utilizando a tecnologia de NFC para realizar avisos sonoros e alertar os passageiros do vagão. 

## Aplicação Real

A iniciativa foi inspirada no sistema de sensores utilizado no metrô da Coreia do Sul e seu aplicativo [pinklight](https://play.google.com/store/apps/details?id=kr.doweb.pinklight&hl=pt_BR), para criar uma solução baseada em IoT que incentive os passageiros a dar lugar à mulheres grávidas no assento preferencial. Segundo o [estudo de caso](https://publicadministration.un.org/unpsa/en/Home/Case-Details-Public?PreScreeningGUID=399fae3c-5002-4a93-af5e-88691160b86c&ReadOnly=Yes), "Recentemente, como muitos passageiros ficam absortos em seus smartphones enquanto viajam de ônibus ou metrô, é possível que raramente notem uma gestante por perto. Partindo do princípio de que muitos dos passageiros que não estão grávidos, mas ocupam assentos preferenciais, estariam de fato dispostos a ceder o lugar a uma mulher caso percebessem que ela está grávida, a cidade de Busan lançou o 'Pink Light'".

Assim, o dispositivo seria uma forma de alertar os passageiros quando devem ceder seu lugar para outro passageiro, sem necessidade de perguntar e sem que seja necessário pedir. É uma tecnologia relativamente barata de ser implementada como política pública que incentiva o bem-estar de diferentes grupos sociais com direito ao assento preferencial, como por exemplo: Pessoas com deficiência, pessoas com crianças de colo, idosos, obesos, gestantes, pessoas com restrição de mobilidade e autistas.

## História de usuário (exemplificação de como funcionaria o projeto):

### usuário com direito ao assento preferencial

- 1. ao entrar no trem o usuario deve ter em mãos o acessorio (cartão ou chaveiro) que tem informações sobre o assento preferencial
- 2. o usuário deve encostar o acessório no dispositivo no sensor de nfc (requisito esse estar localizado com fácil acesso)
- 3. o usuário verá a luz acima dos assentos liberados acender
- 3.5 Se não houverem assentos livres, os passageiros ouviram o anuncio da chegada do passageiro preferencial e necessidade de liberação de assentos preferenciais
- 4. o usuário pode ir até o assento, necessitando possivelmente que outros passageiros deem lugar sabendo da presença do passageiro preferencial


### usuários sem acesso ao assento preferencial

- 1. ao chegar no trem, se houver um assento vazio e nao houver pessoas preferenciais usuário pode se sentar no assento preferencial
- 2. o usuário fica tranquilo e quando chega na proxima estação se houver um usuario que deseja usar o assento preferencial ele ouve um anúncio
- 3. o usuario deve se levantar, permitindo que a luz de assento livre ligue
- 4. o usuario com direito ao assento verá o assento livre e se sentará nele


### preocupação com funcionalidade

- importante reforçar que a implementação do projeto envolve também a mudança no comportamento do usuário. Se implementado na vida real, o sucesso do projeto depende das pessoas cederem seus assentos. 

- O projeto em suas primeiras versões tem impedimentos para seu funcionamento em horários de pico. Os motivos são 
1. limitação no número de assentos
2. Possível lotação pode impedir o usuário de chegar ate o sensor do cartão. A lotação tambem pode impedir o usuário de enxergar a luz que sinaliza o assento livre, bem como impedir o deslocamento do usuario até lá.

## Como foi feito o projeto:

### Componentes:
O projeto utiliza:
- ESP32-C3 mini
- Jumpers
- PN532
- Buzzer
- Módulo sensor de toque capacitivo TTP223B
- LED
- Protoboard
- PC ou outro dispositivo para atuar como servidor

**código em micropython e comunicação via TCP/IP com necessidade de os ESP32 e o Servidor se conectarem em mesma rede**

### Código:
Os códigos se encontram

## Futuras Implementações:

- Interação de múltiplos módulos de leitor de NFC com um só servidor no vagão
- Mensagem mais amigável por meio de um alto falante (integrado ou não com o sistema de som do trem)
- Diferentes meios de detecção do NFC (Cartões, chaveiros, colares)
- Detecção avançada, por meio de sensores com maior alcance nas portas, assim não precisando de contato direto com o leitor]
- Confirmação visual de deteção no meio (luz piscando, vibração, etc)
- Sistema de controle para detectar se uma pessoa sentada no assento preferencial de fato necessita dele ou não (por meio de detecção no assento)
