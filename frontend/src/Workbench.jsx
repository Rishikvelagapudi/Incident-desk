import { useEffect, useRef, useState } from "react";
import { api, AuthError, REVIEW_LABEL } from "./api";
import { useFeed } from "./useFeed";
import { CommandEmblem } from "./CommandEmblem.jsx";
import { LiveClock } from "./CommandTicker.jsx";

const ACTIONS = [
  ["confirm_incident", "Confirm incident", "btn"],
  ["confirm_emergency", "Confirm emergency", "btn btn-danger"],
  ["not_emergency", "Not an emergency", "btn"],
  ["request_review", "Request further review", "btn"],
];
const PHASE = { pre: "Before", event: "Detection", post: "After" };

export default function Workbench({ id, user, navigate }) {
  const { cameras, incidents } = useFeed();
  const [fetched, setFetched] = useState(null);
  const [error, setError] = useState("");
  const [selId, setSelId] = useState(null);
  const [zoom, setZoom] = useState(null);
  const [compare, setCompare] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [integrity, setIntegrity] = useState(null);
  const [summary, setSummary] = useState(null);
  const [sendingEmail, setSendingEmail] = useState(false);
  const [emailFeedback, setEmailFeedback] = useState("");
  const video = useRef(null);

  const handleSendEmail = async () => {
    if (!inc?.id) return;
    setSendingEmail(true);
    setEmailFeedback("");
    try {
      const res = await api(`/api/incidents/${inc.id}/email`, { method: "POST" });
      if (res.status === "sent") {
        setEmailFeedback(`✓ Email delivered successfully to ${res.to}`);
      } else if (res.status === "logged") {
        setEmailFeedback(`📁 Saved to outbox (${res.detail})`);
      } else {
        setEmailFeedback(`⚠️ Failed: ${res.detail || "Could not deliver email"}`);
      }
    } catch (err) {
      setEmailFeedback(`⚠️ Error: ${err.message}`);
    } finally {
      setSendingEmail(false);
    }
  };

  const guard = (e) => setError(e.message);
  useEffect(() => { 
    api(`/api/incidents/${id}`).then((data) => {
      setFetched(data);
    }).catch(guard); 
  }, [id]);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && setZoom(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const inc = incidents[id] || fetched;
  if (error && !inc) return <Shell navigate={navigate} user={user}><p className="form-error">{error}</p></Shell>;
  if (!inc) return <Shell navigate={navigate} user={user}><p className="muted">Loading incident…</p></Shell>;

  const frames = [...inc.evidence].sort((a, b) => a.video_ts - b.video_ts);
  const sel = frames.find((f) => f.frame_id === selId) || frames.find((f) => f.phase === "event") || frames[0];
  const src = cameras[inc.camera_id]?.video_url || `/api/videos/${inc.camera_id}`;
  const seek = (t, play = false) => {
    const v = video.current;
    if (!v) return;
    v.currentTime = Math.max(0, t);
    play ? v.play().catch(() => {}) : v.pause();
  };
  const pick = (f) => { setSelId(f.frame_id); seek(f.video_ts); };
  const act = async (action) => {
    setBusy(true);
    setError("");
    try { await api(`/api/incidents/${id}/review`, { method: "POST", body: { action, reason } }); setReason(""); }
    catch (e) { guard(e); }
    setBusy(false);
  };
  const decision = inc.emergency === true ? "Emergency confirmed" : inc.emergency === false ? "Not an emergency" : "No emergency decision yet";

  return (
    <Shell navigate={navigate} user={user}>
      <section className="panel summary">
        <h2>{inc.id} · {inc.label}</h2>
        <dl className="facts wide">
          <dt>Incident type</dt><dd>{inc.category} · {inc.short}</dd>
          <dt>Camera</dt><dd>{inc.camera_id}</dd>
          <dt>Location</dt><dd>{inc.location}</dd>
          <dt>Detection time</dt><dd>Video {inc.video_ts_text} · detected {new Date(inc.detected_at).toLocaleString()}</dd>
          <dt>Preliminary severity</dt><dd>{inc.severity} <span className="muted">({inc.severity_note})</span></dd>
          <dt>Review status</dt><dd>{REVIEW_LABEL[inc.review_status]} · {decision}</dd>
        </dl>
        <h3>Incident summary</h3>
        <textarea rows={3} value={summary ?? inc.summary} onChange={(e) => setSummary(e.target.value)} />
        {summary !== null && summary !== inc.summary && (
          <button className="btn" onClick={() => api(`/api/incidents/${id}`, { method: "PATCH", body: { summary } }).then(() => setSummary(null)).catch(guard)}>Save summary</button>
        )}
        <p className="muted note">Text source: {inc.description_source}. The summary describes the detector output and saved frames. Edit it if the footage shows something different.</p>
      </section>

      <section className="panel">
        <h2>Evidence timeline</h2>
        {!inc.evidence_complete && <p className="muted note">Frames after the event are still being collected.</p>}
        <ul className="strip">
          {frames.map((f) => (
            <li key={f.frame_id}>
              <button className={`thumb ${sel?.frame_id === f.frame_id ? "thumb-on" : ""} phase-${f.phase}`} onClick={() => pick(f)}>
                <img src={f.url} alt={`${PHASE[f.phase]} frame at ${f.video_ts_text}`} loading="lazy" />
                <span>{f.video_ts_text} · {PHASE[f.phase]}</span>
              </button>
            </li>
          ))}
        </ul>
        {sel && (
          <div className="selected-frame-box">
            <div className="selected-frame-media">
              <button className="enlarge" onClick={() => setZoom(sel)} aria-label="Enlarge frame">
                <img src={sel.url} alt={`Frame ${sel.frame_id}`} />
                <span className="enlarge-hint">🔍 Click to enlarge frame</span>
              </button>
              <div className="frame-meta-bar">
                <span className="frame-id-pill">{sel.frame_id}</span>
                <span className="frame-time-pill">Video: {sel.video_ts_text}</span>
                <span className={`pill-phase phase-${sel.phase}`}>{sel.delta_t_text || PHASE[sel.phase] || sel.phase}</span>
              </div>
            </div>

            <div className="selected-frame-content">
              <div className="frame-header-row">
                <h3 className="frame-title">{sel.title || `${sel.frame_id} · ${PHASE[sel.phase] || sel.phase} Frame`}</h3>
                <span className={`badge-phase phase-${sel.phase}`}>{sel.phase_label || PHASE[sel.phase] || sel.phase}</span>
              </div>

              <div className="agent-analysis-card">
                <div className="agent-card-header">
                  <span className="agent-badge">AI AGENT DETAILED FRAME ANALYSIS</span>
                  <span className="agent-conf">
                    Confidence: {sel.confidence == null ? "Rule-based" : `${Math.round(sel.confidence * 100)}%`}
                  </span>
                </div>
                <p className="frame-narrative">{sel.finding}</p>
              </div>

              <div className="telemetry-grid">
                {sel.scene_context && (
                  <div className="telemetry-cell">
                    <span className="tel-label">Scene Context</span>
                    <span className="tel-val">{sel.scene_context}</span>
                  </div>
                )}
                {sel.tracked_entities && (
                  <div className="telemetry-cell">
                    <span className="tel-label">Tracked Entities</span>
                    <span className="tel-val">{sel.tracked_entities}</span>
                  </div>
                )}
                {sel.dynamics && (
                  <div className="telemetry-cell">
                    <span className="tel-label">Kinematics & Dynamics</span>
                    <span className="tel-val">{sel.dynamics}</span>
                  </div>
                )}
                {sel.operator_note && (
                  <div className="telemetry-cell tel-focus">
                    <span className="tel-label">Reviewer Inspection Focus</span>
                    <span className="tel-val">{sel.operator_note}</span>
                  </div>
                )}
              </div>

              <div className="frame-card-footer">
                <span className="muted">SHA-256: <code>{sel.sha256?.slice(0, 16)}…</code></span>
                <span className="muted">Evidence File: {sel.filename}</span>
              </div>
            </div>
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Original footage</h2>
        <div className={compare ? "compare" : ""}>
          <video ref={video} src={src} controls muted playsInline onLoadedMetadata={() => seek(inc.video_ts)} />
          {compare && sel && <img src={sel.url} alt={`Evidence frame ${sel.video_ts_text}`} />}
        </div>
        <div className="actions">
          <button className="btn" onClick={() => seek(inc.video_ts, true)}>Jump to incident ({inc.video_ts_text})</button>
          <button className="btn" onClick={() => setCompare(!compare)}>{compare ? "Hide frame comparison" : "Compare with evidence frame"}</button>
        </div>
      </section>

      <section className="panel">
        <h2>AI findings</h2>
        {inc.findings.map((f, i) => (
          <dl className="facts wide" key={i}>
            <dt>Detected event</dt><dd>{f.event}</dd>
            <dt>Objects</dt><dd>{f.objects}</dd>
            <dt>Timestamp</dt><dd>{f.timestamp}</dd>
            <dt>Confidence</dt><dd>{Math.round(f.confidence * 100)}% rule score, not a calibrated probability</dd>
            <dt>Evidence</dt><dd>{f.evidence}</dd>
            <dt>Method</dt><dd>{f.method}</dd>
          </dl>
        ))}
        <h3>Uncertainties and limitations</h3>
        <ul className="plain">{inc.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
      </section>

      <section className="panel">
        <h2>Reviewer actions</h2>
        <p className="muted note">Detecting an incident does not send emergency resources. Confirm an emergency only after checking the evidence.</p>
        <label>Reason (recorded with your decision)<textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
        <div className="actions">
          {ACTIONS.map(([key, label, cls]) => <button key={key} className={cls} disabled={busy} onClick={() => act(key)}>{label}</button>)}
        </div>
        {error && <p className="form-error">{error}</p>}
        <h3>Review history</h3>
        {inc.reviews.length === 0 ? <p className="muted">No decisions yet.</p> : (
          <ul className="plain">{inc.reviews.map((r, i) => <li key={i}>{new Date(r.at).toLocaleTimeString()} · {r.user} · {r.action.replace(/_/g, " ")}{r.reason ? ` · ${r.reason}` : ""}</li>)}</ul>
        )}
      </section>

      <section className="panel">
        <h2>Record & Governance</h2>
        <dl className="facts wide">
          <dt>Workbench link</dt>
          <dd>
            <a
              href={`${window.location.origin}/incidents/${inc.id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="sms-hyperlink"
            >
              {`${window.location.origin}/incidents/${inc.id}`}
            </a>
          </dd>
          <dt>Original video</dt><dd>{inc.video_ref?.file} · SHA-256 {inc.video_ref?.sha256?.slice(0, 16)}…</dd>
          <dt>Email Alert Status</dt>
          <dd>
            <div style={{ display: "inline-flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
              <span className={`badge ${inc.email?.status === "sent" ? "sev-low" : inc.email?.status === "failed" ? "sev-critical" : "sev-medium"}`} style={{ fontSize: "12px", padding: "3px 8px" }}>
                {inc.email?.status === "sent" && `✓ Sent to ${inc.email.to}`}
                {inc.email?.status === "failed" && `⚠️ Email Failed (${inc.email.detail || "Connection error"})`}
                {inc.email?.status === "logged" && `📁 Saved to Outbox (${inc.email.to || "offline"})`}
                {inc.email?.status === "skipped" && `Skipped (${inc.email.detail})`}
                {(!inc.email || inc.email?.status === "pending") && `⏳ Pending Dispatch`}
              </span>
              <button
                type="button"
                className="btn btn-sm"
                onClick={handleSendEmail}
                disabled={sendingEmail}
                style={{ fontSize: "12px", padding: "3px 10px" }}
              >
                {sendingEmail ? "Dispatching..." : "✉️ Dispatch Email Alert"}
              </button>
            </div>
            {emailFeedback && (
              <span style={{ display: "block", fontSize: "12px", color: emailFeedback.startsWith("✓") ? "#16a34a" : "#dc2626", marginTop: "4px" }}>
                {emailFeedback}
              </span>
            )}
          </dd>
          <dt>SMS Dispatch Status</dt>
          <dd>
            {inc.sms ? (
              <div style={{ display: "inline-flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                <span className={`badge ${inc.sms.status === "sent" ? "sev-low" : inc.sms.status === "failed" ? "sev-critical" : "sev-medium"}`} style={{ fontSize: "12px", padding: "3px 8px" }}>
                  {inc.sms.status === "sent" && `✓ Sent to ${inc.sms.to}`}
                  {inc.sms.status === "failed" && `⚠️ Fast2SMS Rejected (${inc.sms.detail || "Insufficient wallet balance"})`}
                  {inc.sms.status === "logged" && `📁 Saved to Outbox (${inc.sms.to || "no number"})`}
                  {inc.sms.status === "skipped" && `Skipped (${inc.sms.detail})`}
                </span>
                <button
                  type="button"
                  className="btn-link"
                  onClick={() => navigate(`/settings?tab=fast2sms`)}
                  style={{ fontSize: "12px" }}
                >
                  View Outbox Copy →
                </button>
              </div>
            ) : (
              <span className="muted">No dispatch recorded</span>
            )}
          </dd>
          <dt>System Status</dt>
          <dd>
            <span className="badge-fast2sms" style={{ fontSize: "11px", padding: "2px 8px" }}>Fast2SMS & Audit Managed in Settings</span>
          </dd>
        </dl>
        <div className="actions">
          <button className="btn" onClick={() => api(`/api/incidents/${id}/integrity`).then(setIntegrity).catch(guard)}>Verify evidence integrity</button>
          {integrity && <span>{integrity.video_ok && integrity.frames.every((f) => f.ok) ? "Video and all frames match their recorded hashes." : "A hash does not match. Treat this evidence as altered."}</span>}
        </div>

        <div className="record-settings-redirect" style={{ marginTop: "18px", padding: "14px 16px", background: "var(--surface)", border: "1.5px solid var(--border)", borderRadius: "6px", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px" }}>
          <div>
            <strong style={{ fontSize: "13.5px", color: "var(--text)" }}>🛡️ Fast2SMS Telecom & Audit Logs Moved to Settings</strong>
            <p className="muted" style={{ margin: "4px 0 0", fontSize: "12.5px" }}>
              Incident audit trails, operator access history, and Fast2SMS dispatch controls are managed centrally in System Settings.
            </p>
          </div>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => navigate(`/settings?tab=audit&incident=${inc.id}`)}
            style={{ fontSize: "13px", whiteSpace: "nowrap" }}
          >
            Open Settings Audit Log →
          </button>
        </div>
      </section>

      {zoom && (
        <div className="lightbox" role="dialog" aria-label="Enlarged evidence frame" onClick={() => setZoom(null)}>
          <div className="lightbox-modal" onClick={(e) => e.stopPropagation()}>
            <div className="lightbox-img-wrap">
              <img src={zoom.url} alt={`Frame ${zoom.frame_id}`} />
            </div>
            <div className="lightbox-info-panel">
              <div className="lightbox-header">
                <div>
                  <h3 className="lightbox-title">{zoom.title || zoom.frame_id}</h3>
                  <span className="lightbox-sub">Frame ID: {zoom.frame_id} · Video Timestamp: {zoom.video_ts_text} · Phase: {zoom.phase_label || PHASE[zoom.phase]}</span>
                </div>
                <button className="btn btn-close-modal" onClick={() => setZoom(null)}>✕ Close</button>
              </div>

              <div className="lightbox-narrative-box">
                <div className="agent-badge">AI AGENT DETAILED FRAME ANALYSIS</div>
                <p className="lightbox-narrative-text">{zoom.finding}</p>
              </div>

              {zoom.operator_note && (
                <div className="lightbox-focus-box">
                  <strong>Reviewer Inspection Focus:</strong> {zoom.operator_note}
                </div>
              )}

              <div className="lightbox-footer">
                {zoom.dynamics && <div><strong>Kinematics:</strong> {zoom.dynamics}</div>}
                {zoom.tracked_entities && <div><strong>Entities:</strong> {zoom.tracked_entities}</div>}
                <div className="muted" style={{ marginTop: "4px" }}>SHA-256 Hash: <code>{zoom.sha256}</code></div>
              </div>
            </div>
          </div>
        </div>
      )}
    </Shell>
  );
}

function Shell({ navigate, user, children }) {
  return (
    <div className="desk">
      <header className="bar">
        <div className="brand-group">
          <CommandEmblem size={30} spinning={true} />
          <div className="brand-text">
            <div className="brand-title-row">
              <h1>Incident Workbench</h1>
              <span className="brand-badge">FORENSICS HQ</span>
            </div>
            <span className="brand-sub">FORENSIC EVIDENCE & DECISION CONSOLE</span>
          </div>
        </div>
        <div className="bar-stats">
          <LiveClock />
        </div>
        <div className="bar-actions">
          <button
            type="button"
            className="btn btn-settings-nav"
            onClick={() => navigate("/settings")}
            title="Open System Settings (Fast2SMS Gateway, Audit Trail)"
          >
            ⚙️ Settings
          </button>
          <button className="btn btn-primary" onClick={() => navigate("/")}>
            ← Back to Dashboard
          </button>
        </div>
      </header>
      <main className="bench">{children}</main>
    </div>
  );
}
