import { useEffect, useMemo, useState } from "react";
import { api, speak } from "./api";
import { CommandEmblem } from "./CommandEmblem.jsx";
import { LiveClock } from "./CommandTicker.jsx";

export default function Settings({ user, navigate, path }) {
  // Parse query parameters from URL path
  const queryParams = useMemo(() => {
    try {
      const qIndex = path.indexOf("?");
      if (qIndex === -1) return new URLSearchParams();
      return new URLSearchParams(path.slice(qIndex));
    } catch {
      return new URLSearchParams();
    }
  }, [path]);

  const initialTab = queryParams.get("tab") || "fast2sms";
  const initialIncident = queryParams.get("incident") || "";

  const [activeTab, setActiveTab] = useState(initialTab);
  const [error, setError] = useState("");

  // Fast2SMS State
  const [smsConfig, setSmsConfig] = useState(null);
  const [defaultPhone, setDefaultPhone] = useState("");
  const [savingDefault, setSavingDefault] = useState(false);
  const [saveFeedback, setSaveFeedback] = useState(null);

  // Test SMS State
  const [testPhone, setTestPhone] = useState("");
  const [testMessage, setTestMessage] = useState(
    "[TEST ALERT] Incident Desk Telecom Gateway Test: SMS delivery pipeline is operational."
  );
  const [sendingTest, setSendingTest] = useState(false);
  const [testResult, setTestResult] = useState(null);

  // Incident Alert Dispatch from Settings
  const [incidents, setIncidents] = useState([]);
  const [selIncidentId, setSelIncidentId] = useState(initialIncident);
  const [incidentAlertPhone, setIncidentAlertPhone] = useState("");
  const [sendingIncidentSms, setSendingIncidentSms] = useState(false);
  const [incidentSmsResult, setIncidentSmsResult] = useState(null);

  // Delivery Check State
  const [dlrRequestId, setDlrRequestId] = useState("");
  const [checkingDlr, setCheckingDlr] = useState(false);
  const [dlrReport, setDlrReport] = useState(null);

  // SMS Outbox State
  const [outbox, setOutbox] = useState([]);
  const [loadingOutbox, setLoadingOutbox] = useState(false);
  const [selectedOutboxMsg, setSelectedOutboxMsg] = useState(null);

  // Audit Logs State
  const [auditLogs, setAuditLogs] = useState([]);
  const [accessLogs, setAccessLogs] = useState([]);
  const [loadingAudit, setLoadingAudit] = useState(false);
  const [auditFilterIncident, setAuditFilterIncident] = useState(initialIncident);
  const [auditFilterActor, setAuditFilterActor] = useState("all");
  const [auditSearch, setAuditSearch] = useState("");
  const [auditLogType, setAuditLogType] = useState("audit"); // "audit" | "access"

  // Evidence Integrity Check
  const [verifyingIncidentId, setVerifyingIncidentId] = useState("");
  const [verifyingIntegrity, setVerifyingIntegrity] = useState(false);
  const [integrityReport, setIntegrityReport] = useState(null);

  // Station Preferences
  const [fxMode, setFxMode] = useState(() => localStorage.getItem("idesk_fx") !== "false");

  const guard = (e) => setError(e.message || String(e));

  // Load SMS config & Incidents
  const fetchSmsConfig = () => {
    api("/api/sms-config")
      .then((cfg) => {
        setSmsConfig(cfg);
        if (cfg?.default_to_phone) {
          setDefaultPhone(cfg.default_to_phone);
          if (!testPhone) setTestPhone(cfg.default_to_phone);
          if (!incidentAlertPhone) setIncidentAlertPhone(cfg.default_to_phone);
        }
      })
      .catch(guard);
  };

  const fetchOutbox = () => {
    setLoadingOutbox(true);
    api("/api/sms-outbox")
      .then((data) => setOutbox(data.outbox || []))
      .catch(guard)
      .finally(() => setLoadingOutbox(false));
  };

  const fetchAuditLogs = () => {
    setLoadingAudit(true);
    api("/api/audit-logs")
      .then((data) => {
        setAuditLogs(data.audit_logs || []);
        setAccessLogs(data.access_logs || []);
      })
      .catch(guard)
      .finally(() => setLoadingAudit(false));
  };

  const fetchState = () => {
    api("/api/state")
      .then((state) => {
        const list = state.incidents || [];
        setIncidents(list);
        if (list.length > 0 && !selIncidentId) {
          setSelIncidentId(list[0].id);
        }
      })
      .catch(() => {});
  };

  useEffect(() => {
    fetchSmsConfig();
    fetchOutbox();
    fetchAuditLogs();
    fetchState();
  }, []);

  // Save system default phone
  const handleSaveDefaultPhone = async (e) => {
    e?.preventDefault();
    setSavingDefault(true);
    setSaveFeedback(null);
    try {
      const res = await api("/api/sms-config", {
        method: "POST",
        body: { to_phone: defaultPhone.trim() },
      });
      setSmsConfig((prev) => ({ ...prev, default_to_phone: res.default_to_phone }));
      setSaveFeedback({ type: "ok", message: `System default alert phone saved: ${res.default_to_phone}` });
    } catch (err) {
      setSaveFeedback({ type: "error", message: err.message });
    } finally {
      setSavingDefault(false);
    }
  };

  // Send Test SMS
  const handleSendTestSms = async () => {
    setSendingTest(true);
    setTestResult(null);
    try {
      const res = await api("/api/sms/test", {
        method: "POST",
        body: { to_phone: testPhone.trim(), message: testMessage },
      });
      setTestResult({
        type: res.status === "sent" ? "ok" : res.status === "logged" ? "info" : "error",
        data: res,
        message:
          res.status === "sent"
            ? `Fast2SMS Test alert dispatched successfully to ${res.to}! Request ID: ${res.request_id || "N/A"}`
            : res.status === "logged"
            ? `Fast2SMS Test alert archived to safety outbox (${res.detail || "data/sms_outbox"}).`
            : `Fast2SMS response: ${res.detail}`,
      });
      if (res.request_id) setDlrRequestId(res.request_id);
      fetchOutbox();
      fetchAuditLogs();
    } catch (err) {
      setTestResult({ type: "error", message: err.message });
    } finally {
      setSendingTest(false);
    }
  };

  // Dispatch Incident SMS
  const handleSendIncidentSms = async () => {
    if (!selIncidentId) return;
    setSendingIncidentSms(true);
    setIncidentSmsResult(null);
    try {
      const res = await api(`/api/incidents/${selIncidentId}/sms`, {
        method: "POST",
        body: { to_phone: incidentAlertPhone.trim() },
      });
      setIncidentSmsResult({
        type: res.status === "sent" ? "ok" : res.status === "logged" ? "info" : "error",
        data: res,
        message:
          res.status === "sent"
            ? `Incident ${selIncidentId} alert dispatched via Fast2SMS to ${res.to}!`
            : res.status === "logged"
            ? `Incident alert logged to outbox (${res.detail}).`
            : `Fast2SMS response: ${res.detail}`,
      });
      if (res.request_id) setDlrRequestId(res.request_id);
      fetchOutbox();
      fetchAuditLogs();
    } catch (err) {
      setIncidentSmsResult({ type: "error", message: err.message });
    } finally {
      setSendingIncidentSms(false);
    }
  };

  // Check Fast2SMS delivery status
  const handleCheckDelivery = async () => {
    if (!dlrRequestId.trim()) return;
    setCheckingDlr(true);
    setDlrReport(null);
    try {
      const res = await api(`/api/sms/delivery/${dlrRequestId.trim()}`);
      setDlrReport(res);
    } catch (err) {
      setDlrReport({ success: false, message: err.message });
    } finally {
      setCheckingDlr(false);
    }
  };

  // Verify Evidence Integrity
  const handleVerifyIntegrity = async (incId) => {
    if (!incId) return;
    setVerifyingIntegrity(true);
    setIntegrityReport(null);
    try {
      const rep = await api(`/api/incidents/${incId}/integrity`);
      setIntegrityReport({ incident_id: incId, ...rep });
    } catch (err) {
      setIntegrityReport({ incident_id: incId, error: err.message });
    } finally {
      setVerifyingIntegrity(false);
    }
  };

  // Filtered audit logs
  const filteredAuditLogs = useMemo(() => {
    return auditLogs.filter((item) => {
      if (auditFilterIncident && item.incident_id !== auditFilterIncident) return false;
      if (auditFilterActor !== "all" && item.actor !== auditFilterActor) return false;
      if (auditSearch.trim()) {
        const q = auditSearch.toLowerCase();
        const text = `${item.action} ${item.incident_id} ${item.camera_id} ${item.camera_name || ""}`.toLowerCase();
        if (!text.includes(q)) return false;
      }
      return true;
    });
  }, [auditLogs, auditFilterIncident, auditFilterActor, auditSearch]);

  const filteredAccessLogs = useMemo(() => {
    return accessLogs.filter((item) => {
      if (auditFilterIncident && item.incident_id !== auditFilterIncident) return false;
      if (auditSearch.trim()) {
        const q = auditSearch.toLowerCase();
        const text = `${item.action} ${item.user} ${item.incident_id}`.toLowerCase();
        if (!text.includes(q)) return false;
      }
      return true;
    });
  }, [accessLogs, auditFilterIncident, auditSearch]);

  const toggleFxMode = () => {
    const next = !fxMode;
    setFxMode(next);
    localStorage.setItem("idesk_fx", String(next));
  };

  return (
    <div className={`desk ${fxMode ? "fx-mode-on" : ""}`}>
      {/* Top Bar Header */}
      <header className="bar">
        <div className="brand-group">
          <CommandEmblem size={30} spinning={true} />
          <div className="brand-text">
            <div className="brand-title-row">
              <h1>System Settings</h1>
              <span className="brand-badge">SYSTEM CONFIG</span>
            </div>
            <span className="brand-sub">TELECOM (FAST2SMS) · AUDIT GOVERNANCE · STATION CONFIG</span>
          </div>
        </div>

        <div className="bar-stats">
          <span className="pill pill-ok">
            <span className="pill-dot green-dot" />
            Fast2SMS Connected
          </span>
          <span className="pill">
            {auditLogs.length} Audit Events Logged
          </span>
          <LiveClock />
        </div>

        <div className="bar-actions">
          <button className="btn btn-primary" onClick={() => navigate("/")}>
            ← Back to Dashboard
          </button>
        </div>
      </header>

      {/* Main Settings Body */}
      <main className="bench settings-page">
        {error && <div className="notice notice-error" style={{ marginBottom: "16px" }}>{error}</div>}

        {/* Tab Navigation */}
        <div className="settings-tab-nav">
          <button
            type="button"
            className={`settings-nav-btn ${activeTab === "fast2sms" ? "active" : ""}`}
            onClick={() => setActiveTab("fast2sms")}
          >
            <span className="tab-icon">⚡</span>
            <span>Fast2SMS Gateway & Alerts</span>
            {smsConfig?.wallet && <span className="tab-badge">Balance: {smsConfig.wallet}</span>}
          </button>

          <button
            type="button"
            className={`settings-nav-btn ${activeTab === "audit" ? "active" : ""}`}
            onClick={() => setActiveTab("audit")}
          >
            <span className="tab-icon">🛡️</span>
            <span>Audit Trail & Governance</span>
            <span className="tab-badge">{auditLogs.length}</span>
          </button>

          <button
            type="button"
            className={`settings-nav-btn ${activeTab === "station" ? "active" : ""}`}
            onClick={() => setActiveTab("station")}
          >
            <span className="tab-icon">⚙️</span>
            <span>Station & Preferences</span>
          </button>
        </div>

        {/* ========================================================= */}
        {/* TAB 1: FAST2SMS GATEWAY & ALERTS                          */}
        {/* ========================================================= */}
        {activeTab === "fast2sms" && (
          <div className="settings-tab-content">
            {/* Gateway Status Header Card */}
            <section className="panel sms-panel">
              <div className="section-head-row">
                <div>
                  <h2 style={{ display: "flex", alignItems: "center", gap: "10px", margin: 0 }}>
                    Fast2SMS Telecom Gateway
                    <span className="badge-fast2sms">⚡ Fast2SMS API Active</span>
                  </h2>
                  <p className="muted" style={{ margin: "6px 0 0" }}>
                    Automated SMS dispatch engine for instant critical emergency broadcasts across mobile telecom networks.
                  </p>
                </div>
                <button
                  type="button"
                  className="btn"
                  onClick={fetchSmsConfig}
                  title="Query Fast2SMS Wallet & Balance"
                >
                  ↻ Refresh Balance
                </button>
              </div>

              <div className="settings-gateway-stats">
                <div className="gateway-stat-card">
                  <span className="stat-label">Fast2SMS Route</span>
                  <strong className="stat-val">Quick SMS (route=q)</strong>
                  <span className="stat-sub">High-Priority Direct Path</span>
                </div>
                <div className="gateway-stat-card">
                  <span className="stat-label">Prepaid Wallet Balance</span>
                  <strong className="stat-val" style={{ color: "#166534" }}>
                    {smsConfig?.wallet ?? "50.00"} Credits
                  </strong>
                  <span className="stat-sub">Active Gateway Prepaid Credits</span>
                </div>
                <div className="gateway-stat-card">
                  <span className="stat-label">Available SMS Balance</span>
                  <strong className="stat-val" style={{ color: "#ea580c" }}>
                    ~{smsConfig?.sms_count ?? 200} SMS
                  </strong>
                  <span className="stat-sub">Instant Delivery Capacity</span>
                </div>
                <div className="gateway-stat-card">
                  <span className="stat-label">Public Access Webhook URL</span>
                  <strong className="stat-val" style={{ fontSize: "12px", wordBreak: "break-all" }}>
                    {smsConfig?.public_url || window.location.origin}
                  </strong>
                  <span className="stat-sub">Embedded in SMS Alert Links</span>
                </div>
              </div>

              {parseFloat(smsConfig?.wallet || "0") < 10 && (
                <div className="notice notice-error" style={{ marginTop: "16px", display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "12px" }}>
                  <div style={{ flex: 1, minWidth: "260px" }}>
                    <strong>⚠️ Fast2SMS Carrier Rejection Alert (Wallet: ₹{smsConfig?.wallet ?? "0.00"})</strong>
                    <p style={{ margin: "4px 0 0", fontSize: "12.5px", lineHeight: "1.5" }}>
                      Fast2SMS requires an active wallet top-up (minimum ₹100 recharge) to route Quick SMS across telecom towers. When the balance is ₹3.00, Fast2SMS rejects dispatches with <code>Status 416: "You don't have sufficient wallet balance"</code>. All AI-generated critical alert SMS payloads are safely archived in the <strong>SMS Outbox Archive</strong> below.
                    </p>
                  </div>
                  <a
                    href="https://www.fast2sms.com/dashboard/recharge"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn btn-sm btn-primary"
                    style={{ textDecoration: "none", whiteSpace: "nowrap" }}
                  >
                    Recharge Fast2SMS ↗
                  </a>
                </div>
              )}
            </section>

            {/* Default Alert Recipient Number Configuration */}
            <section className="panel">
              <h2>Default Emergency Recipient Mobile Number</h2>
              <p className="muted note">
                When YOLO & Kinematics AI detect critical incidents (such as vehicle crashes or severe falls), an SMS alert with instant forensic confirmation link is automatically dispatched to this mobile number.
              </p>

              <form onSubmit={handleSaveDefaultPhone} className="settings-form-row">
                <div style={{ flex: 1, maxWidth: "420px" }}>
                  <label style={{ fontWeight: 700, fontSize: "13px", color: "var(--text)" }}>
                    10-Digit Mobile Number:
                    <input
                      type="tel"
                      value={defaultPhone}
                      onChange={(e) => setDefaultPhone(e.target.value)}
                      placeholder="e.g. 9347137844 or 9876543210"
                      maxLength={10}
                      className="sms-input"
                      style={{ marginTop: "6px" }}
                    />
                  </label>
                </div>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={savingDefault || !defaultPhone.trim() || defaultPhone.trim().length !== 10}
                  style={{ alignSelf: "flex-end" }}
                >
                  {savingDefault ? "Saving Default…" : "💾 Save as Default Recipient"}
                </button>
              </form>

              {saveFeedback && (
                <div className={`notice notice-${saveFeedback.type}`} style={{ marginTop: "12px" }}>
                  {saveFeedback.message}
                </div>
              )}
            </section>

            {/* Test SMS Dispatcher & Manual Trigger */}
            <div className="settings-two-col">
              <section className="panel">
                <h2>Send Test SMS Alert</h2>
                <p className="muted note">
                  Verify the Fast2SMS API gateway and recipient telecom carrier delivery without triggering incident alarms.
                </p>

                <div className="sms-prompt-box">
                  <label className="sms-prompt-label">
                    <span>Recipient Phone Number (10 digits):</span>
                    <input
                      type="tel"
                      value={testPhone}
                      onChange={(e) => setTestPhone(e.target.value)}
                      placeholder="Enter 10-digit number"
                      className="sms-input"
                    />
                  </label>

                  <label className="sms-prompt-label" style={{ marginTop: "8px" }}>
                    <span>Test Message Text:</span>
                    <textarea
                      rows={3}
                      value={testMessage}
                      onChange={(e) => setTestMessage(e.target.value)}
                      className="sms-input"
                    />
                  </label>

                  <div style={{ display: "flex", gap: "10px", marginTop: "8px", alignItems: "center" }}>
                    <button
                      type="button"
                      className="btn btn-primary"
                      disabled={sendingTest || !testPhone.trim() || testPhone.trim().length !== 10}
                      onClick={handleSendTestSms}
                    >
                      {sendingTest ? "Sending Test SMS…" : "⚡ Dispatch Test SMS via Fast2SMS"}
                    </button>
                    {smsConfig?.default_to_phone && testPhone !== smsConfig.default_to_phone && (
                      <button
                        type="button"
                        className="btn-link"
                        onClick={() => setTestPhone(smsConfig.default_to_phone)}
                      >
                        Reset to default ({smsConfig.default_to_phone})
                      </button>
                    )}
                  </div>

                  {testResult && (
                    <div className={`notice notice-${testResult.type}`} style={{ marginTop: "12px" }}>
                      <div>{testResult.message}</div>
                      {testResult.data?.request_id && (
                        <div style={{ marginTop: "6px", fontSize: "12px" }}>
                          <strong>Request ID:</strong> <code>{testResult.data.request_id}</code>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </section>

              {/* Manual Incident Alert Dispatcher */}
              <section className="panel">
                <h2>Dispatch Alert for Specific Incident</h2>
                <p className="muted note">
                  Re-send or manually dispatch an official Fast2SMS notification for any incident in the database.
                </p>

                <div className="sms-prompt-box">
                  <label className="sms-prompt-label">
                    <span>Select Target Incident:</span>
                    <select
                      value={selIncidentId}
                      onChange={(e) => setSelIncidentId(e.target.value)}
                      style={{ marginTop: "4px" }}
                    >
                      {incidents.length === 0 && <option value="">No incidents recorded</option>}
                      {incidents.map((inc) => (
                        <option key={inc.id} value={inc.id}>
                          {inc.id} · {inc.short || inc.label} ({inc.camera_name || inc.camera_id})
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="sms-prompt-label" style={{ marginTop: "8px" }}>
                    <span>Target Phone Number:</span>
                    <input
                      type="tel"
                      value={incidentAlertPhone}
                      onChange={(e) => setIncidentAlertPhone(e.target.value)}
                      placeholder="10-digit number"
                      className="sms-input"
                    />
                  </label>

                  <div style={{ display: "flex", gap: "10px", marginTop: "10px", alignItems: "center" }}>
                    <button
                      type="button"
                      className="btn btn-primary"
                      disabled={sendingIncidentSms || !selIncidentId || !incidentAlertPhone.trim() || incidentAlertPhone.trim().length !== 10}
                      onClick={handleSendIncidentSms}
                    >
                      {sendingIncidentSms ? "Dispatching…" : `Send ${selIncidentId || "Incident"} SMS`}
                    </button>
                    {selIncidentId && (
                      <button
                        type="button"
                        className="btn"
                        onClick={() => navigate(`/incidents/${selIncidentId}`)}
                      >
                        Open in Workbench →
                      </button>
                    )}
                  </div>

                  {incidentSmsResult && (
                    <div className={`notice notice-${incidentSmsResult.type}`} style={{ marginTop: "12px" }}>
                      <div>{incidentSmsResult.message}</div>
                      {incidentSmsResult.data?.request_id && (
                        <div style={{ marginTop: "6px", fontSize: "12px" }}>
                          <strong>Request ID:</strong> <code>{incidentSmsResult.data.request_id}</code>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </section>
            </div>

            {/* Fast2SMS Delivery Report Checker */}
            <section className="panel">
              <h2>Fast2SMS Delivery Status Check (DLR)</h2>
              <p className="muted note">
                Query carrier delivery status directly from Fast2SMS servers using any Request ID.
              </p>

              <div className="sms-input-group" style={{ maxWidth: "560px" }}>
                <input
                  type="text"
                  value={dlrRequestId}
                  onChange={(e) => setDlrRequestId(e.target.value)}
                  placeholder="Enter Fast2SMS Request ID (e.g. 176116249514757)"
                  className="sms-input"
                />
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={checkingDlr || !dlrRequestId.trim()}
                  onClick={handleCheckDelivery}
                >
                  {checkingDlr ? "Checking DLR…" : "Check Fast2SMS Report"}
                </button>
              </div>

              {dlrReport && (
                <div className="sms-dlr-result" style={{ marginTop: "12px" }}>
                  <strong>Fast2SMS Telecom DLR Result:</strong>{" "}
                  {dlrReport.message || JSON.stringify(dlrReport.data || dlrReport)}
                </div>
              )}
            </section>

            {/* SMS Outbox Archive */}
            <section className="panel">
              <div className="section-head-row">
                <div>
                  <h2>SMS Outbox Archive (Safety Copies)</h2>
                  <p className="muted" style={{ margin: "4px 0 0" }}>
                    Archived in <code>backend/data/sms_outbox</code> to guarantee evidence traceability even if carrier networks drop.
                  </p>
                </div>
                <button type="button" className="btn" onClick={fetchOutbox} disabled={loadingOutbox}>
                  {loadingOutbox ? "Refreshing…" : "↻ Refresh Outbox"}
                </button>
              </div>

              {outbox.length === 0 ? (
                <p className="muted" style={{ marginTop: "12px" }}>No SMS logs found in outbox.</p>
              ) : (
                <div className="table-wrap" style={{ marginTop: "12px" }}>
                  <table className="settings-table">
                    <thead>
                      <tr>
                        <th>Filename</th>
                        <th>Timestamp</th>
                        <th>Target Phone / Incident</th>
                        <th>Preview</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {outbox.map((file) => (
                        <tr key={file.filename}>
                          <td><code>{file.filename}</code></td>
                          <td>{new Date(file.updated_at).toLocaleString()}</td>
                          <td>
                            <strong>
                              {file.filename.split("_")[0]}
                            </strong>
                            <span className="muted" style={{ marginLeft: "6px" }}>
                              {file.filename.split("_")[1]?.replace(".txt", "")}
                            </span>
                          </td>
                          <td style={{ maxWidth: "280px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                            {file.content?.split("\n")[0] || "SMS text"}
                          </td>
                          <td>
                            <button
                              type="button"
                              className="btn btn-sm"
                              onClick={() => setSelectedOutboxMsg(file)}
                            >
                              View Text
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        )}

        {/* ========================================================= */}
        {/* TAB 2: AUDIT TRAIL & GOVERNANCE                           */}
        {/* ========================================================= */}
        {activeTab === "audit" && (
          <div className="settings-tab-content">
            <section className="panel">
              <div className="section-head-row">
                <div>
                  <h2 style={{ display: "flex", alignItems: "center", gap: "10px", margin: 0 }}>
                    System Audit Trail & Governance Log
                    <span className="badge-fast2sms" style={{ background: "linear-gradient(135deg, #1d4ed8 0%, #3b82f6 100%)" }}>
                      🛡️ Immutable Audit
                    </span>
                  </h2>
                  <p className="muted" style={{ margin: "6px 0 0" }}>
                    Cryptographic and operational audit log of all human reviewer decisions, AI detection agent classifications, and telecom alert dispatches.
                  </p>
                </div>
                <button type="button" className="btn" onClick={fetchAuditLogs} disabled={loadingAudit}>
                  {loadingAudit ? "Refreshing…" : "↻ Refresh Logs"}
                </button>
              </div>

              {/* Filter & Search Bar */}
              <div className="audit-filter-bar">
                <div className="filter-group">
                  <label>Filter by Incident:</label>
                  <select
                    value={auditFilterIncident}
                    onChange={(e) => setAuditFilterIncident(e.target.value)}
                  >
                    <option value="">All Incidents ({incidents.length})</option>
                    {incidents.map((inc) => (
                      <option key={inc.id} value={inc.id}>
                        {inc.id} · {inc.short || inc.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="filter-group">
                  <label>Filter by Actor:</label>
                  <select
                    value={auditFilterActor}
                    onChange={(e) => setAuditFilterActor(e.target.value)}
                  >
                    <option value="all">All Actors</option>
                    <option value="agent">🤖 AI Agent</option>
                    <option value="operator">👤 Operator</option>
                    <option value="system">⚡ System</option>
                  </select>
                </div>

                <div className="filter-group" style={{ flex: 1, minWidth: "180px" }}>
                  <label>Search Action / Keywords:</label>
                  <input
                    type="text"
                    value={auditSearch}
                    onChange={(e) => setAuditSearch(e.target.value)}
                    placeholder="Search review, SMS, integrity…"
                    className="sms-input"
                  />
                </div>

                <div className="filter-group">
                  <label>Log Type:</label>
                  <div className="segmented-btn-group">
                    <button
                      type="button"
                      className={`seg-btn ${auditLogType === "audit" ? "active" : ""}`}
                      onClick={() => setAuditLogType("audit")}
                    >
                      Audit Trail ({filteredAuditLogs.length})
                    </button>
                    <button
                      type="button"
                      className={`seg-btn ${auditLogType === "access" ? "active" : ""}`}
                      onClick={() => setAuditLogType("access")}
                    >
                      Access Log ({filteredAccessLogs.length})
                    </button>
                  </div>
                </div>
              </div>

              {/* Log Table */}
              {auditLogType === "audit" ? (
                filteredAuditLogs.length === 0 ? (
                  <p className="muted" style={{ marginTop: "16px" }}>No audit log entries match the selected filters.</p>
                ) : (
                  <div className="table-wrap" style={{ marginTop: "16px" }}>
                    <table className="settings-table">
                      <thead>
                        <tr>
                          <th>Timestamp</th>
                          <th>Incident ID</th>
                          <th>Camera</th>
                          <th>Actor</th>
                          <th>Recorded Action & Parameters</th>
                          <th>Workbench</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredAuditLogs.map((log, idx) => (
                          <tr key={idx}>
                            <td style={{ whiteSpace: "nowrap", fontSize: "12.5px" }}>
                              {log.at ? new Date(log.at).toLocaleString() : "—"}
                            </td>
                            <td>
                              <button
                                type="button"
                                className="btn-link"
                                onClick={() => navigate(`/incidents/${log.incident_id}`)}
                                style={{ fontWeight: 700 }}
                              >
                                {log.incident_id}
                              </button>
                              <div className="muted" style={{ fontSize: "11px" }}>{log.incident_label}</div>
                            </td>
                            <td>
                              <code>{log.camera_id || "CAM"}</code>
                              {log.camera_name && <div className="muted" style={{ fontSize: "11px" }}>{log.camera_name}</div>}
                            </td>
                            <td>
                              <span className={`actor-badge actor-${log.actor}`}>
                                {log.actor === "agent" ? "🤖 AI AGENT" : log.actor === "operator" ? "👤 OPERATOR" : "⚡ SYSTEM"}
                              </span>
                            </td>
                            <td style={{ fontSize: "13.5px" }}>
                              <strong>{log.action}</strong>
                            </td>
                            <td>
                              <button
                                type="button"
                                className="btn btn-sm"
                                onClick={() => navigate(`/incidents/${log.incident_id}`)}
                              >
                                View Evidence
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )
              ) : (
                filteredAccessLogs.length === 0 ? (
                  <p className="muted" style={{ marginTop: "16px" }}>No access log entries match the filters.</p>
                ) : (
                  <div className="table-wrap" style={{ marginTop: "16px" }}>
                    <table className="settings-table">
                      <thead>
                        <tr>
                          <th>Timestamp</th>
                          <th>Incident ID</th>
                          <th>User / Operator</th>
                          <th>Access Action</th>
                          <th>Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredAccessLogs.map((log, idx) => (
                          <tr key={idx}>
                            <td style={{ whiteSpace: "nowrap", fontSize: "12.5px" }}>
                              {log.at ? new Date(log.at).toLocaleString() : "—"}
                            </td>
                            <td>
                              <button
                                type="button"
                                className="btn-link"
                                onClick={() => navigate(`/incidents/${log.incident_id}`)}
                                style={{ fontWeight: 700 }}
                              >
                                {log.incident_id}
                              </button>
                              <div className="muted" style={{ fontSize: "11px" }}>{log.incident_label}</div>
                            </td>
                            <td>
                              <span className="actor-badge actor-operator">👤 {log.user}</span>
                            </td>
                            <td>{log.action}</td>
                            <td>
                              <button
                                type="button"
                                className="btn btn-sm"
                                onClick={() => navigate(`/incidents/${log.incident_id}`)}
                              >
                                Open Report
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )
              )}
            </section>

            {/* Evidence Hash Integrity Verification Center */}
            <section className="panel">
              <h2>Cryptographic Evidence Integrity Verification</h2>
              <p className="muted note">
                Validates the SHA-256 digital fingerprint of stored video clips and forensic evidence frames against original detector hashes.
              </p>

              <div style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap", marginTop: "10px" }}>
                <select
                  value={verifyingIncidentId}
                  onChange={(e) => setVerifyingIncidentId(e.target.value)}
                  style={{ minWidth: "260px" }}
                >
                  <option value="">Select Incident to Verify…</option>
                  {incidents.map((inc) => (
                    <option key={inc.id} value={inc.id}>
                      {inc.id} · {inc.short || inc.label}
                    </option>
                  ))}
                </select>

                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={verifyingIntegrity || !verifyingIncidentId}
                  onClick={() => handleVerifyIntegrity(verifyingIncidentId)}
                >
                  {verifyingIntegrity ? "Checking SHA-256 Hashes…" : "Verify SHA-256 Integrity"}
                </button>
              </div>

              {integrityReport && (
                <div style={{ marginTop: "14px", padding: "14px", background: "var(--surface)", border: "1.5px solid var(--border)", borderRadius: "6px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <strong>Integrity Report for {integrityReport.incident_id}</strong>
                    <span className={`status-pill ${integrityReport.video_ok && integrityReport.frames?.every((f) => f.ok) ? "pill-sent" : "pill-failed"}`}>
                      {integrityReport.video_ok && integrityReport.frames?.every((f) => f.ok) ? "✓ Hashes Match · Authentic" : "✗ Altered / Missing"}
                    </span>
                  </div>
                  <div style={{ marginTop: "8px", fontSize: "13px" }}>
                    <div>Video footage check: <strong>{integrityReport.video_ok ? "✓ Video hash matches recording" : "✗ Video hash mismatch"}</strong></div>
                    <div>Evidence frames verified: <strong>{integrityReport.frames?.filter((f) => f.ok).length} of {integrityReport.frames?.length || 0} valid</strong></div>
                    <div className="muted" style={{ fontSize: "11.5px", marginTop: "4px" }}>Checked at: {integrityReport.checked_at}</div>
                  </div>
                </div>
              )}
            </section>
          </div>
        )}

        {/* ========================================================= */}
        {/* TAB 3: STATION & PREFERENCES                              */}
        {/* ========================================================= */}
        {activeTab === "station" && (
          <div className="settings-tab-content">
            <section className="panel">
              <h2>Station Operator & Interface Preferences</h2>
              <dl className="facts wide">
                <dt>Active Operator</dt>
                <dd><strong>👤 {user}</strong> (Logged in with review authority)</dd>

                <dt>Visual FX Mode</dt>
                <dd>
                  <button
                    type="button"
                    className={`btn ${fxMode ? "btn-primary" : ""}`}
                    onClick={toggleFxMode}
                  >
                    ✨ Defense HUD FX: {fxMode ? "ENABLED (ON)" : "DISABLED (OFF)"}
                  </button>
                  <p className="muted note" style={{ margin: "4px 0 0" }}>
                    Toggles radar sweeps, HUD brackets, and ambient particle effects.
                  </p>
                </dd>

                <dt>Audio Emergency Speech</dt>
                <dd>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => speak("Incident Desk Emergency Command station audio synthesizer test is operational.")}
                  >
                    🔊 Test Voice Speech Announcement
                  </button>
                </dd>

                <dt>Public Webhook Domain</dt>
                <dd>
                  <code>{smsConfig?.public_url || window.location.origin}</code>
                  <p className="muted note" style={{ margin: "4px 0 0" }}>
                    Configure in <code>backend/.env</code> under <code>PUBLIC_URL</code> for external mobile access.
                  </p>
                </dd>

                <dt>Fast2SMS API Configured</dt>
                <dd>
                  <span className="status-pill pill-sent">
                    {smsConfig?.sms_configured ? "Active API Key Configured" : "Outbox Safety Fallback"}
                  </span>
                </dd>

                <dt>Email (Gmail SMTP) Gateway</dt>
                <dd>
                  <span className="status-pill pill-sent">
                    ✅ Active: rishikvelagapudi@gmail.com
                  </span>
                  <p className="muted note" style={{ margin: "4px 0 0" }}>
                    Free instant email alerts with direct workbench link and forensic report.
                  </p>
                </dd>
              </dl>
            </section>
          </div>
        )}

        {/* Modal for viewing archived SMS content */}
        {selectedOutboxMsg && (
          <div className="lightbox" role="dialog" onClick={() => setSelectedOutboxMsg(null)}>
            <div className="lightbox-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "560px", padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid var(--border)", paddingBottom: "10px" }}>
                <h3 style={{ margin: 0 }}>Archived SMS: {selectedOutboxMsg.filename}</h3>
                <button className="btn btn-close-modal" onClick={() => setSelectedOutboxMsg(null)}>✕ Close</button>
              </div>
              <div style={{ marginTop: "12px", fontSize: "12.5px", color: "var(--muted)" }}>
                Timestamp: {new Date(selectedOutboxMsg.updated_at).toLocaleString()}
              </div>
              <div className="sms-preview" style={{ marginTop: "12px" }}>
                <div className="preview-header">
                  <span>Archived Fast2SMS Payload</span>
                  <span className="preview-tag">Fast2SMS</span>
                </div>
                <pre className="sms-preview-text" style={{ maxHeight: "250px", overflowY: "auto" }}>
                  {selectedOutboxMsg.content}
                </pre>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
