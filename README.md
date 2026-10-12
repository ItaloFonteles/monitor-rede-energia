# Monitor de Rede e Energia

Vigia **internet, roteador, câmeras, sistemas e o nobreak** de uma empresa e **avisa no Telegram (ou WhatsApp, via n8n)** quando algo cai, quando volta e quando falta energia. Todo mês gera um **relatório de disponibilidade** pronto para entregar ao cliente.

Pensado para pequenas empresas, clínicas e escritórios de **Boa Vista - RR**, onde quedas de energia e de internet são comuns e ninguém fica sabendo até o cliente reclamar.

**Stack:** Python 3.12 (só biblioteca padrão) · SQLite · Docker Compose · Telegram · webhook para n8n · NUT (nobreak)

---

## O que ele faz

- Verifica cada equipamento a cada minuto: **ping**, **porta TCP** (câmera, servidor, impressora), **site/sistema web** e **nobreak** (via NUT).
- **Confirma antes de avisar:** só alerta depois de N falhas seguidas, o que evita alarme falso por um ping perdido.
- Alertas claros, com o horário e quanto tempo ficou fora:
  ```
  🔴 Clínica Exemplo: Câmera da recepção está fora do ar desde 18:46.
  🟢 Clínica Exemplo: Câmera da recepção voltou. Ficou fora por 12 min.
  ⚡ Clínica Exemplo: falta de energia — Nobreak do rack: nobreak na bateria, bateria 98%, autonomia ~49 min (desde 18:47).
  🔌 Clínica Exemplo: energia restabelecida (Nobreak do rack). Ficou 25 min sem energia.
  ```
- **Painel** no navegador com o status ao vivo e as últimas ocorrências.
- **Relatório mensal** (HTML para imprimir ou salvar em PDF): disponibilidade de cada equipamento, quedas, maior queda e tempo de resposta. É enviado automaticamente no dia 1.
- **Sinal de vida** (heartbeat) para um serviço externo: se o local ficar **sem energia e sem internet**, o monitor não consegue avisar, mas o serviço externo percebe o silêncio e avisa você.
- Histórico guardado em SQLite; se o monitor reiniciar, ele lembra o que estava fora do ar.

## Testar em 2 minutos (com nobreak simulado)

Requisito: **Docker Desktop**.

```bash
cp .env.example .env
cp config.exemplo.toml config.toml
docker compose up -d --build
```

- Painel: **http://localhost:8090**
- Alertas (em modo de teste aparecem só no log): `docker compose logs -f monitor`

O exemplo já tem uma "câmera" desligada de propósito, então em alguns minutos aparece o alerta 🔴.

**Simular falta de energia:**

| Ação | Endereço |
|------|----------|
| Faltou energia (nobreak vai para a bateria) | http://localhost:8091/falta-energia |
| Energia voltou | http://localhost:8091/energia-voltou |

**Relatório do mês atual:** http://localhost:8090/relatorio

## Configurar para um cliente

### 1. Equipamentos (`config.toml`)

```toml
[geral]
cliente = "Clínica São José"
intervalo_segundos = 60
falhas_para_alerta = 3

[[alvos]]
nome = "Roteador"
tipo = "ping"
host = "192.168.0.1"

[[alvos]]
nome = "Câmera da recepção"
tipo = "tcp"
host = "192.168.0.50"
porta = 554

[[alvos]]
nome = "Sistema da clínica"
tipo = "http"
url = "http://192.168.0.10:8080"
categoria = "servico"

[[alvos]]
nome = "Nobreak do rack"
tipo = "nut"
host = "192.168.0.10"
ups = "nobreak"
```

| Tipo | Campos | Serve para |
|------|--------|------------|
| `ping` | `host` | roteador, switch, computador, internet (`1.1.1.1`) |
| `tcp` | `host`, `porta` | câmera (554), impressora (9100), servidor (22, 3389) |
| `http` | `url` (e opcional `status_esperado`) | sites, sistemas web, painel do roteador |
| `nut` | `host` (e opcional `ups`, `porta`) | nobreak conectado por USB a um computador com NUT |

`categoria` (opcional): `rede`, `servico` ou `energia`. Muda o texto do alerta.

### 2. Alertas no Telegram (`.env`)

1. No Telegram, fale com o **@BotFather** → `/newbot` → copie o **token**.
2. Mande qualquer mensagem para o seu bot e depois fale com o **@userinfobot** para descobrir o seu **chat_id**. Para um grupo, adicione o bot no grupo e use o id do grupo.
3. No `.env`:
   ```
   MODO_TESTE=false
   TELEGRAM_TOKEN=123456:ABC...
   TELEGRAM_CHAT_ID=123456789
   ```
