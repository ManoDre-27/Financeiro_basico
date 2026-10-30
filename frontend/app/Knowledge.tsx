"use client";

import { useState } from "react";
import { factCheck, learnConcept } from "@/lib/api";

const TOPICS = [
  "O que é o rácio P/E?",
  "Como funciona um ETF?",
  "Porque é que os juros afetam a tecnologia?",
  "O que é a duration de uma obrigação?",
  "O que é uma stablecoin?",
];

export default function Knowledge({ enabled }: { enabled: boolean }) {
  const [tab, setTab] = useState<"fact" | "learn">("fact");
  const [claim, setClaim] = useState("");
  const [topic, setTopic] = useState("");
  const [out, setOut] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function run(fn: () => Promise<{ answer: string }>) {
    if (busy) return;
    setBusy(true);
    setErr(null);
    setOut("");
    try {
      setOut((await fn()).answer);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "erro");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel kn">
      <h2>Verificar &amp; Aprender</h2>
      <div className="kn-body">
        <div className="kn-tabs">
          <button className={tab === "fact" ? "on" : ""} onClick={() => setTab("fact")}>
            Verificar facto
          </button>
          <button className={tab === "learn" ? "on" : ""} onClick={() => setTab("learn")}>
            Aprender
          </button>
        </div>

        {tab === "fact" ? (
          <div className="kn-controls">
            <input
              type="text"
              placeholder="Afirmação a verificar (ex: o Brent subiu acima de 90 dólares hoje)"
              value={claim}
              onChange={(e) => setClaim(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && claim.trim() && run(() => factCheck(claim.trim()))}
              disabled={busy || !enabled}
            />
            <button onClick={() => run(() => factCheck(claim.trim()))} disabled={busy || !enabled || !claim.trim()}>
              Verificar
            </button>
          </div>
        ) : (
          <>
            <div className="kn-chips">
              {TOPICS.map((t) => (
                <button key={t} onClick={() => run(() => learnConcept(t))} disabled={busy || !enabled}>
                  {t}
                </button>
              ))}
            </div>
            <div className="kn-controls">
              <input
                type="text"
                placeholder="Ou pergunta o teu conceito…"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && topic.trim() && run(() => learnConcept(topic.trim()))}
                disabled={busy || !enabled}
              />
              <button onClick={() => run(() => learnConcept(topic.trim()))} disabled={busy || !enabled || !topic.trim()}>
                Explicar
              </button>
            </div>
          </>
        )}

        {!enabled && <div className="kn-out muted">Ativa uma IA no .env (Groq é grátis) para usar isto.</div>}
        {busy && <div className="kn-out muted">A analisar…</div>}
        {err && <div className="kn-out err">{err}</div>}
        {out && !busy && <div className="kn-out">{out}</div>}
      </div>
    </section>
  );
}
