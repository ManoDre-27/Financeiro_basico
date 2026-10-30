"""Paper Trading (seccao 11.2 do documento): carteira virtual de 10.000 EUR.

Compra/venda dos ativos reais do terminal ao ultimo preco conhecido. Calcula
posicoes, custo medio, valor de mercado e lucro/prejuizo. Tudo simulado.
"""
from __future__ import annotations

from sqlalchemy import func, select

from .db import SessionLocal
from .models import Portfolio, Price, Security, Transaction


class TradeError(Exception):
    pass


def _get_or_create_portfolio(db) -> Portfolio:
    pf = db.scalar(select(Portfolio).order_by(Portfolio.id).limit(1))
    if not pf:
        pf = Portfolio(name="Carteira", cash=10000.0, initial_cash=10000.0)
        db.add(pf)
        db.commit()
        db.refresh(pf)
    return pf


def _latest_price(db, symbol: str) -> tuple[Security, float] | None:
    sec = db.scalar(select(Security).where(Security.symbol == symbol.upper()))
    if not sec:
        return None
    price = db.scalar(
        select(Price.price).where(Price.security_id == sec.id).order_by(Price.ts.desc()).limit(1)
    )
    if price is None:
        return None
    return sec, float(price)


def _positions(db, portfolio_id: int) -> dict[str, dict]:
    """Posicoes liquidas por simbolo (custo medio ponderado)."""
    txs = db.scalars(
        select(Transaction).where(Transaction.portfolio_id == portfolio_id).order_by(Transaction.ts)
    ).all()
    pos: dict[str, dict] = {}
    for t in txs:
        p = pos.setdefault(t.symbol, {"qty": 0.0, "cost": 0.0})
        if t.side == "buy":
            p["qty"] += t.quantity
            p["cost"] += t.quantity * t.price
        else:  # sell: reduz quantidade e custo proporcionalmente (custo medio)
            if p["qty"] > 0:
                avg = p["cost"] / p["qty"]
                p["qty"] -= t.quantity
                p["cost"] -= avg * t.quantity
                if p["qty"] < 1e-9:
                    p["qty"], p["cost"] = 0.0, 0.0
    return {s: v for s, v in pos.items() if v["qty"] > 1e-9}


def get_portfolio() -> dict:
    with SessionLocal() as db:
        pf = _get_or_create_portfolio(db)
        pos = _positions(db, pf.id)
        rows = []
        holdings_value = 0.0
        for symbol, p in pos.items():
            lp = _latest_price(db, symbol)
            price = lp[1] if lp else None
            avg = p["cost"] / p["qty"] if p["qty"] else 0.0
            mkt = price * p["qty"] if price else 0.0
            holdings_value += mkt
            pnl = (price - avg) * p["qty"] if price else 0.0
            rows.append(
                {
                    "symbol": symbol,
                    "quantity": round(p["qty"], 8),
                    "avg_cost": round(avg, 4),
                    "price": round(price, 4) if price else None,
                    "market_value": round(mkt, 2),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round((price - avg) / avg * 100, 2) if price and avg else None,
                }
            )
        total = pf.cash + holdings_value
        return {
            "cash": round(pf.cash, 2),
            "initial_cash": pf.initial_cash,
            "holdings_value": round(holdings_value, 2),
            "total_value": round(total, 2),
            "total_pnl": round(total - pf.initial_cash, 2),
            "total_pnl_pct": round((total - pf.initial_cash) / pf.initial_cash * 100, 2),
            "positions": sorted(rows, key=lambda r: -r["market_value"]),
        }


def trade(symbol: str, side: str, quantity: float) -> dict:
    side = side.lower().strip()
    if side not in ("buy", "sell"):
        raise TradeError("lado invalido (buy/sell)")
    if quantity <= 0:
        raise TradeError("quantidade tem de ser positiva")
    with SessionLocal() as db:
        pf = _get_or_create_portfolio(db)
        lp = _latest_price(db, symbol)
        if not lp:
            raise TradeError("mercado sem cotacao (adiciona-o primeiro na aba Mercados)")
        sec, price = lp
        cost = price * quantity
        if side == "buy":
            if cost > pf.cash + 1e-9:
                raise TradeError(f"saldo insuficiente: precisas de {cost:.2f}, tens {pf.cash:.2f}")
            pf.cash -= cost
        else:
            held = _positions(db, pf.id).get(sec.symbol, {}).get("qty", 0.0)
            if quantity > held + 1e-9:
                raise TradeError(f"nao tens {quantity} de {sec.symbol} (tens {held:.6f})")
            pf.cash += cost
        db.add(
            Transaction(portfolio_id=pf.id, symbol=sec.symbol, side=side, quantity=quantity, price=price)
        )
        db.commit()
    return {"ok": True, "symbol": sec.symbol, "side": side, "quantity": quantity, "price": round(price, 4)}


def reset_portfolio() -> dict:
    with SessionLocal() as db:
        pf = _get_or_create_portfolio(db)
        db.query(Transaction).filter(Transaction.portfolio_id == pf.id).delete()
        pf.cash = pf.initial_cash
        db.commit()
    return {"ok": True, "cash": pf.initial_cash}


def transactions(limit: int = 50) -> list[dict]:
    with SessionLocal() as db:
        pf = _get_or_create_portfolio(db)
        txs = db.scalars(
            select(Transaction)
            .where(Transaction.portfolio_id == pf.id)
            .order_by(Transaction.ts.desc())
            .limit(limit)
        ).all()
        return [
            {
                "symbol": t.symbol,
                "side": t.side,
                "quantity": t.quantity,
                "price": t.price,
                "ts": t.ts.isoformat(),
            }
            for t in txs
        ]
