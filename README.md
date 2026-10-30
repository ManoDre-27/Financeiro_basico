# Terminal de Inteligencia Global

Infraestrutura pessoal de inteligencia: recolhe e analisa noticias, mercados,
macro e geopolitica. **Perceber o mundo primeiro. Tomar decisoes depois.**

Este repositorio e o **MVP (Fase 0/1)** do documento de produto: dashboard +
API + ingestao real de precos e noticias. Cresce por fases.

## Arquitetura (MVP)

```
Fontes reais            API (FastAPI)             Frontend (Next.js)
CoinGecko (crypto)  ->  ingestao agendada     ->  Dashboard
Frankfurter (fx)        PostgreSQL / SQLite        Markets + News
Yahoo (acoes)           /health /api/markets       auto-refresh 30s
RSS (noticias)          /api/news
```

- **Backend**: Python + FastAPI + SQLAlchemy + APScheduler
- **Frontend**: Next.js + TypeScript
- **DB**: PostgreSQL (TimescaleDB + pgvector) em producao; SQLite local em dev
- **Orquestracao**: Docker Compose (portavel para VM Proxmox)

## Correr localmente SEM Docker (rapido, para desenvolver)

Precisa de Python 3.12+ e Node 20+.

**1. Backend** (usa SQLite automaticamente):
```bash
cd api
python -m venv .venv
.venv\Scripts\activate            # Windows (Git Bash: source .venv/Scripts/activate)
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
API em http://localhost:8000 · docs em http://localhost:8000/docs

**2. Frontend** (noutro terminal):
```bash
cd frontend
npm install
npm run dev
```
Dashboard em http://localhost:3000

## Correr com Docker (alvo de producao / Proxmox)

```bash
cp .env.example .env      # edita a password
docker compose up -d --build
```
- Dashboard: http://localhost:3000
- API: http://localhost:8000
- n8n: http://localhost:5678

Na VM Proxmox: `docker compose up -d --build` e publica **apenas** frontend/api
via `tailscale serve`. Postgres, Redis e n8n ficam internos (ver seccao 9 do doc).

## Fontes de dados (gratuitas, sem chave)

| Classe      | Fonte        | Notas |
| ----------- | ------------ | ----- |
| Crypto      | CoinGecko    | preco + variacao 24h |
| Cambio (FX) | Frankfurter  | taxas do BCE |
| Acoes/indices/commodities | yfinance | best-effort; pode ser bloqueado por IP |
| Noticias    | RSS          | BBC, FT, CNN, Reuters |

## Inteligencia (Claude)

O dashboard tem um painel de IA: **Ask Terminal** (perguntas em portugues) e
**Resumo do dia**. Responde apenas com base nas noticias e cotacoes reais, com
fontes e nivel de confianca. Nao da conselhos de investimento.

Multi-provedor com **fallback automatico** (`AI_PROVIDER=auto`): tenta pela ordem
Anthropic -> Groq -> OpenAI -> Gemini. Basta configurar UMA chave no `.env`; se
uma falhar (ex: sem creditos), passa a seguinte automaticamente.

Opcao **gratuita recomendada**: Groq (rapido, sem cartao).
```
GROQ_API_KEY=gsk_...            # https://console.groq.com/keys
```
Outras: `ANTHROPIC_API_KEY` (pago), `OPENAI_API_KEY` (+ `OPENAI_BASE_URL` p/ OpenRouter),
`GEMINI_API_KEY` (free tier, https://aistudio.google.com/apikey).

Nao existe "sem limite de tokens" — `AI_MAX_TOKENS` e o maximo por resposta.
Endpoints: `GET /api/ai/status` · `POST /api/ai/ask` · `/api/ai/brief` · `/api/ai/impact`.

## Estado atual

- [x] Fase 0 — scaffold, docker-compose, health checks
- [x] Fase 1 — ingestao real (precos crypto/fx + noticias), dashboard
- [x] IA multi-provedor (Groq/Anthropic/OpenAI/Gemini) com fallback
- [x] Ask Terminal, Resumo do dia, Leitura do dia (impacto), Destaques (pop-ups)
- [x] Mercados: tendencia, grafico (sparkline), adicionar mercados
- [x] Paper Trading (carteira virtual 10.000 EUR) — seccao 11.2
- [x] Alertas por movimento + Daily Brief automatico (08:00) — seccoes 6.3/6.4
- [x] Fact Checker + Learning Center — seccoes 4.2/11.4
- [x] Company Intelligence (dossier qualitativo) — seccao 4.4
- [ ] Fase seguinte — clustering de noticias, Event Graph, Quant/backtesting
- [ ] Fase 3 — cobertura de mercado alargada + graficos
- [ ] ... (ver seccao 12 do documento de produto)

## Proximo passo sugerido

Ligar o **Claude API** para o pipeline de News Intelligence (deduplicacao ->
clustering -> analise com fontes e nivel de confianca), conforme a Fase 2.
