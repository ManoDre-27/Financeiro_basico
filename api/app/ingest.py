"""Ingestao de dados reais.

Precos: multi-fonte e resiliente (cada fonte falha isoladamente):
  - crypto  -> CoinGecko (sem chave)
  - fx      -> Frankfurter / BCE (sem chave)
  - equity/index/commodity -> yfinance (best-effort)
Noticias: feeds RSS.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import feedparser
import httpx
from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import NewsArticle, NewsSource, Price, Security

log = logging.getLogger("ingest")

# Mapa ticker -> id CoinGecko (crypto) para os mais comuns
COINGECKO_IDS = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "SOL-USD": "solana",
    "XRP-USD": "ripple",
    "ADA-USD": "cardano",
    "DOGE-USD": "dogecoin",
    "BNB-USD": "binancecoin",
    "DOT-USD": "polkadot",
    "LTC-USD": "litecoin",
    "MATIC-USD": "matic-network",
    "AVAX-USD": "avalanche-2",
    "LINK-USD": "chainlink",
}


def resolve_coingecko_id(symbol: str) -> str | None:
    """Resolve o id CoinGecko de um ticker cripto (ex: BTC-USD -> bitcoin).

    Usa o mapa fixo; se nao existir, pesquisa na API do CoinGecko pelo simbolo.
    """
    if symbol in COINGECKO_IDS:
        return COINGECKO_IDS[symbol]
    base = symbol.replace("-USD", "").upper()
    try:
        r = httpx.get(
            "https://api.coingecko.com/api/v3/search", params={"query": base}, headers=_UA, timeout=20
        )
        for coin in r.json().get("coins", []):
            if coin.get("symbol", "").upper() == base:
                return coin.get("id")
    except Exception as exc:  # noqa: BLE001
        log.warning("resolve_coingecko_id falhou %s: %s", symbol, exc)
    return None

_UA = {"User-Agent": "Mozilla/5.0 (TerminalInteligenciaGlobal/0.1)"}


def _classify(symbol: str) -> str:
    if symbol.startswith("^"):
        return "index"
    if symbol.endswith("-USD"):
        return "crypto"
    if symbol.endswith("=X"):
        return "fx"
    if symbol.endswith("=F"):
        return "commodity"
    return "equity"


def ensure_securities() -> None:
    with SessionLocal() as db:
        existing = {s.symbol for s in db.scalars(select(Security)).all()}
        for symbol in settings.ticker_list:
            if symbol not in existing:
                klass = _classify(symbol)
                pid = resolve_coingecko_id(symbol) if klass == "crypto" else None
                db.add(Security(symbol=symbol, name=symbol, asset_class=klass, provider_id=pid))
        db.commit()


def add_security(symbol: str) -> dict:
    """Adiciona um mercado novo a watchlist e faz uma ingestao imediata."""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"ok": False, "error": "simbolo vazio"}
    klass = _classify(symbol)
    with SessionLocal() as db:
        if db.scalar(select(Security).where(Security.symbol == symbol)):
            return {"ok": False, "error": "ja existe", "symbol": symbol}
        pid = resolve_coingecko_id(symbol) if klass == "crypto" else None
        if klass == "crypto" and not pid:
            return {"ok": False, "error": "cripto nao encontrada no CoinGecko", "symbol": symbol}
        db.add(Security(symbol=symbol, name=symbol, asset_class=klass, provider_id=pid))
        db.commit()
    ingest_prices()
    return {"ok": True, "symbol": symbol, "asset_class": klass}


def _minute_ts() -> datetime:
    return datetime.now(timezone.utc).replace(second=0, microsecond=0)


def _write_price(db, sec: Security, price: float, prev: float | None, currency: str | None) -> None:
    change_pct = round((price - prev) / prev * 100, 4) if prev else None
    ts = _minute_ts()
    existing = db.scalar(select(Price).where(Price.security_id == sec.id, Price.ts == ts))
    if existing:
        existing.price = price
        existing.prev_close = prev
        existing.change_pct = change_pct
        existing.currency = currency
    else:
        db.add(
            Price(
                security_id=sec.id,
                ts=ts,
                price=price,
                prev_close=prev,
                change_pct=change_pct,
                currency=currency,
            )
        )


def _ingest_crypto(db, secs: list[Security]) -> int:
    ids = {s.symbol: (s.provider_id or COINGECKO_IDS.get(s.symbol)) for s in secs}
    ids = {sym: cid for sym, cid in ids.items() if cid}
    if not ids:
        return 0
    try:
        r = httpx.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ",".join(ids.values()), "vs_currencies": "usd", "include_24hr_change": "true"},
            headers=_UA,
            timeout=20,
        )
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("coingecko falhou: %s", exc)
        return 0
    n = 0
    for sec in secs:
        cid = ids.get(sec.symbol)
        if not cid or cid not in data:
            continue
        price = data[cid].get("usd")
        change = data[cid].get("usd_24h_change")
        if price is None:
            continue
        prev = price / (1 + change / 100) if change is not None else None
        _write_price(db, sec, float(price), prev, "USD")
        n += 1
    return n


def _ingest_fx(db, secs: list[Security]) -> int:
    n = 0
    for sec in secs:
        pair = sec.symbol.replace("=X", "")
        if len(pair) != 6:
            continue
        base, quote = pair[:3], pair[3:]
        try:
            r = httpx.get(
                "https://api.frankfurter.app/latest",
                params={"from": base, "to": quote},
                headers=_UA,
                follow_redirects=True,
                timeout=20,
            )
            rate = r.json().get("rates", {}).get(quote)
        except Exception as exc:  # noqa: BLE001
            log.warning("frankfurter falhou %s: %s", sec.symbol, exc)
            continue
        if rate:
            _write_price(db, sec, float(rate), None, quote)
            n += 1
    return n


def _ingest_yfinance(db, secs: list[Security]) -> int:
    if not secs:
        return 0
    try:
        import yfinance as yf
    except Exception:  # noqa: BLE001
        return 0
    n = 0
    for sec in secs:
        try:
            fi = yf.Ticker(sec.symbol).fast_info
            price = fi.get("last_price")
            prev = fi.get("previous_close")
            if price is None:
                continue
            _write_price(db, sec, float(price), float(prev) if prev else None, fi.get("currency"))
            n += 1
        except Exception as exc:  # noqa: BLE001
            log.info("yfinance sem dados para %s (%s)", sec.symbol, exc)
    return n


def ingest_prices() -> int:
    ensure_securities()
    with SessionLocal() as db:
        secs = db.scalars(select(Security)).all()
        by_class: dict[str, list[Security]] = {}
        for s in secs:
            by_class.setdefault(s.asset_class or "equity", []).append(s)
        written = 0
        written += _ingest_crypto(db, by_class.get("crypto", []))
        written += _ingest_fx(db, by_class.get("fx", []))
        yf_secs = by_class.get("equity", []) + by_class.get("index", []) + by_class.get("commodity", [])
        written += _ingest_yfinance(db, yf_secs)
        db.commit()
    log.info("ingest_prices: %d cotacoes", written)
    return written


def provider_history(sec: Security, days: int = 1) -> list[dict]:
    """Historico real do fornecedor para o grafico (cripto=CoinGecko, fx=Frankfurter)."""
    try:
        if sec.asset_class == "crypto":
            cid = sec.provider_id or COINGECKO_IDS.get(sec.symbol)
            if not cid:
                return []
            r = httpx.get(
                f"https://api.coingecko.com/api/v3/coins/{cid}/market_chart",
                params={"vs_currency": "usd", "days": days},
                headers=_UA,
                timeout=25,
            )
            prices = r.json().get("prices", [])
            return [
                {"ts": datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(), "price": p}
                for ms, p in prices
            ]
        if sec.asset_class == "fx":
            pair = sec.symbol.replace("=X", "")
            if len(pair) != 6:
                return []
            base, quote = pair[:3], pair[3:]
            start = (datetime.now(timezone.utc) - timedelta(days=max(days, 30))).strftime("%Y-%m-%d")
            r = httpx.get(
                f"https://api.frankfurter.app/{start}..",
                params={"from": base, "to": quote},
                headers=_UA,
                follow_redirects=True,
                timeout=25,
            )
            rates = r.json().get("rates", {})
            return [
                {"ts": f"{d}T00:00:00+00:00", "price": v[quote]}
                for d, v in sorted(rates.items())
                if quote in v
            ]
    except Exception as exc:  # noqa: BLE001
        log.warning("provider_history falhou %s: %s", sec.symbol, exc)
    return []


def _parse_dt(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            return datetime(*val[:6], tzinfo=timezone.utc)
    return None


def ingest_news() -> int:
    written = 0
    with SessionLocal() as db:
        for feed_url in settings.feed_list:
            try:
                parsed = feedparser.parse(feed_url)
                src_name = parsed.feed.get("title", feed_url)[:128]
                source = db.scalar(select(NewsSource).where(NewsSource.url == feed_url))
                if not source:
                    source = NewsSource(name=src_name, url=feed_url)
                    db.add(source)
                    db.flush()
                for entry in parsed.entries[:40]:
                    guid = (entry.get("id") or entry.get("link") or "")[:512]
                    if not guid or db.scalar(select(NewsArticle).where(NewsArticle.guid == guid)):
                        continue
                    db.add(
                        NewsArticle(
                            source_id=source.id,
                            guid=guid,
                            title=(entry.get("title") or "")[:1000],
                            link=entry.get("link") or "",
                            summary=(entry.get("summary") or "")[:2000],
                            published_at=_parse_dt(entry),
                        )
                    )
                    written += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("feed falhou %s: %s", feed_url, exc)
        db.commit()
    log.info("ingest_news: %d artigos novos", written)
    return written
