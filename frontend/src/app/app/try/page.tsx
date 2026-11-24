"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useLoad } from "@/lib/use-load";
import { Alert, Badge, Button, Card, PageHeader, Select, Spinner } from "@/components/ui";
import { api, send } from "@/lib/api";
import { DEMO, type DemoInfo, type VoiceStatus } from "@/lib/demo";
import { label } from "@/lib/format";

type Line = { speaker: string; text: string };
type SimResult = {
  call_id: string;
  simulated: boolean;
  transcript: Line[];
  tools: { tool: string; result: unknown }[];
  outcome: string;
  summary: string | null;
};
type Session = { public_key: string; assistant_id: string; max_call_seconds: number };
// Minimal surface of @vapi-ai/web used here (loaded on demand so other pages stay small).
type VapiClient = {
  start: (assistantId: string) => Promise<unknown>;
  stop: () => Promise<void>;
  on: (event: string, cb: (arg?: unknown) => void) => unknown;
};

function Transcript({ lines }: { lines: Line[] }) {
  if (lines.length === 0) return null;
  return (
    <ol className="mt-4 max-h-96 space-y-2 overflow-y-auto rounded-xl bg-slate-50 p-4 text-sm">
      {lines.map((l, i) => (
        <li key={i}>
          <span
            className={`font-medium ${l.speaker === "caller" || l.speaker === "user" ? "text-slate-700" : "text-navy"}`}
          >
            {l.speaker === "caller" || l.speaker === "user" ? "Caller" : "Receptionist"}:
          </span>{" "}
          {l.text}
        </li>
      ))}
    </ol>
  );
}

function LiveCall({ status, onDone }: { status: VoiceStatus; onDone: () => Promise<void> }) {
  const vapi = useRef<VapiClient | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [state, setState] = useState<"idle" | "connecting" | "live" | "ended">("idle");
  const [lines, setLines] = useState<Line[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
      vapi.current?.stop().catch(() => undefined);
    },
    [],
  );

  async function start() {
    setError(null);
    setLines([]);
    setState("connecting");
    try {
      const s = await send("/api/demo/voice-session", "POST").then((r) => r as Session);
      const { default: Vapi } = await import("@vapi-ai/web");
      const client = new Vapi(s.public_key) as unknown as VapiClient;
      vapi.current = client;
      client.on("call-start", () => setState("live"));
      client.on("call-end", () => {
        setState("ended");
        if (timer.current) clearTimeout(timer.current);
        // The call is recorded by Vapi's end-of-call report; give it a moment.
        setTimeout(() => onDone().catch(() => undefined), 4000);
      });
      client.on("message", (m) => {
        const msg = m as {
          type?: string;
          transcriptType?: string;
          role?: string;
          transcript?: string;
        };
        if (msg?.type === "transcript" && msg.transcriptType === "final" && msg.transcript) {
          setLines((prev) => [
            ...prev,
            { speaker: msg.role ?? "assistant", text: msg.transcript! },
          ]);
        }
      });
      client.on("error", (e) => {
        const text = e instanceof Error ? e.message : JSON.stringify(e ?? "").slice(0, 400);
        setError("The live call failed. You can still use the simulation below.");
        setState("ended");
        send("/api/demo/voice-error", "POST", { message: text }).catch(() => undefined);
      });
      await client.start(s.assistant_id);
      // Belt and braces: the assistant also has maxDurationSeconds set by the server.
      timer.current = setTimeout(
        () => vapi.current?.stop().catch(() => undefined),
        (s.max_call_seconds + 5) * 1000,
      );
    } catch (e) {
      setState("idle");
      setError(e instanceof Error ? e.message : "Could not start the call");
    }
  }

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold text-navy">Talk to the receptionist</h2>
        <Badge tone="green">Live voice</Badge>
      </div>
      <p className="mt-1 text-sm text-slate-600">
        Uses your microphone. Calls end after {Math.round(status.max_call_seconds / 60)} minutes.
        Try: &ldquo;My AC stopped cooling, do you service 77002?&rdquo;
      </p>
      {error && (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="mt-4 flex gap-2">
        {state === "live" || state === "connecting" ? (
          <Button variant="danger" onClick={() => vapi.current?.stop()}>
            {state === "connecting" ? "Connecting…" : "End call"}
          </Button>
        ) : (
          <Button onClick={start}>{state === "ended" ? "Call again" : "Start call"}</Button>
        )}
      </div>
      <Transcript lines={lines} />
      {state === "ended" && !error && (
        <p className="mt-3 text-sm text-slate-600">
          Call finished. It appears in{" "}
          <Link className="text-brand underline" href="/app/calls">
            Call history
          </Link>{" "}
          with its summary, and any lead or callback is saved.
        </p>
      )}
    </Card>
  );
}