4. `docker compose up -d monitor`. Chega a mensagem "✅ Monitor iniciado".

### 3. Alertas no WhatsApp (via n8n)

Coloque em `WEBHOOK_URL` o endereço de um webhook do n8n. Cada alerta chega como JSON:

```json
{ "texto": "🔴 Clínica: Roteador está fora do ar desde 10:42.", "evento": "caiu",
  "alvo": "Roteador", "categoria": "rede", "cliente": "Clínica", "inicio": "2026-10-12 10:42:10", "fim": null }
```

No n8n, basta um fluxo **Webhook → HTTP Request** para a Evolution API (`/message/sendText`), mandando o campo `texto`. É o mesmo esquema do projeto [atendimento-whatsapp](https://github.com/ItaloFonteles/atendimento-whatsapp).

### 4. Nobreak de verdade (NUT)

O nobreak precisa estar ligado por **USB** a um computador Linux (pode ser o próprio mini PC do monitor) com o **NUT** instalado:

```bash
sudo apt install nut
```

- `/etc/nut/ups.conf`:
  ```
  [nobreak]
    driver = usbhid-ups
    port = auto
  ```
- `/etc/nut/upsd.conf`: `LISTEN 0.0.0.0 3493`
- `/etc/nut/nut.conf`: `MODE=netserver`
- `sudo systemctl restart nut-server` e teste com `upsc nobreak`.

Muitos nobreaks nacionais funcionam com `usbhid-ups` ou `blazer_usb`/`nutdrv_qx`. Consulte a [lista de compatibilidade do NUT](https://networkupstools.org/stable-hcl.html).

**Sem nobreak compatível?** Use uma "sentinela": um equipamento barato ligado **direto na tomada, sem nobreak** (um roteadorzinho ou uma tomada inteligente). Cadastre como `tipo = "ping"` e `categoria = "energia"`. Se ele cair enquanto o resto continua no ar, é falta de energia.

### 5. Sinal de vida (recomendado)

1. Crie uma conta grátis em [healthchecks.io](https://healthchecks.io), crie um "check" com período de 5 min e configure o aviso para o seu e-mail ou Telegram.
2. Coloque a URL de ping em `HEARTBEAT_URL`.

Se o monitor parar de mandar sinal (sem energia, sem internet ou computador desligado), o healthchecks.io avisa.

## Instalar no cliente

O ideal é um **mini PC ou Raspberry Pi** com Linux e Docker, ligado **no nobreak**, dentro da rede do cliente:

1. Instale o Docker e copie o projeto (`git clone`).
2. No `docker-compose.yml`, troque `ports` por `network_mode: host` no serviço `monitor` e **apague o serviço `nobreak-simulado`**.
3. Configure `config.toml` e `.env` e rode `docker compose up -d --build`.
4. O painel fica em `http://IP-DO-MINI-PC:8090` para quem estiver na rede local.

## Testes

```bash
docker run --rm -v "${PWD}:/m" -w /m python:3.12-slim python -m unittest -v
```

Cobrem a regra de alerta (N falhas, falha isolada, recuperação), leitura do ping e do nobreak, cálculo de disponibilidade cortando nas bordas do mês, quedas ainda abertas e a retomada após reinício.

## Estrutura

```
monitor-rede-energia/
├── app/
│   ├── main.py        # loop principal, alertas e relatório mensal
│   ├── checks.py      # ping, tcp, http e nobreak (NUT)
│   ├── estado.py      # regra "caiu/voltou" e formatação de durações
│   ├── banco.py       # histórico em SQLite
│   ├── relatorio.py   # disponibilidade e relatório HTML
│   ├── alertas.py     # Telegram, webhook e heartbeat
│   ├── painel.py      # painel web, API JSON e relatório
│   └── config.py      # leitura e validação do config.toml
├── simulador/nobreak.py   # nobreak de mentira para demonstração
├── tests/test_monitor.py
├── config.exemplo.toml
├── .env.example
├── Dockerfile
└── docker-compose.yml
```

## Endereços do painel

| Endereço | O que mostra |
|----------|--------------|
| `/` | Status ao vivo (atualiza a cada 20 s) |
| `/relatorio?mes=AAAA-MM` | Relatório de disponibilidade do mês |
| `/api/status` | Status em JSON (para integrar com n8n, Home Assistant etc.) |
| `/saude` | Responde `ok` (para checagem externa) |

---

Feito por **Ítalo Fonteles** · [italofonteles.dev](https://italofonteles.dev) · contato@italofonteles.dev
