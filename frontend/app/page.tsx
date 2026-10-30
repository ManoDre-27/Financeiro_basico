"use client";

import React, { useEffect, useState } from "react";
import PaperTrading from "./PaperTrading";
import Knowledge from "./Knowledge";
import Company from "./Company";
import {
  askTerminal,
  generateBrief,
  addMarket,
  generateImpact,
  getAIStatus,
  getHealth,
  getHighlights,
  generateStoredBrief,
  getMarketHistory,
  getMarkets,
  getNews,
  getStoredBrief,
  type Health,
  type Highlight,
  type HistoryPoint,
  type Market,
  type NewsItem,
} from "@/lib/api";

function Sparkline({ points }: { points: HistoryPoint[] }) {
  if (points.length < 2) {
    return <div className="spark-empty">Ainda a recolher histórico (aguarda alguns minutos).</div>;
  }
  const w = 560;
  const h = 120;
  const pad = 6;
  const vals = points.map((p) => p.price);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const x = (i: number) => pad + (i / (points.length - 1)) * (w - 2 * pad);
  const y = (v: number) => pad + (1 - (v - min) / span) * (h - 2 * pad);
  const d = points.map((p, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(p.price).toFixed(1)}`).join(" ");
  const up = vals[vals.length - 1] >= vals[0];
  const color = up ? "var(--up)" : "var(--down)";
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="spark" preserveAspectRatio="none">
      <path d={`${d} L ${x(points.length - 1)} ${h - pad} L ${x(0)} ${h - pad} Z`} fill={color} opacity="0.08" />
      <path d={d} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

function fmtPrice(m: Market): string {
  const d = m.asset_class === "fx" ? 4 : m.price < 10 ? 4 : 2;
  return m.price.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

function Change({ pct }: { pct: number | null }) {
  if (pct === null || pct === undefined) return <span className="flat">—</span>;
  const cls = pct > 0 ? "up" : pct < 0 ? "down" : "flat";
  const arrow = pct > 0 ? "▲" : pct < 0 ? "▼" : "▬";
  return (
    <span className={cls}>
      {arrow} {Math.abs(pct).toFixed(2)}%
    </span>
  );
}

function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export default function Dashboard() {
  const [markets, setMarkets] = useState<Market[]>([]);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Grafico + adicionar mercado
  const [expanded, setExpanded] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [histBusy, setHistBusy] = useState(false);
  const [newSymbol, setNewSymbol] = useState("");
  const [addBusy, setAddBusy] = useState(false);
  const [addMsg, setAddMsg] = useState<string | null>(null);

  // Brief do dia guardado
  const [brief, setBrief] = useState<{ content: string | null; created_at?: string } | null>(null);
  const [briefBusy, setBriefBusy] = useState(false);

  async function loadBrief() {
    try {
      setBrief(await getStoredBrief());
    } catch {
      /* silencioso */
    }
  }
  async function genBrief() {
    if (briefBusy) return;
    setBriefBusy(true);
    try {
      setBrief(await generateStoredBrief());
    } catch {
      /* silencioso */
    } finally {
      setBriefBusy(false);
    }
  }

  async function toggleChart(symbol: string) {
    if (expanded === symbol) {
      setExpanded(null);
      return;
    }
    setExpanded(symbol);
    setHistory([]);
    setHistBusy(true);
    try {
      const r = await getMarketHistory(symbol, 1440);
      setHistory(r.points);
    } catch {
      setHistory([]);
    } finally {
      setHistBusy(false);
    }
  }

  async function doAddMarket() {
    const s = newSymbol.trim();
    if (!s || addBusy) return;
    setAddBusy(true);
    setAddMsg(null);
    try {
      const r = await addMarket(s);
      setAddMsg(`Adicionado: ${r.symbol} (${r.asset_class})`);
      setNewSymbol("");
      await load();
    } catch (e) {
      setAddMsg(e instanceof Error ? e.message : "não foi possível adicionar");
    } finally {
      setAddBusy(false);
    }
  }

  // IA
  const [aiEnabled, setAiEnabled] = useState<boolean | null>(null);
  const [aiAvailable, setAiAvailable] = useState<string[]>([]);
  const [question, setQuestion] = useState("");
  const [aiOutput, setAiOutput] = useState("");
  const [aiProvider, setAiProvider] = useState<string | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);

  // Pop-ups de destaques
  const [highlights, setHighlights] = useState<Highlight[]>([]);
  const [hlBusy, setHlBusy] = useState(false);
  const [hlLoaded, setHlLoaded] = useState(false);

  async function loadHighlights() {
    if (hlBusy) return;
    setHlBusy(true);
    try {
      const r = await getHighlights();
      setHighlights(r.highlights || []);
    } catch {
      /* silencioso: os pop-ups sao opcionais */
    } finally {
      setHlBusy(false);
      setHlLoaded(true);
    }
  }

  function dismissHighlight(i: number) {
    setHighlights((hs) => hs.filter((_, idx) => idx !== i));
  }

  async function runAI(fn: () => Promise<{ text: string; provider: string }>) {
    if (aiBusy) return;
    setAiBusy(true);
    setAiError(null);
    setAiOutput("");
    setAiProvider(null);
    try {
      const r = await fn();
      setAiOutput(r.text);
      setAiProvider(r.provider);
    } catch (e) {
      setAiError(e instanceof Error ? e.message : "erro da IA");
    } finally {
      setAiBusy(false);
    }
  }

  const doAsk = () =>
    question.trim() &&
    runAI(async () => {
      const r = await askTerminal(question.trim());
      return { text: r.answer, provider: r.provider };
    });
  const doBrief = () =>
    runAI(async () => {
      const r = await generateBrief();
      return { text: r.brief, provider: r.provider };
    });
  const doImpact = () =>
    runAI(async () => {
      const r = await generateImpact();
      return { text: r.impact, provider: r.provider };
    });

  async function load() {
    try {
      const [m, n, h] = await Promise.all([getMarkets(), getNews(), getHealth()]);
      setMarkets(m);
      setNews(n);
      setHealth(h);
      setError(null);
      if (aiEnabled === null) {
        try {
          const s = await getAIStatus();
          setAiEnabled(s.enabled);
          setAiAvailable(s.available);
        } catch {
          setAiEnabled(false);
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "erro desconhecido");
    }
  }

  useEffect(() => {
    load();
    loadBrief();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, []);

  // Alertas calculados dos mercados (movimento >= 2%).
  const alerts = markets
    .filter((m) => m.change_pct !== null && Math.abs(m.change_pct) >= 2)
    .sort((a, b) => Math.abs(b.change_pct!) - Math.abs(a.change_pct!));

  // Assim que a IA estiver confirmada como ativa, mostra os pop-ups uma vez
  // e depois regenera-os a cada 15 min para acompanhar as noticias novas.
  useEffect(() => {
    if (!aiEnabled) return;
    if (!hlLoaded && !hlBusy) loadHighlights();
    const id = setInterval(loadHighlights, 15 * 60 * 1000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aiEnabled]);

  return (
    <div className="wrap">
      <header className="top">
        <div>
          <h1>TERMINAL DE INTELIGÊNCIA</h1>
          <div className="sub">Perceber o mundo primeiro. Tomar decisões depois.</div>
        </div>
        <div className="status">
          {health && (
            <>
              <span>
                <span className={`dot ${error ? "red" : "green"}`} />
                {health.engine.toUpperCase()}
              </span>
              <span>MARKETS {health.counts.prices}</span>
              <span>NEWS {health.counts.news}</span>
              <span>atualizado há {timeAgo(health.last_ingest.news)}</span>
            </>
          )}
        </div>
      </header>

      {error && <div className="err">API indisponível: {error} — confirma que o backend está em :8000</div>}

      {alerts.length > 0 && (
        <div className="alerts-bar">
          <span className="alerts-label">ALERTAS</span>
          {alerts.map((m) => {
            const crit = Math.abs(m.change_pct!) >= 5;
            return (
              <span key={m.symbol} className={`alert-pill ${crit ? "crit" : "imp"}`}>
                {m.change_pct! > 0 ? "▲" : "▼"} {m.symbol} {Math.abs(m.change_pct!).toFixed(1)}%
              </span>
            );
          })}
        </div>
      )}

      <section className="panel ai">
        <h2>
          Inteligência
          {aiEnabled && aiAvailable.length > 0 && (
            <span className="ai-on"> · {aiAvailable.join(" → ")}</span>
          )}
          {aiEnabled === false && (
            <span className="ai-off"> · desativada (configura uma chave no .env: Groq é grátis)</span>
          )}
        </h2>
        <div className="ai-body">
          <div className="ai-controls">
            <input
              type="text"
              placeholder="Pergunta ao terminal (ex: o que está a mover os mercados hoje?)"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && doAsk()}
              disabled={aiBusy || aiEnabled === false}
            />
            <button onClick={doAsk} disabled={aiBusy || aiEnabled === false || !question.trim()}>
              Perguntar
            </button>
            <button className="secondary" onClick={doBrief} disabled={aiBusy || aiEnabled === false}>
              Resumo do dia
            </button>
            <button className="secondary" onClick={doImpact} disabled={aiBusy || aiEnabled === false}>
              Leitura do dia (impacto)
            </button>
            <button className="secondary" onClick={loadHighlights} disabled={hlBusy || aiEnabled === false}>
              {hlBusy ? "A gerar destaques…" : "Destaques (pop-ups)"}
            </button>
          </div>
          {aiBusy && <div className="ai-out muted">A analisar com os dados reais…</div>}
          {aiError && <div className="ai-out err">{aiError}</div>}
          {aiOutput && !aiBusy && (
            <div className="ai-out">
              {aiProvider && <div className="ai-tag">resposta via {aiProvider}</div>}
              {aiOutput}
            </div>
          )}
          {!aiOutput && !aiBusy && !aiError && (
            <div className="ai-out muted">
              A IA responde em português, apenas com base nas notícias e cotações reais acima, com fontes e nível de confiança.
            </div>
          )}
        </div>
      </section>

      <div className="grid">
        <section className="panel">
          <h2>Mercados</h2>
          {markets.length === 0 ? (
            <div className="err" style={{ color: "var(--muted)" }}>
              Sem cotações ainda. (Cripto e câmbio chegam primeiro; ações dependem do acesso ao Yahoo.)
            </div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Ativo</th>
                  <th>Classe</th>
                  <th className="num">Preço</th>
                  <th className="num">24h / Δ</th>
                  <th>Tend.</th>
                </tr>
              </thead>
              <tbody>
                {markets.map((m) => (
                  <React.Fragment key={m.symbol}>
                    <tr className="mkt-row" onClick={() => toggleChart(m.symbol)}>
                      <td>
                        <span className="chev">{expanded === m.symbol ? "▾" : "▸"}</span> {m.symbol}
                      </td>
                      <td className="klass">{m.asset_class}</td>
                      <td className="num">
                        {fmtPrice(m)} {m.currency}
                      </td>
                      <td className="num">
                        <Change pct={m.change_pct} />
                      </td>
                      <td className={m.trend}>
                        {m.trend === "up" ? "▲" : m.trend === "down" ? "▼" : "▬"}
                      </td>
                    </tr>
                    {expanded === m.symbol && (
                      <tr className="chart-row">
                        <td colSpan={5}>
                          {histBusy ? (
                            <div className="spark-empty">A carregar gráfico…</div>
                          ) : (
                            <Sparkline points={history} />
                          )}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          )}
          <div className="add-market">
            <input
              type="text"
              placeholder="Adicionar mercado (ex: SOL-USD, USDCAD=X, AAPL)"
              value={newSymbol}
              onChange={(e) => setNewSymbol(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && doAddMarket()}
              disabled={addBusy}
            />
            <button onClick={doAddMarket} disabled={addBusy || !newSymbol.trim()}>
              {addBusy ? "A adicionar…" : "Adicionar"}
            </button>
          </div>
          {addMsg && <div className="add-msg">{addMsg}</div>}
        </section>

        <section className="panel">
          <h2>Notícias</h2>
          {news.length === 0 ? (
            <div className="err" style={{ color: "var(--muted)" }}>Sem notícias ainda.</div>
          ) : (
            news.map((n, i) => (
              <div className="news-item" key={i}>
                <div className="title">
                  <a href={n.link} target="_blank" rel="noreferrer">
                    {n.title}
                  </a>
                </div>
                <div className="meta">
                  {n.source || "?"} · há {timeAgo(n.published_at)}
                </div>
              </div>
            ))
          )}
        </section>
      </div>

      <PaperTrading symbols={markets.map((m) => m.symbol)} />

      <Knowledge enabled={aiEnabled === true} />

      <Company enabled={aiEnabled === true} />

      <section className="panel brief">
        <h2>
          Brief do dia
          {brief?.created_at && (
            <span className="brief-time"> · gerado {new Date(brief.created_at).toLocaleString("pt-PT")}</span>
          )}
          <button className="brief-gen" onClick={genBrief} disabled={briefBusy || aiEnabled === false}>
            {briefBusy ? "A gerar…" : "Gerar agora"}
          </button>
        </h2>
        <div className="brief-body">
          {brief?.content ? (
            <div className="brief-out">{brief.content}</div>
          ) : (
            <div className="brief-empty">
              Ainda não há brief. É gerado automaticamente às 08:00, ou carrega em &quot;Gerar agora&quot;.
            </div>
          )}
        </div>
      </section>

      {highlights.length > 0 && (
        <div className="toasts">
          <div className="toasts-head">
            <span>Destaques de hoje</span>
            <button onClick={() => setHighlights([])} title="Fechar todos">
              ✕
            </button>
          </div>
          <div className="toasts-list">
          {highlights.map((h, i) => (
            <div key={i} className={`toast ${h.tipo === "risco" ? "risco" : "oport"}`}>
              <button className="toast-x" onClick={() => dismissHighlight(i)} title="Dispensar">
                ✕
              </button>
              <div className="toast-top">
                <span className="badge">{h.tipo === "risco" ? "RISCO" : "OPORTUNIDADE"}</span>
                {h.direcao && <span className="dir">{h.direcao}</span>}
                {h.confianca && <span className="conf">[{h.confianca}]</span>}
              </div>
              <div className="toast-title">{h.titulo}</div>
              {h.mercado && (
                <div className={`toast-market ${h.direcao.includes("desc") ? "down" : h.direcao.includes("sub") ? "up" : "flat"}`}>
                  {h.mercado} {h.direcao.includes("desc") ? "▼" : h.direcao.includes("sub") ? "▲" : "▬"} {h.direcao}
                </div>
              )}
              {h.porque && <div className="toast-why">{h.porque}</div>}
              {h.fontes?.length > 0 && <div className="toast-src">Fontes: {h.fontes.join(", ")}</div>}
            </div>
          ))}
          </div>
          <div className="toasts-foot">Sinais para analisares — não é conselho de investimento.</div>
        </div>
      )}
    </div>
  );
}
