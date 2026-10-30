"use client";

import { useEffect, useState } from "react";
import {
  getPortfolio,
  resetPortfolio,
  tradePortfolio,
  type Portfolio,
} from "@/lib/api";

export default function PaperTrading({ symbols }: { symbols: string[] }) {
  const [pf, setPf] = useState<Portfolio | null>(null);
  const [symbol, setSymbol] = useState("");
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [qty, setQty] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    try {
      setPf(await getPortfolio());
    } catch {
      /* silencioso */
    }
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (!symbol && symbols.length) setSymbol(symbols[0]);
  }, [symbols, symbol]);

  async function doTrade() {
    const q = parseFloat(qty);
    if (!symbol || !q || q <= 0 || busy) return;
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      await tradePortfolio(symbol, side, q);
      setMsg(`${side === "buy" ? "Comprado" : "Vendido"}: ${q} ${symbol}`);
      setQty("");
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "falhou");
    } finally {
      setBusy(false);
    }
  }

  async function doReset() {
    if (!confirm("Repor a carteira a 10.000€ e apagar todas as transações?")) return;
    await resetPortfolio();
    await load();
    setMsg("Carteira reposta.");
  }

  const money = (n: number) =>
    n.toLocaleString("pt-PT", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const pnlClass = (n: number) => (n > 0 ? "up" : n < 0 ? "down" : "flat");

  return (
    <section className="panel pt">
      <h2>
        Carteira (Paper Trading)
        <span className="pt-note"> · simulação com 10.000€ virtuais</span>
      </h2>
      <div className="pt-body">
        {pf && (
          <div className="pt-summary">
            <div className="pt-kpi">
              <span className="k">Saldo</span>
              <span className="v">{money(pf.cash)} €</span>
            </div>
            <div className="pt-kpi">
              <span className="k">Investido</span>
              <span className="v">{money(pf.holdings_value)} €</span>
            </div>
            <div className="pt-kpi">
              <span className="k">Total</span>
              <span className="v">{money(pf.total_value)} €</span>
            </div>
            <div className="pt-kpi">
              <span className="k">Lucro / Prejuízo</span>
              <span className={`v ${pnlClass(pf.total_pnl)}`}>
                {pf.total_pnl >= 0 ? "+" : ""}
                {money(pf.total_pnl)} € ({pf.total_pnl_pct >= 0 ? "+" : ""}
                {pf.total_pnl_pct}%)
              </span>
            </div>
          </div>
        )}

        <div className="pt-trade">
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)} disabled={busy}>
            {symbols.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select value={side} onChange={(e) => setSide(e.target.value as "buy" | "sell")} disabled={busy}>
            <option value="buy">Comprar</option>
            <option value="sell">Vender</option>
          </select>
          <input
            type="number"
            step="any"
            min="0"
            placeholder="Quantidade"
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && doTrade()}
            disabled={busy}
          />
          <button onClick={doTrade} disabled={busy || !qty}>
            {busy ? "…" : "Executar"}
          </button>
          <button className="reset" onClick={doReset} disabled={busy} title="Repor carteira">
            Repor
          </button>
        </div>
        {msg && <div className="pt-msg">{msg}</div>}
        {err && <div className="pt-msg err">{err}</div>}

        {pf && pf.positions.length > 0 ? (
          <table className="pt-table">
            <thead>
              <tr>
                <th>Ativo</th>
                <th className="num">Qtd.</th>
                <th className="num">Custo médio</th>
                <th className="num">Preço</th>
                <th className="num">Valor</th>
                <th className="num">L/P</th>
              </tr>
            </thead>
            <tbody>
              {pf.positions.map((p) => (
                <tr key={p.symbol}>
                  <td>{p.symbol}</td>
                  <td className="num">{p.quantity}</td>
                  <td className="num">{money(p.avg_cost)}</td>
                  <td className="num">{p.price !== null ? money(p.price) : "—"}</td>
                  <td className="num">{money(p.market_value)} €</td>
                  <td className={`num ${pnlClass(p.pnl)}`}>
                    {p.pnl >= 0 ? "+" : ""}
                    {money(p.pnl)} €{p.pnl_pct !== null ? ` (${p.pnl_pct}%)` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="pt-empty">Sem posições. Compra um ativo acima para começar.</div>
        )}
      </div>
    </section>
  );
}
