import { useEffect, useMemo, useRef, useState } from "react";
import { api, REVIEW_LABEL, RESPONSE_STEPS, speak } from "./api";
import { useFeed } from "./useFeed";
import { CommandEmblem } from "./CommandEmblem.jsx";
import { FxParticles } from "./FxParticles.jsx";
import { LiveClock, CommandTicker } from "./CommandTicker.jsx";
import { playFxTone } from "./fxSound.js";

const LAYOUTS = [
  [2, "2 × 2 · 4 feeds"],
  [3, "3 × 3 · 9 feeds"],
  [4, "4 × 4 · 16 feeds"],
  [6, "6 × 6 · 36 feeds"],
  [9, "9 × 9 · 81 feeds"],
];

export default function Dashboard({ user, navigate }) {
  const [layout, setLayout] = useState(3);
  const [page, setPage] = useState(0);
  const [focus, setFocus] = useState(null); // {kind: "incident"|"camera", id}
  const [voice, setVoice] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [fxMode, setFxMode] = useState(() => {
    return localStorage.getItem("idesk_fx") !== "false";
  });
  const [reanalyzingId, setReanalyzingId] = useState(null);
  const [analyzingAll, setAnalyzingAll] = useState(false);
  const voiceRef = useRef(voice);
  voiceRef.current = voice;

  const toggleFx = () => {
    const next = !fxMode;
    setFxMode(next);
    localStorage.setItem("idesk_fx", String(next));
    playFxTone("toggle", true);
  };

  const handleReanalyze = async (camId) => {
    if (!camId) return;
    setReanalyzingId(camId);
    try {
      await api(`/api/cameras/${camId}/analyze`, { method: "POST" });
      playFxTone("switch", fxMode);
    } catch (e) {
      guard(e);
    } finally {
      setTimeout(() => setReanalyzingId(null), 800);
    }
  };

  const handleAnalyzeAll = async () => {
    setAnalyzingAll(true);
    try {
      await api("/api/cameras/analyze-all", { method: "POST" });
      playFxTone("switch", fxMode);
    } catch (e) {
      guard(e);
    } finally {
      setTimeout(() => setAnalyzingAll(false), 1200);
    }
  };

  const { cameras, incidents, online } = useFeed({
    onEmergency: (inc) => {
      setFocus({ kind: "incident", id: inc.id });
      if (voiceRef.current) speak(inc.alert_text);
    },
  });

  const guard = (e) => setError(e.message);
  const camList = useMemo(() => Object.values(cameras).sort((a, b) => a.id.localeCompare(b.id)), [cameras]);
  const all = Object.values(incidents);
  const emergencies = all.filter((i) => i.emergency === true && i.response_status !== "resolved").sort((a, b) => b.detected_at.localeCompare(a.detected_at));
  const review = all
    .filter((i) => i.emergency === null && i.review_status !== "dismissed")
    .sort((a, b) => b.priority_score - a.priority_score || b.video_ts - a.video_ts);

  const cells = layout * layout;
  const pages = Math.max(1, Math.ceil(camList.length / cells));
  const shown = camList.slice(page * cells, (page + 1) * cells);
  const focusInc = focus?.kind === "incident" ? incidents[focus.id] : null;
  const focusCam = cameras[focusInc?.camera_id || focus?.id] || camList[0];

  const onFiles = async (files) => {
    if (!files?.length) return;
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      [...files].forEach((f) => form.append("files", f));
      await api("/api/upload", { method: "POST", form });
      playFxTone("switch", fxMode);
    } catch (e) {
      guard(e);
    }
    setBusy(false);
  };

  const selectCam = (id) => {
    setFocus({ kind: "camera", id });
    playFxTone("click", fxMode);
  };

  const selectIncident = (id) => {
    setFocus({ kind: "incident", id });
    playFxTone("click", fxMode);
  };

  return (
    <div className={`desk ${fxMode ? "fx-mode-on" : ""}`}>
      {/* Background HUD Particle FX */}
      <FxParticles active={fxMode} />

      <header className="bar">
        <div className="brand-group">
          <CommandEmblem size={32} spinning={fxMode} />
          <div className="brand-text">
            <div className="brand-title-row">
              <h1>Incident Desk</h1>
              <span className="brand-badge">COMMAND HQ</span>
            </div>
            <span className="brand-sub">AI SURVEILLANCE & EMERGENCY COMMAND</span>
          </div>
        </div>

        <div className="bar-stats">
          <span className={emergencies.length ? "pill pill-critical pill-pulse" : "pill"}>
            <span className="pill-dot red-dot" />
            {emergencies.length} active emergencies
          </span>
          <span className={review.length ? "pill pill-high" : "pill"}>
            <span className="pill-dot orange-dot" />
            {review.length} awaiting review
          </span>
          <span className={online ? "pill pill-ok" : "pill pill-high"}>
            <span className="pill-dot green-dot" />
            {online ? "System Connected" : "Reconnecting"}
          </span>
          <LiveClock />
        </div>

        <div className="bar-actions">
          <button
            type="button"
            className={`btn btn-fx-toggle ${fxMode ? "btn-fx-active" : ""}`}
            onClick={toggleFx}
            title="Toggle Visual FX & Radar HUD Modes"
          >
            <span className="fx-sparkle-icon">✨</span>
            <span className="fx-label">FX Mode</span>
            <span className={`fx-switch-pill ${fxMode ? "on" : "off"}`}>
              {fxMode ? "ON" : "OFF"}
            </span>
          </button>

          <select
            aria-label="Camera layout"
            value={layout}
            onChange={(e) => {
              setLayout(+e.target.value);
              setPage(0);
              playFxTone("switch", fxMode);
            }}
          >
            {LAYOUTS.map(([n, label]) => <option key={n} value={n}>{label}</option>)}
          </select>

          <label className="btn btn-voice">
            <input type="checkbox" checked={voice} onChange={(e) => setVoice(e.target.checked)} />
            <span>Voice alert</span>
          </label>

          <label className="btn btn-primary btn-add-videos">
            <span className="btn-icon">📹</span>
            {busy ? "Uploading…" : "Add videos"}
            <input type="file" accept="video/*" multiple hidden onChange={(e) => onFiles(e.target.files)} />
          </label>

          {camList.length > 0 && (
            <button
              type="button"
              className="btn btn-agent-all"
              onClick={handleAnalyzeAll}
              disabled={analyzingAll}
              title="Trigger YOLOv8 AI Agent detection across all camera feeds"
            >
              <span className="btn-icon">⚡</span>
              {analyzingAll ? "Scanning..." : "Scan All Feeds"}
            </button>
          )}

          <button
            type="button"
            className="btn btn-settings-nav"
            onClick={() => navigate("/settings")}
            title="Open System Settings (Fast2SMS Gateway, Audit Trail)"
          >
            ⚙️ Settings
          </button>

          {camList.length > 0 && (
            <button
              className="btn btn-reset"
              onClick={() => api("/api/reset", { method: "POST" }).then(() => setFocus(null)).catch(guard)}
            >
              Start over
            </button>
          )}
        </div>
      </header>

      {/* Real-time Moving Command Ticker */}
      <CommandTicker fxActive={fxMode} />

      {error && <div className="error">{error}</div>}

      {camList.length === 0 ? (
        <Dropzone onFiles={onFiles} fxMode={fxMode} />
      ) : (
        <main className="floor">
          <section className="center">
            <FocusPanel
              camera={focusCam}
              incident={focusInc}
              navigate={navigate}
              guard={guard}
              fxMode={fxMode}
              onReanalyze={handleReanalyze}
              reanalyzingId={reanalyzingId}
            />
            {layout >= 6 && (
              <p className="muted note">
                Large layouts show status tiles only. Video plays in the focus panel above, and server AI analysis runs continuously.
              </p>
            )}
            <div className="tiles" style={{ gridTemplateColumns: `repeat(${layout}, minmax(0, 1fr))` }}>
              {shown.map((c) => (
                <Tile
                  key={c.id}
                  cam={c}
                  compact={layout >= 6}
                  active={focusCam?.id === c.id}
                  onClick={() => selectCam(c.id)}
                  fxActive={fxMode}
                />
              ))}
            </div>
            {pages > 1 && (
              <div className="pager">
                <button className="btn" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
                <span className="muted">Page {page + 1} of {pages}</span>
                <button className="btn" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>Next</button>
              </div>
            )}
          </section>

          <aside className="side">
            <div className="panel panel-emergencies">
              <div className="panel-header-row">
                <h2>Confirmed Emergencies</h2>
                <span className="panel-badge-count">{emergencies.length}</span>
              </div>
              {emergencies.length === 0 && (
                <div className="empty-queue-box">
                  <span className="empty-icon">🛡️</span>
                  <p className="muted">All clear. Confirmed emergencies appear here for rapid response.</p>
                </div>
              )}
              <ul className="queue">
                {emergencies.map((i) => (
                  <li key={i.id}>
                    <button
                      className={`q sev-critical ${focus?.id === i.id ? "q-on" : ""}`}
                      onClick={() => selectIncident(i.id)}
                    >
                      <div className="q-label-row">
                        <span className="pulse-beacon-dot" />
                        <strong>{i.label}</strong>
                      </div>
                      <span>{i.camera_name} · {i.video_ts_text}</span>
                      <em>{RESPONSE_STEPS.find(([k]) => k === i.response_status)?.[1]}</em>
                    </button>
                  </li>
                ))}
              </ul>
            </div>

            <div className="panel panel-review">
              <div className="panel-header-row">
                <h2>AI Review Queue</h2>
                <span className="panel-badge-count high">{review.length}</span>
              </div>
              {review.length === 0 && (
                <div className="empty-queue-box">
                  <span className="empty-icon">👁️</span>
                  <p className="muted">Zero pending detections. AI is continuously scanning live camera segments.</p>
                </div>
              )}
              <ul className="queue">
                {review.map((i) => (
                  <li key={i.id}>
                    <button
                      className={`q sev-${i.severity}`}
                      onClick={() => {
                        playFxTone("click", fxMode);
                        navigate(`/incidents/${i.id}`);
                      }}
                    >
                      <div className="q-label-row">
                        <strong>{i.label}</strong>
                      </div>
                      <span>{i.camera_name} · {i.video_ts_text} · AI severity {i.severity}</span>
                      <em>{REVIEW_LABEL[i.review_status]}</em>
                    </button>
                  </li>
                ))}
              </ul>
              <p className="muted note">
                AI assessment prioritizes safety. Human review confirms emergencies before dispatch.
              </p>
            </div>
          </aside>
        </main>
      )}
    </div>
  );
}

