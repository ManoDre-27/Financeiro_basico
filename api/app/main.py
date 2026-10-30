"""Terminal de Inteligencia Global - API (MVP Fase 0/1).

FastAPI + agendador de ingestao. Endpoints:
  GET /health            estado do sistema e data quality
  GET /api/markets       ultima cotacao de cada ativo
  GET /api/news          feed de noticias recente
  POST /api/ingest/run   forca uma ingestao imediata (dev)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func, select

from .ai import (
    AIUnavailable,
    ask_terminal,
    daily_brief,
    company_brief,
    daily_highlights,
    explain_concept,
    fact_check,
    market_impact,
    providers_status,
)
from .config import settings
from .db import IS_SQLITE, SessionLocal, init_db
from .ingest import add_security, ingest_news, ingest_prices
from .models import NewsArticle, NewsSource, Price, Security

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")

scheduler = BackgroundScheduler(timezone="UTC")


def _initial_ingest():
    for fn in (ingest_prices, ingest_news):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            log.warning("ingestao inicial falhou (%s): %s", fn.__name__, exc)


def _generate_daily_brief():
    """Gera e guarda o Daily Brief (chamado pelo agendador ou a pedido)."""
    from .models import Report

    try:
        res = daily_brief()
    except Exception as exc:  # noqa: BLE001
        log.warning("daily_brief automatico falhou: %s", exc)
        return
    with SessionLocal() as db:
        db.add(Report(kind="daily_brief", content=res["brief"], provider=res.get("provider")))
        db.commit()
    log.info("daily_brief guardado")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import threading

    init_db()
    # Primeira ingestao em background para nao bloquear o arranque do servidor.
    threading.Thread(target=_initial_ingest, daemon=True).start()
    scheduler.add_job(ingest_prices, "interval", seconds=settings.market_interval_seconds, id="prices")
    scheduler.add_job(ingest_news, "interval", seconds=settings.news_interval_seconds, id="news")
    # Daily Brief automatico todos os dias as 08:00 (hora do servidor/UTC).
    scheduler.add_job(_generate_daily_brief, "cron", hour=8, minute=0, id="daily_brief")
    scheduler.start()
    log.info("scheduler iniciado (prices=%ss, news=%ss)", settings.market_interval_seconds, settings.news_interval_seconds)
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Terminal de Inteligencia Global", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    with SessionLocal() as db:
        n_prices = db.scalar(select(func.count(Price.id))) or 0
        n_news = db.scalar(select(func.count(NewsArticle.id))) or 0
        last_price = db.scalar(select(func.max(Price.ts)))
        last_news = db.scalar(select(func.max(NewsArticle.ingested_at)))
    return {
        "status": "ok",
        "engine": "sqlite" if IS_SQLITE else "postgres",
        "now": datetime.now(timezone.utc).isoformat(),
        "counts": {"prices": n_prices, "news": n_news},
        "last_ingest": {
            "markets": last_price.isoformat() if last_price else None,
            "news": last_news.isoformat() if last_news else None,
        },
    }


@app.get("/api/markets")
def markets():
    """Ultima cotacao por ativo + tendencia intraday (ultimos ~90 min)."""
    from datetime import datetime, timedelta, timezone

    with SessionLocal() as db:
        latest_ts = (
            select(Price.security_id, func.max(Price.ts).label("mts"))
            .group_by(Price.security_id)
            .subquery()
        )
        rows = db.execute(
            select(Security, Price)
            .join(Price, Price.security_id == Security.id)
            .join(
                latest_ts,
                (latest_ts.c.security_id == Price.security_id) & (latest_ts.c.mts == Price.ts),
            )
            .order_by(Security.asset_class, Security.symbol)
        ).all()

        # Preco de referencia ~90 min atras, para calcular tendencia curta.
        since = datetime.now(timezone.utc) - timedelta(minutes=90)
        ref_rows = db.execute(
            select(Price.security_id, Price.ts, Price.price)
            .where(Price.ts >= since)
            .order_by(Price.security_id, Price.ts)
        ).all()
        first_seen: dict[int, float] = {}
        for sid, _ts, pr in ref_rows:
            first_seen.setdefault(sid, pr)

    out = []
    for sec, price in rows:
        ref = first_seen.get(sec.id)
        if ref and ref != price.price:
            trend = "up" if price.price > ref else "down"
        elif price.change_pct is not None and price.change_pct != 0:
            trend = "up" if price.change_pct > 0 else "down"
        else:
            trend = "flat"
        out.append(
            {
                "symbol": sec.symbol,
                "name": sec.name,
                "asset_class": sec.asset_class,
                "price": price.price,
                "change_pct": price.change_pct,
                "currency": price.currency,
                "trend": trend,
                "ts": price.ts.isoformat(),
            }
        )
    return out


@app.get("/api/reports/daily_brief")
def latest_brief():
    from .models import Report

    with SessionLocal() as db:
        rep = db.scalar(
            select(Report).where(Report.kind == "daily_brief").order_by(Report.created_at.desc()).limit(1)
        )
        if not rep:
            return {"content": None}
        return {"content": rep.content, "provider": rep.provider, "created_at": rep.created_at.isoformat()}


@app.post("/api/reports/daily_brief/generate")
def generate_brief_now():
    _generate_daily_brief()
    return latest_brief()


@app.get("/api/alerts")
def alerts():
    """Alertas por movimento de preco (seccao 6.3). Critico >=5%, Importante >=2%."""
    data = markets()
    out = []
    for m in data:
        chg = m.get("change_pct")
        if chg is None:
            continue
        a = abs(chg)
        if a >= 5:
            level = "critical"
        elif a >= 2:
            level = "important"
        else:
            continue
        out.append(
            {
                "symbol": m["symbol"],
                "asset_class": m["asset_class"],
                "change_pct": chg,
                "price": m["price"],
                "level": level,
                "direction": "up" if chg > 0 else "down",
            }
        )
    out.sort(key=lambda x: -abs(x["change_pct"]))
    return {"alerts": out}


@app.get("/api/markets/{symbol}/history")
def market_history(symbol: str, minutes: int = 1440):
    """Serie temporal de precos (snapshots guardados) para desenhar o grafico."""
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(minutes=min(minutes, 20160))
    with SessionLocal() as db:
        sec = db.scalar(select(Security).where(Security.symbol == symbol.upper()))
        if not sec:
            raise HTTPException(status_code=404, detail="mercado nao encontrado")
        pts = db.execute(
            select(Price.ts, Price.price)
            .where(Price.security_id == sec.id, Price.ts >= since)
            .order_by(Price.ts)
        ).all()
        local = [{"ts": ts.isoformat(), "price": pr} for ts, pr in pts]
        sec_copy = sec  # para uso fora da sessao
    # Poucos snapshots locais? Puxa historico real do fornecedor para o grafico.
    if len(local) < 3:
        from .ingest import provider_history

        days = max(1, min(minutes // 1440, 30))
        remote = provider_history(sec_copy, days=days)
        if len(remote) >= 2:
            return {"symbol": sec_copy.symbol, "points": remote, "source": "provider"}
    return {"symbol": sec_copy.symbol, "points": local, "source": "local"}


class AddMarketBody(BaseModel):
    symbol: str


@app.post("/api/markets/add")
def markets_add(body: AddMarketBody):
    res = add_security(body.symbol)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "falhou"))
    return res


@app.get("/api/news")
def news(limit: int = 30):
    with SessionLocal() as db:
        rows = db.execute(
            select(NewsArticle, NewsSource)
            .join(NewsSource, NewsArticle.source_id == NewsSource.id, isouter=True)
            .order_by(NewsArticle.published_at.desc().nullslast())
            .limit(min(limit, 100))
        ).all()
    return [
        {
            "title": art.title,
            "link": art.link,
            "summary": art.summary,
            "source": src.name if src else None,
            "published_at": art.published_at.isoformat() if art.published_at else None,
        }
        for art, src in rows
    ]


@app.post("/api/ingest/run")
def run_ingest():
    return {"prices": ingest_prices(), "news": ingest_news()}


from .paper import TradeError, get_portfolio, reset_portfolio
from .paper import trade as paper_trade
from .paper import transactions as paper_transactions


@app.get("/api/portfolio")
def portfolio():
    return get_portfolio()


class TradeBody(BaseModel):
    symbol: str
    side: str
    quantity: float


@app.post("/api/portfolio/trade")
def portfolio_trade(body: TradeBody):
    try:
        return paper_trade(body.symbol, body.side, body.quantity)
    except TradeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/portfolio/reset")
def portfolio_reset():
    return reset_portfolio()


@app.get("/api/portfolio/transactions")
def portfolio_transactions():
    return paper_transactions()


class AskBody(BaseModel):
    question: str


@app.get("/api/ai/status")
def ai_status():
    return providers_status()


@app.post("/api/ai/ask")
def ai_ask(body: AskBody):
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Pergunta vazia.")
    try:
        return ask_terminal(q)
    except AIUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("ai_ask falhou")
        raise HTTPException(status_code=500, detail=f"Erro da IA: {exc}") from exc


@app.post("/api/ai/brief")
def ai_brief():
    try:
        return daily_brief()
    except AIUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("ai_brief falhou")
        raise HTTPException(status_code=500, detail=f"Erro da IA: {exc}") from exc


@app.get("/api/ai/highlights")
def ai_highlights():
    try:
        return daily_highlights()
    except AIUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("ai_highlights falhou")
        raise HTTPException(status_code=500, detail=f"Erro da IA: {exc}") from exc


class ClaimBody(BaseModel):
    claim: str


@app.post("/api/ai/factcheck")
def ai_factcheck(body: ClaimBody):
    if not (body.claim or "").strip():
        raise HTTPException(status_code=400, detail="Afirmacao vazia.")
    try:
        return fact_check(body.claim.strip())
    except AIUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Erro da IA: {exc}") from exc


class CompanyBody(BaseModel):
    name: str


@app.post("/api/ai/company")
def ai_company(body: CompanyBody):
    if not (body.name or "").strip():
        raise HTTPException(status_code=400, detail="Nome vazio.")
    try:
        return company_brief(body.name.strip())
    except AIUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Erro da IA: {exc}") from exc


class TopicBody(BaseModel):
    topic: str


@app.post("/api/ai/learn")
def ai_learn(body: TopicBody):
    if not (body.topic or "").strip():
        raise HTTPException(status_code=400, detail="Tema vazio.")
    try:
        return explain_concept(body.topic.strip())
    except AIUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Erro da IA: {exc}") from exc


@app.post("/api/ai/impact")
def ai_impact():
    try:
        return market_impact()
    except AIUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("ai_impact falhou")
        raise HTTPException(status_code=500, detail=f"Erro da IA: {exc}") from exc
