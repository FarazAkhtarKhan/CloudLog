import { ArrowRight, LogIn } from "lucide-react";
import { useState } from "react";
import { ErrorNotice } from "../components/ui";
import { MODE, ROLES } from "../config";
import { signInCognito, signInLocal } from "../lib/auth";

const FEED = [
  ["INFO", "checkout-api", "POST /checkout 201 in 233ms"],
  ["WARN", "database-cluster", "Connection pool usage at 93%  [DB_POOL_SATURATED]"],
  ["ERROR", "order-service", "Query timed out after 5000ms on orders.insert  [DB_QUERY_TIMEOUT]"],
  ["INFO", "payment-gateway", "Card authorised in 182ms"],
  ["WARN", "auth-service", "Login failed for a***@shop.example: bad password  [AUTH_LOGIN_FAILED]"],
  ["CRIT", "database-cluster", "Primary node db-primary-1 unreachable; automatic failover started"],
  ["INFO", "iot-edge-gateway", "MQTT heartbeat from cold-store-03 (4.1°C)"],
];
const TONE = { INFO: "lv-INFO", WARN: "lv-WARNING", ERROR: "lv-ERROR", CRIT: "lv-CRITICAL" };

export default function Login({ onSignedIn }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function cognito(e, p) {
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await signInCognito(e, p));
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <section className="login-art">
        <div className="wordmark" style={{ color: "#fff", padding: 0 }}>
          <img src="/favicon.svg" width="30" height="30" alt="" />
          <span className="wordmark-name">CloudLog</span>
        </div>
        <div>
          <h1>Error detection for cloud logs</h1>
          <p>
            Log files land in S3. A Lambda function checks every line, groups repeated failures into incidents in
            DynamoDB, and pages on-call through SNS when something is critical.
          </p>
        </div>
        <div className="login-feed" aria-hidden="true">
          {FEED.map(([lvl, svc, msg], i) => (
            <div key={i}><span className={TONE[lvl]}>{lvl.padEnd(5)}</span>  {svc.padEnd(17)} {msg}</div>
          ))}
        </div>
      </section>

      <section className="login-form">
        <div>
          <h2>Sign in</h2>
          <p className="muted">
            {MODE === "local"
              ? "Offline emulator. Choose a role; the API enforces what each role may do."
              : "Use your CloudLog account. Tokens are issued by Amazon Cognito."}
          </p>
        </div>
        <ErrorNotice error={error} />

        {MODE === "aws" && (
          <>
            <form className="stack" style={{ gap: 12 }} onSubmit={(e) => { e.preventDefault(); cognito(email, password); }}>
              <label className="field">Email
                <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
              </label>
              <label className="field">Password
                <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
              </label>
              <button type="submit" className="btn btn-primary" disabled={busy}><LogIn size={16} /> {busy ? "Signing in…" : "Sign in"}</button>
            </form>
            <div className="divider">or use a demo account</div>
          </>
        )}

        <div className="role-pick">
          {ROLES.map((r) => (
            <button key={r.role} type="button" className="role-option" disabled={busy}
              onClick={() => (MODE === "local" ? onSignedIn(signInLocal(r.role)) : cognito(r.email, r.password))}>
              <strong>{r.role}</strong>
              <span>{r.can}</span>
              <ArrowRight size={18} aria-hidden="true" />
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
