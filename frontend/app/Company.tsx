"use client";

import { useState } from "react";
import { companyBrief } from "@/lib/api";

const PRESETS = ["Mota-Engil", "Apple", "Tesla", "NVIDIA", "Microsoft", "Galp", "EDP"];

export default function Company({ enabled }: { enabled: boolean }) {
  const [name, setName] = useState("");
  const [out, setOut] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function run(n: string) {
    if (!n.trim() || busy) return;
    setBusy(true);
    setErr(null);
    setOut("");
    try {
      setOut((await companyBrief(n.trim())).answer);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "erro");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel co">
      <h2>
        Empresas
        <span className="co-note"> · análise qualitativa (não são dados financeiros ao vivo)</span>
      </h2>
      <div className="co-body">
        <div className="kn-chips">
          {PRESETS.map((p) => (
            <button key={p} onClick={() => run(p)} disabled={busy || !enabled}>
              {p}
            </button>
          ))}
        </div>
        <div className="kn-controls">
          <input
            type="text"
            placeholder="Nome da empresa (ex: Amazon, BYD, Sonae…)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run(name)}
            disabled={busy || !enabled}
          />
          <button onClick={() => run(name)} disabled={busy || !enabled || !name.trim()}>
            Analisar
          </button>
        </div>
        {!enabled && <div className="kn-out muted">Ativa uma IA no .env (Groq é grátis) para usar isto.</div>}
        {busy && <div className="kn-out muted">A preparar o dossier…</div>}
        {err && <div className="kn-out err">{err}</div>}
        {out && !busy && <div className="kn-out">{out}</div>}
      </div>
    </section>
  );
}