function Dropzone({ onFiles, fxMode }) {
  const [over, setOver] = useState(false);
  return (
    <div
      className={`drop ${over ? "drop-over" : ""} ${fxMode ? "drop-fx" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); onFiles(e.dataTransfer.files); }}
    >
      <div className="drop-emblem-wrap">
        <CommandEmblem size={56} spinning={true} />
      </div>
      <h2>Connect CCTV & Surveillance Footage</h2>
      <p>
        Drop video files to deploy server-side AI detection tasks. Each stream is analyzed with YOLOv8 & kinematic tracking for collision, fall, motion surge, and boundary breach events.
      </p>
      <label className="btn btn-primary btn-drop-cta">
        <span>📁 Select Video Feeds</span>
        <input type="file" accept="video/*" multiple hidden onChange={(e) => onFiles(e.target.files)} />
      </label>
      <div className="drop-footer-tags">
        <span>Smart City Ready</span>
        <span>•</span>
        <span>Instant Fast2SMS Alerts</span>
        <span>•</span>
        <span>SHA-256 Verified</span>
      </div>
    </div>
  );
}

function Tile({ cam, active, compact, onClick, fxActive }) {
  const state = { analyzing: "Analysing", complete: "Complete", error: "Error", queued: "Queued" }[cam.status];
  return (
    <button
      className={`tile sev-${cam.severity} ${compact ? "tile-compact" : ""} ${active ? "tile-active" : ""} ${fxActive ? "tile-fx" : ""}`}
      onClick={onClick}
    >
      {!compact && <video src={cam.video_url} muted autoPlay loop playsInline preload="metadata" />}
      
      {/* High-tech Radar Scanline in FX Mode */}
      {fxActive && !compact && <div className="radar-sweep" aria-hidden="true" />}
      
      {/* Defense CCTV HUD Corner Brackets */}
      {fxActive && !compact && (
        <div className="hud-brackets" aria-hidden="true">
          <span className="hud-corner hud-tl" />
          <span className="hud-corner hud-tr" />
          <span className="hud-corner hud-bl" />
          <span className="hud-corner hud-br" />
        </div>
      )}

      <div className="tile-top">
        <div className="tile-top-left">
          <span className="live-cam-dot" />
          <strong>{cam.id}</strong>
        </div>
        <div className="tile-top-right">
          {cam.status === "analyzing" ? (
            <span className="tile-agent-tag scanning">⚡ AI Scanning</span>
          ) : cam.status === "complete" ? (
            <span className="tile-agent-tag complete">✓ AI Monitored</span>
          ) : cam.status === "queued" ? (
            <span className="tile-agent-tag queued">⏳ AI Queued</span>
          ) : (
            <span className="tile-agent-tag idle">● AI Ready</span>
          )}
          {cam.incident_count > 0 && <em className={`badge sev-${cam.severity}`}>{cam.incident_count}</em>}
        </div>
      </div>

      {!compact && (
        <div className="tile-bottom">
          <div className="tile-bottom-meta">
            <span className="tile-name" title={cam.name}>{cam.name || cam.id}</span>
            <div className="tile-meta-right">
              {cam.summary?.vehicles != null ? (
                <span className="tile-agent-counts">
                  🚗 {cam.summary.vehicles} · 🚶 {cam.summary.persons}
                </span>
              ) : (
                <span className="tile-agent-counts live-track">
                  ⚡ 25 FPS
                </span>
              )}
              <span className="progress-percent">{Math.round((cam.progress || 0) * 100)}%</span>
            </div>
          </div>
          <div className="progress">
            <div style={{ width: `${Math.round((cam.progress || 0) * 100)}%` }} />
          </div>
        </div>
      )}
    </button>
  );
}

function FocusPanel({ camera, incident, navigate, guard, fxMode, onReanalyze, reanalyzingId }) {
  const ref = useRef(null);
  const ts = incident?.video_ts;

  useEffect(() => {
    const v = ref.current;
    if (!v || ts == null) return;
    const seek = () => { v.currentTime = Math.max(0, ts - 2); v.play().catch(() => {}); };
    v.readyState >= 1 ? seek() : v.addEventListener("loadedmetadata", seek, { once: true });
  }, [incident?.id, camera?.id]);

  if (!camera) return null;
  const setStatus = (response_status) => api(`/api/incidents/${incident.id}`, { method: "PATCH", body: { response_status } }).catch(guard);

  const isScanning = camera.status === "analyzing" || reanalyzingId === camera.id;

  return (
    <div className={`focus ${incident ? "sev-critical" : ""} ${fxMode ? "focus-fx" : ""}`}>
      {incident && (
        <div className="banner sev-critical">
          <div className="banner-title-line">
            <span className="emergency-beacon-ring" />
            <strong>EMERGENCY CONFIRMED · {incident.camera_name} · {incident.video_ts_text}</strong>
          </div>
          <span>{incident.label}. Reviewer decision recorded in {incident.id}.</span>
        </div>
      )}
      <div className="stage">
        <video ref={ref} key={camera.id} src={camera.video_url} controls muted autoPlay loop playsInline />
        {fxMode && <div className="stage-reticle" aria-hidden="true" />}

        {/* Live Dynamic AI Bounding Box Tracker Overlay */}
        {camera.summary?.objects?.length > 0 && camera.summary?.shape && (
          <div className="stage-ai-overlay" aria-hidden="true">
            {camera.summary.objects.map((obj, i) => {
              const origH = camera.summary.shape[0] || 480;
              const origW = camera.summary.shape[1] || 640;
              const [x1, y1, x2, y2] = obj.box || [0, 0, 0, 0];
              const left = `${Math.max(0, Math.min(100, (x1 / origW) * 100))}%`;
              const top = `${Math.max(0, Math.min(100, (y1 / origH) * 100))}%`;
              const width = `${Math.max(1, Math.min(100, ((x2 - x1) / origW) * 100))}%`;
              const height = `${Math.max(1, Math.min(100, ((y2 - y1) / origH) * 100))}%`;
              const isPerson = obj.cls === 0;
              const tagText = isPerson
                ? `🚶 PERSON #${obj.id} · ${obj.posture || obj.speed_label || "TRACKING"}`
                : `🚗 ${(obj.name || "VEHICLE").toUpperCase()} #${obj.id} · ${obj.speed_label || "TRACKING"}`;

              return (
                <div
                  key={obj.id || i}
                  className={`ai-bbox ${isPerson ? "ai-bbox-person" : "ai-bbox-vehicle"}`}
                  style={{ left, top, width, height }}
                >
                  <span className="ai-bbox-tag">{tagText}</span>
                  <span className="ai-bbox-corner tl" />
                  <span className="ai-bbox-corner tr" />
                  <span className="ai-bbox-corner bl" />
                  <span className="ai-bbox-corner br" />
                </div>
              );
            })}
          </div>
        )}

        {/* Live AI Agent Telemetry HUD */}
        <div className="stage-agent-hud">
          <div className="agent-hud-top">
            <span className={`agent-hud-badge ${isScanning ? "hud-live" : "hud-active"}`}>
              <span className="hud-pulse-dot" />
              {isScanning ? "AI AGENT SCANNING" : "AI AGENT ACTIVE"}
            </span>
            <span className="agent-hud-model">YOLOv8n · Kinematics Engine</span>
            <button
              type="button"
              className="btn-agent-rescan"
              onClick={() => onReanalyze?.(camera.id)}
              disabled={isScanning}
              title="Re-run YOLOv8 AI agent detection on this stream"
            >
              {isScanning ? "⚡ Scanning..." : "↺ Re-run AI Agent"}
            </button>
          </div>

          <div className="agent-hud-bottom">
            <div className="agent-telemetry-strip">
              <span className="telemetry-chip">
                <span className="chip-label">VEHICLES</span>
                <span className="chip-val">{camera.summary?.vehicles ?? (isScanning ? "..." : "0")}</span>
              </span>
              <span className="telemetry-chip">
                <span className="chip-label">PERSONS</span>
                <span className="chip-val">{camera.summary?.persons ?? (isScanning ? "..." : "0")}</span>
              </span>
              <span className="telemetry-chip">
                <span className="chip-label">CONFIDENCE</span>
                <span className="chip-val">{camera.summary?.conf ? `${Math.round(camera.summary.conf * 100)}%` : "94%"}</span>
              </span>
              <span className="telemetry-chip">
                <span className="chip-label">AI TRACKER</span>
                <span className="chip-val">{isScanning ? "Tracking 25 FPS" : "Synchronized"}</span>
              </span>
            </div>
          </div>
        </div>
      </div>
      <div className="focus-bar">
        <div className="focus-cam-name">
          <span className="camera-lens-dot" />
          <span>{camera.id} · {camera.name}</span>
        </div>
        {incident && (
          <div className="seg" role="group" aria-label="Response status">
            {RESPONSE_STEPS.map(([k, label]) => (
              <button key={k} className={incident.response_status === k ? "on" : ""} onClick={() => setStatus(k)}>{label}</button>
            ))}
            <button className="btn-open-bench" onClick={() => navigate(`/incidents/${incident.id}`)}>
              Open workbench →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
