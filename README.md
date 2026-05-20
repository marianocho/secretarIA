# secretarIA

Bot pessoal de Telegram que cria eventos no Google Calendar a partir de
mensagens em português, parseadas por regex (sem IA). Roda local, é
single-user, e recupera mensagens enviadas enquanto estava offline (limite
de 24h do Telegram).

> Você escreve no Telegram: `Dentista amanhã 16:00 @ Clínica X`
> Bot devolve: `✅ Dentista — 11/05/2026 16:00–17:00 [abrir no calendar]`
> E o evento já está no seu Google Calendar.

---

## Índice

- [O que faz](#o-que-faz)
- [Arquitetura](#arquitetura)
- [Fluxo de mensagem](#fluxo-de-mensagem)
- [Formato de mensagem](#formato-de-mensagem)
- [Esquemas de dados](#esquemas-de-dados)
- [Componentes](#componentes)
- [Configuração](#configuração)
- [Setup inicial](#setup-inicial)
- [Como rodar](#como-rodar)
- [Testes](#testes)
- [Roadmap](#roadmap)
- [Estrutura de arquivos](#estrutura-de-arquivos)

---

## O que faz

Você manda uma mensagem estruturada no Telegram (ex: `Reunião 18/05 14:00`,
`Happy hour sexta 19:00 @ bar`), o bot extrai os campos via regex (título,
data, hora, local, notas) e cria um evento no seu Google Calendar primário.
Responde com o link clicável.

**Por que existe:** tirar a fricção de abrir o app do Calendar e preencher
formulário toda vez que aparece um compromisso. Por design, é single-user
(só você) e o input é estruturado (sem IA) — quem ditou esse desenho foi
escolha de simplicidade e custo zero.

**O que NÃO faz hoje:** listar / editar / cancelar eventos, eventos
recorrentes, criar Google Tasks (com checkbox de concluído), entender
linguagem natural totalmente livre tipo "dentista lá pelas 4 da tarde
amanhã". Lista completa no [Roadmap](#roadmap).

---

## Arquitetura

```
┌─────────────┐
│   Telegram  │   ← usuário envia mensagem
└──────┬──────┘
       │ getUpdates() longpoll
       ▼
┌──────────────────────────────────────────────────────┐
│                    bot.py                            │
│  ┌────────────────────────────────────────────────┐  │
│  │ startup: lê state.json → drena backlog → live  │  │
│  └────────────────────────────────────────────────┘  │
│       │                                              │
│       ▼ checa chat_id contra whitelist               │
│       ▼                                              │
│  ┌─────────┐                                         │
│  │ parser  │  texto → ParsedEvent | ParseError       │
│  └─────────┘                                         │
│       │                                              │
│       ▼ (se sucesso)                                 │
│  ┌──────────────────┐                                │
│  │ calendar_client  │  insert event → Google         │
│  └──────────────────┘                                │
│       │                                              │
│       ▼                                              │
│  ┌─────────┐                                         │
│  │  state  │  salva update_id processado             │
│  └─────────┘                                         │
└──────────────────────────────────────────────────────┘
       │
       ▼ resposta com link
┌─────────────┐         ┌─────────────────────┐
│   Telegram  │         │  Google Calendar    │
│  (resposta) │         │  (evento criado)    │
└─────────────┘         └─────────────────────┘
```

**Princípios de design:**

- **Single-user com whitelist por chat_id.** Bots do Telegram são públicos
  por default (qualquer um que descobrir o username pode mandar mensagem).
  Filtro de identidade no nosso código é o que isola você do resto.

- **Determinismo > flexibilidade.** Parser regex em vez de LLM. Você dita
  o formato, o script é previsível, custo zero, sem chave de API extra.

- **Resiliência offline.** Bot armazena `last_update_id` do Telegram. Ao
  reiniciar, busca tudo desde aquele ID (até o limite de 24h da plataforma).

- **Sem persistência além do mínimo.** Não tem banco de dados. Os únicos
  arquivos de estado: `state.json` (1 inteiro) e `credentials/token.json`
  (token OAuth do Google).

- **Configuração via `.env`.** Todos os segredos e parâmetros lá. Falha cedo
  e com mensagem clara se faltar variável obrigatória.

---

## Fluxo de mensagem

### Modo live (bot ligado)

```
1. Usuário envia "Dentista amanhã 16:00" no Telegram
2. bot.get_updates(offset=N+1, timeout=30) retorna o update
3. bot.py verifica from_user.id == ALLOWED_TELEGRAM_USER_ID
   └─ se não bater: ignora silenciosamente, mas atualiza state.json
4. parser.parse(texto, now=datetime.now(TZ)) é chamado
   ├─ pré-processa "amanhã" → "12/05/2026"
   ├─ extrai notas (após #), local (após @)
   ├─ encontra DD/MM, separa título do resto
   ├─ parseia hora/duração
   └─ retorna ParsedEvent ou ParseError
5. Se ParseError: bot responde com mensagem amigável + bloco de exemplos
6. Se ParsedEvent:
   ├─ calendar_client.find_conflicts(event) — busca timed events que
   │   sobrepõem o horário
   └─ calendar_client.create_event(event) — events().insert(...)
7. bot responde com preview do evento + link + aviso de conflito (se houver)
8. state.save_last_update_id(update.update_id)
```

### Modo backlog (startup do bot)

```
1. bot inicia
2. state.load_last_update_id() lê state.json (ou None se primeira vez)
3. bot.get_updates(offset=N+1, timeout=0) busca tudo acumulado
   └─ Telegram retém updates por até 24h. Acima disso, perdido.
4. Se tem updates:
   ├─ Processa cada um (parse + create_event) sem responder per-msg
   ├─ Acumula resultados (sucessos e erros) em lista
   └─ Envia UMA mensagem-resumo:
        "📬 Backlog processado (8 mensagens)
         ✅ Criados (6): ...
         ❌ Erros (2): ..."
5. state.save_last_update_id(último update_id)
6. Entra em live loop (modo acima)
```

---

## Formato de mensagem

```
<título> <data> [<HH:MM>[-<HH:MM> | +Xh[Ym] | +Xm]] [@<local>] [#<notas>]
```

### `<data>`

- **Numérica**: `DD/MM` ou `DD/MM/AAAA` (ex: `18/05`, `01/06/2027`).
- **Relativa**: `hoje`, `amanhã` (ou `amanha`), `depois de amanhã`.
- **Dia da semana**: `segunda`, `terça`, `quarta`, `quinta`, `sexta`,
  `sábado`, `domingo` (com ou sem acento, com ou sem `-feira`).

### Hora (opcional)

- Omitida → evento de dia inteiro (all-day).
- `HH:MM` sozinha → 1h de duração default.
- `HH:MM-HH:MM` → range explícito.
- `HH:MM +Xh`, `HH:MM +Ym`, `HH:MM +XhYm` → duração explícita.

### Marcadores opcionais

- `@<local>` — extrai o local (vai pro campo `location` no Google).
- `#<notas>` — extrai a descrição (vai pro campo `description`).

### Exemplos

| Mensagem | Vira |
|---|---|
| `Dentista 18/05 16:00` | 16:00–17:00 (default 1h) |
| `Dentista amanhã 16:00` | mesmo, com data relativa |
| `Aula 15/05 19:00-21:00` | range explícito |
| `Reunião 18/05 14:00 +30m` | duração explícita |
| `Happy hour sexta 19:00` | próxima sexta-feira |
| `Festa 01/06 20:00 @ casa do Greg` | com local |
| `Aniversário 12/07` | sem hora → all-day |
| `Prova 22/05 14:00 @ FCT # cadeira de SO` | local + notas |

### Regras importantes

- **Dia da semana sempre aponta pra próxima ocorrência.** Se hoje é domingo
  e você escreve "domingo", vira o **próximo** domingo (daqui a 7 dias),
  não hoje. Pra hoje você diria "hoje".
- **Data sem ano** → ano atual; se já passou no ano atual, próximo ano.
- **Ano explícito** é respeitado mesmo que passado (`01/01/2020` → 2020).
- **Data numérica vence palavra relativa**: `Aula de domingo 18/05 14:00`
  → título "Aula de domingo", data 18/05.

---

## Detecção de conflito

Antes de criar o evento, o bot consulta o calendário e verifica se já existe
algum evento que sobreponha o horário. O comportamento depende do **modo**:

### Modo live (interativo)

Se há conflito, o bot **não cria** o evento ainda. Manda uma mensagem com
botões inline:

```
⚠️ Reunião (14:00–15:00) conflita com:
  • Almoço (12:30–14:30)
  • Call (14:00–14:30)

O que fazer?
  [ ✅ Criar mesmo assim       ]
  [ 🔄 Mover 'Almoço' (12:30)  ]
  [ 🔄 Mover 'Call' (14:00)    ]
  [ ↩️ Refazer evento novo     ]
```

- **Criar mesmo assim**: cria o evento sobreposto, normal. Você decide
  depois se precisa mexer em algo.
- **Mover X**: o bot pergunta "manda a nova data/hora pra X". Você responde
  com mensagem texto (ex: `19/05 14:00`, `amanhã 16:00`). O bot dá `patch`
  no evento existente (preservando event_id e link) e **em seguida** cria o
  evento novo no horário original. Tudo numa transação lógica.
- **Refazer evento novo**: o bot esquece o evento pendente. Você reenvia
  com data/hora diferente.

A qualquer momento durante a conversa, `/cancelar` (ou `/cancel`) limpa o
estado e te devolve pro IDLE.

### Modo backlog (não-interativo)

Quando o bot acorda e drena mensagens acumuladas, **não usa botões** —
seria pesadelo de UX ter que tocar em 5 prompts em sequência. Cria todos
os eventos, e na mensagem-resumo cada item com conflito ganha um pequeno
`⚠️` ao lado do título.

### Regras gerais

- Só verifica conflito entre eventos com horário definido. All-day eventos
  são ignorados dos dois lados (não geram conflito quando você cria um, e
  não aparecem como conflito quando você cria outro).
- Mostra até 5 conflitos por prompt. Se tiver mais, mostra "e mais N".
- Se a API do Google falha na checagem (rede, rate-limit), o bot segue **sem
  o aviso de conflito**. Checagem é nice-to-have, não trava o caminho feliz.
- Em modo "mover existente", quando você manda a nova data/hora, o bot
  **não verifica** se essa nova hora também tem conflito. Confia na sua
  escolha. Se tiver, vai aparecer no Calendar normalmente.

### Estado da conversa

A conversa (`AwaitingDecision`, `AwaitingNewDate`) é mantida **em memória**
no módulo [src/conversation.py](src/conversation.py). Se o bot reiniciar
no meio de uma resolução de conflito, o estado é perdido — você reenvia o
evento. Persistir em disco adicionaria complexidade (sincronização,
serialização de `ParsedEvent`/`ExistingEvent`) que não compensa pra
single-user.

Implementação:
- Detecção: [calendar_client.find_conflicts](src/calendar_client.py)
- Mover: [calendar_client.update_event_times](src/calendar_client.py)
  (usa `events().patch`, preserva event_id)
- Máquina de estados: [src/conversation.py](src/conversation.py)
- UI (botões + callbacks): [src/bot.py](src/bot.py)

---

## Esquemas de dados

### `ParsedEvent` (saída do parser)

Definido em [src/models.py](src/models.py).

```python
@dataclass(frozen=True)
class ParsedEvent:
    title: str               # ex: "Dentista"
    start: datetime          # com tzinfo, sempre
    end: datetime            # com tzinfo, sempre
    is_all_day: bool         # True se sem hora
    location: str | None     # após @
    notes: str | None        # após #
```

**Contratos:**

- `start` e `end` **sempre** carregam `tzinfo` (vem de `now.tzinfo`).
  Naive datetime aqui = bug.
- Pra all-day, `end` é **exclusivo** (convenção do Google Calendar). Evento
  de 1 dia em 12/07 → `start=12/07 00:00, end=13/07 00:00`.
- `frozen=True` torna a instância imutável — depois de parseada, ninguém
  muta campos.

### `ParseError` (saída do parser em caso de falha)

```python
@dataclass(frozen=True)
class ParseError:
    message: str             # ex: "data inválida"
    detail: str | None       # ex: "30/02 não existe"
```

### `ExistingEvent` (evento lido do calendário, pra detecção de conflito)

```python
@dataclass(frozen=True)
class ExistingEvent:
    summary: str             # título do evento existente
    start: datetime          # com tzinfo
    end: datetime            # com tzinfo
    html_link: str           # link pro evento no Calendar
```

### `state.json` (estado persistido)

```json
{ "last_update_id": 12345678 }
```

Escrita atômica: grava em `state.json.tmp`, depois `os.replace()`. Evita
corromper o arquivo se o processo morrer no meio.

### Corpo do evento na API do Google

Construído por `_build_event_body` em
[src/calendar_client.py](src/calendar_client.py).

```python
# Evento com hora
{
  "summary": "Dentista",
  "location": "Clínica X",            # se houver
  "description": "levar exame",       # se houver
  "start": {
    "dateTime": "2026-05-11T16:00:00-03:00",
    "timeZone": "America/Sao_Paulo",
  },
  "end": {
    "dateTime": "2026-05-11T17:00:00-03:00",
    "timeZone": "America/Sao_Paulo",
  },
}

# Evento all-day
{
  "summary": "Aniversário",
  "start": { "date": "2026-07-12" },
  "end":   { "date": "2026-07-13" },  # exclusivo!
}
```

---

## Componentes

### [src/config.py](src/config.py)
Carrega `.env`, valida vars obrigatórias na importação (falha cedo). Expõe:
`TELEGRAM_BOT_TOKEN`, `ALLOWED_TELEGRAM_USER_ID`, `TIMEZONE`,
`STATE_FILE_PATH`, paths das credenciais do Google.

### [src/models.py](src/models.py)
`ParsedEvent` e `ParseError`. Tipos compartilhados, sem dependências.

### [src/parser.py](src/parser.py)
`parse(text, now) -> ParsedEvent | ParseError`. Recebe a timezone via
`now.tzinfo` (dependency injection — parser não depende de globals,
testável sem `.env`). Estratégia em camadas:

1. Strip + extrair notas (`#`) e local (`@`).
2. Pré-processar palavras relativas (`amanhã`, `domingo`...) → `DD/MM/AAAA`.
   Só roda se não tem DD/MM no texto.
3. Encontrar primeira `DD/MM` ou `DD/MM/AAAA`. Antes = título.
4. Parsear o que sobra: range, hora+duração, hora sozinha (1h default),
   ou nada (all-day).

### [src/calendar_client.py](src/calendar_client.py)
`create_event(parsed)` → cria evento no Calendar primário. Carrega
`token.json`, refresca se expirado, cacheia o `service` por processo
(`build()` é caro).

### [src/state.py](src/state.py)
`load_last_update_id()` / `save_last_update_id(id)`. Escrita atômica via
`os.replace()`. Sem dependências externas.

### [src/bot.py](src/bot.py)
Entrypoint. Não usa a abstração `Application` do `python-telegram-bot`
— loop manual com `bot.get_updates(offset=...)`. Mais simples pra UX
customizada do backlog (silêncio + 1 resumo) e controle direto do offset.

Tem retry com backoff em `NetworkError`. Salva `state.json` após cada
update processado.

### [src/auth_google.py](src/auth_google.py)
Setup OAuth, roda 1x. Usa `InstalledAppFlow.run_local_server(port=0)`
— sobe servidor HTTP local em porta aleatória, abre navegador, recebe o
auth code, troca por `token.json`. Idempotente (rodar de novo só renova
se necessário).

### [src/find_chat_id.py](src/find_chat_id.py)
Setup helper, roda 1x. Lê o token direto do `.env` (não importa
`src.config` porque o objetivo é justamente descobrir o id que falta).
Lista os user_ids das mensagens recentes + faz ack delas pra não virem
como "backlog" quando o bot subir.

---

## Configuração

Todas as variáveis em `.env`:

| Var | Obrigatória | Default | O que é |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | sim | — | Token do bot, vem do BotFather |
| `ALLOWED_TELEGRAM_USER_ID` | sim | — | Seu chat_id (whitelist) |
| `TIMEZONE` | não | `America/Sao_Paulo` | IANA timezone |
| `STATE_FILE_PATH` | não | `state.json` | Onde salvar o offset |

Arquivos esperados em `credentials/`:
- `google_oauth.json` — você baixa do Google Cloud Console.
- `token.json` — gerado pelo `auth_google.py`.

Ambos no `.gitignore`. **Nunca commitar.**

---

## Setup inicial

### 1. Ambiente Python

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> Se o `Activate.ps1` reclamar de execution policy:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

### 2. Telegram

1. No Telegram, fala com [@BotFather](https://t.me/BotFather) → `/newbot`.
2. Copia o token, cola em `TELEGRAM_BOT_TOKEN` no `.env`.
3. Manda qualquer mensagem pro bot pelo Telegram.
4. `python -m src.find_chat_id` → pega seu id → cola em
   `ALLOWED_TELEGRAM_USER_ID`.

### 3. Google Cloud

1. Cria projeto em [console.cloud.google.com](https://console.cloud.google.com/).
2. APIs & Services → Library → habilita **Google Calendar API**.
3. OAuth consent screen → External → preenche o mínimo + adiciona seu
   email como **Test user** (sem isso, OAuth bloqueia).
4. Credentials → Create Credentials → OAuth client ID → **Desktop app**.
5. Baixa o JSON, salva em `credentials/google_oauth.json`.
6. `python -m src.auth_google` → autoriza no navegador → gera
   `credentials/token.json`.

---

## Como rodar

```powershell
python -m src.bot
```

Saída esperada no terminal:

```
... INFO [secretarIA] conectado como @teu_bot (id=...)
... INFO [secretarIA] buscando backlog (offset=None)...
... INFO [secretarIA] sem backlog
... INFO [secretarIA] entrando em modo polling. Ctrl+C pra parar.
```

Ctrl+C pra parar.

---

## Testes

**83 testes** divididos por módulo. Foco em lógica pura — funções que falam
com Telegram/Google em rede são verificadas manualmente no fluxo
end-to-end.

| Arquivo | Cobre | Casos |
|---|---|---|
| [tests/test_parser.py](tests/test_parser.py) | parsing (data numérica, relativa, hora, range, duração, all-day, erros) | 35 |
| [tests/test_conversation.py](tests/test_conversation.py) | máquina de estados (idle → decisão → nova data → idle) | 7 |
| [tests/test_bot_format.py](tests/test_bot_format.py) | formatadores (success, conflito, prompt com botões, backlog summary, HTML escape, truncate) | 28 |
| [tests/test_calendar_client.py](tests/test_calendar_client.py) | construção do body da API (timed vs all-day, end exclusivo, location/notes opcionais) | 13 |

**Rodar tudo:**

```powershell
.\.venv\Scripts\python.exe tests\test_parser.py
.\.venv\Scripts\python.exe tests\test_conversation.py
.\.venv\Scripts\python.exe tests\test_bot_format.py
.\.venv\Scripts\python.exe tests\test_calendar_client.py
```

Ou com pytest (não está em `requirements.txt` mas funciona se instalado):

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ -v
```

**Por que os tests rodam sem `.env`:** `test_parser.py` não depende de
config (timezone vem via `now.tzinfo`). Os outros importam módulos que
chamam `config._required("TELEGRAM_BOT_TOKEN")`, mas no topo do arquivo
fazemos `os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")` antes do
import — então valor dummy passa pelo validador. Em máquinas com `.env`
real, o `setdefault` não sobrescreve.

---

## Roadmap

Próximas iterações possíveis. Sem ordem fixa — deixar o uso real ditar
prioridade.

- **Suporte a Google Tasks** (criar tarefa em vez de evento).
  API separada (`tasks.googleapis.com`), outro scope, novo módulo
  `tasks_client.py`. Sintaxe possível: prefixo `!` ou palavra-chave
  `tarefa:` distinguindo evento de task.
- **Listar / editar / cancelar eventos por mensagem.** Comandos tipo
  "cancela dentista de amanhã" ou "lista próxima semana". Provavelmente
  o item mais útil depois de uma semana de uso real.
- **Deploy em servidor sempre-ligado** (Railway / Fly.io / VPS). Resolve
  o limite de 24h do Telegram. Adiciona complexidade de deploy + custo
  (geralmente free tier serve).
- **Eventos recorrentes** (`Aula toda terça 19:00-21:00`). Mapeia pra
  `RRULE` do Google. Parser precisa entender "toda terça", "todo dia 5".
- **Modo natural language como fallback opcional.** Quando o parser regex
  falhar, manda pro Claude (haiku-4-5) com tool use. Custo ~$0.05/mês.
  Ganho: aceita "dentista lá pelas 4 da tarde amanhã".
- **Múltiplos calendários** (Pessoal / Trabalho / Faculdade). Categorização
  por sufixo `!trabalho` ou tag em `#`. Cores próprias no Google.
- **Mensagem por áudio** (Whisper → texto → fluxo normal). Útil pra
  notas de voz.
- **Lembretes proativos** ("você tem dentista em 1h"). Scheduler que lê
  o calendário e dispara notificações pelo bot.
- **Idempotência do catchup.** Hoje, se o processo crashar entre criar
  evento e salvar `state.json`, na próxima rodada vira evento duplicado.
  Cachear `update_id`s recentes ou checar antes de criar.

---

## Estrutura de arquivos

```
secretarIA/
├── README.md                       # esse arquivo
├── requirements.txt
├── .env.example
├── .env                            # gitignored
├── .gitignore
├── credentials/                    # gitignored
│   ├── google_oauth.json           # baixado do Google Cloud
│   └── token.json                  # gerado pelo auth_google.py
├── state.json                      # gitignored, last_update_id
├── src/
│   ├── __init__.py
│   ├── bot.py                      # entrypoint
│   ├── parser.py                   # texto → ParsedEvent
│   ├── calendar_client.py          # wrapper Google Calendar
│   ├── auth_google.py              # OAuth setup
│   ├── find_chat_id.py             # setup helper
│   ├── state.py                    # last_update_id
│   ├── config.py                   # .env loader
│   └── models.py                   # dataclasses compartilhadas
└── tests/
    └── test_parser.py              # 35 testes do parser
```