function Simulation({ info, onDone }: { info: DemoInfo; onDone: () => Promise<void> }) {
  const keys = Object.keys(info.scenarios);
  const [scenario, setScenario] = useState(keys[0] ?? "repair");
  const [result, setResult] = useState<SimResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setResult((await send("/api/demo/simulate", "POST", { scenario })) as SimResult);
      await onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Simulation failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold text-navy">Simulated call</h2>
        <Badge tone="amber">Simulation · no voice</Badge>
      </div>
      <p className="mt-1 text-sm text-slate-600">
        A scripted caller goes through the real minute-limit check, the receptionist&apos;s tools
        (service area, lead capture, callbacks, emergency rules) and the end-of-call summary. Only
        the voice is simulated, and it uses no voice minutes.
      </p>
      <div className="mt-4 flex flex-wrap items-end gap-2">
        <Select value={scenario} onChange={(e) => setScenario(e.target.value)}>
          {keys.map((k) => (
            <option key={k} value={k}>
              {info.scenarios[k]}
            </option>
          ))}
        </Select>
        <Button onClick={run} disabled={busy}>
          {busy ? "Running…" : "Run simulated call"}
        </Button>
      </div>
      {error && (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      )}
      {result && (
        <>
          <Transcript lines={result.transcript} />
          <div className="mt-4 text-sm">
            <p>
              <span className="font-medium text-navy">Outcome:</span> {label(result.outcome)}
            </p>
            {result.summary && (
              <p className="mt-1 text-slate-700">
                <span className="font-medium text-navy">Summary:</span> {result.summary}
              </p>
            )}
            {result.tools.length > 0 && (
              <p className="mt-1 text-slate-600">
                Tools used: {result.tools.map((t) => label(t.tool)).join(", ")}
              </p>
            )}
            <p className="mt-2 text-slate-600">
              Saved to{" "}
              <Link className="text-brand underline" href="/app/calls">
                Call history
              </Link>{" "}
              and{" "}
              <Link className="text-brand underline" href="/app/leads">
                Leads
              </Link>
              .
            </p>
          </div>
        </>
      )}
    </Card>
  );
}

export default function TryPage() {
  const { data, error, loading, reload } = useLoad(
    () =>
      DEMO
        ? Promise.all([api<DemoInfo>("/public/demo"), api<VoiceStatus>("/api/demo/voice")])
        : Promise.resolve(null),
    [],
  );

  if (!DEMO) return <Alert tone="amber">This page is only available in the public demo.</Alert>;
  if (loading) return <Spinner />;
  if (error || !data) return <Alert>{error ?? "Could not load"}</Alert>;
  const [info, status] = data;
  const load = reload;

  return (
    <>
      <PageHeader
        title="Try the receptionist"
        subtitle="Call Houston Comfort HVAC's AI receptionist from your browser."
      />
      <div className="space-y-6">
        {status.mode === "live" ? (
          <LiveCall status={status} onDone={load} />
        ) : (
          <Alert tone="amber">
            Live voice is unavailable right now: {status.reason} The simulation below runs the same
            receptionist logic without voice.
          </Alert>
        )}
        <Simulation info={info} onDone={load} />
      </div>
    </>
  );
}
