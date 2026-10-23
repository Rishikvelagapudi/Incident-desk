import { useEffect, useState } from "react";

export function LiveClock() {
  const [timeStr, setTimeStr] = useState("");

  useEffect(() => {
    const update = () => {
      const now = new Date();
      const options = {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      };
      try {
        const t = new Intl.DateTimeFormat(undefined, options).format(now);
        setTimeStr(t);
      } catch {
        setTimeStr(now.toLocaleTimeString());
      }
    };
    update();
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <span className="live-clock-badge" title="System Time">
      <span className="clock-pulse" />
      <span className="live-time-text">{timeStr}</span>
    </span>
  );
}

// Backward-compatibility export
export const IstClock = LiveClock;

export function CommandTicker({ fxActive = true }) {
  return (
    <div className={`command-ticker ${fxActive ? "fx-ticker-glow" : ""}`}>
      <div className="ticker-label">
        <span className="ticker-pulse-dot" />
        <span>COMMAND OPS</span>
      </div>
      <div className="ticker-track">
        <div className="ticker-content">
          <span>AI SURVEILLANCE & INCIDENT MONITORING ACTIVE</span>
          <span className="ticker-sep">✦</span>
          <span>MULTI-CAMERA COMPUTER VISION ENGINE ONLINE</span>
          <span className="ticker-sep">✦</span>
          <span>COLLISION · FALL · MOTION · RESTRICTED-ZONE DETECTION</span>
          <span className="ticker-sep">✦</span>
          <span>FAST2SMS TELECOM DISPATCH SYSTEM ONLINE</span>
          <span className="ticker-sep">✦</span>
          <span>SHA-256 TAMPER-PROOF FORENSIC EVIDENCE CHAIN</span>
          <span className="ticker-sep">✦</span>
          <span>24×7 REAL-TIME INTELLIGENT MONITORING</span>
          <span className="ticker-sep">✦</span>
        </div>
        <div className="ticker-content" aria-hidden="true">
          <span>AI SURVEILLANCE & INCIDENT MONITORING ACTIVE</span>
          <span className="ticker-sep">✦</span>
          <span>MULTI-CAMERA COMPUTER VISION ENGINE ONLINE</span>
          <span className="ticker-sep">✦</span>
          <span>COLLISION · FALL · MOTION · RESTRICTED-ZONE DETECTION</span>
          <span className="ticker-sep">✦</span>
          <span>FAST2SMS TELECOM DISPATCH SYSTEM ONLINE</span>
          <span className="ticker-sep">✦</span>
          <span>SHA-256 TAMPER-PROOF FORENSIC EVIDENCE CHAIN</span>
          <span className="ticker-sep">✦</span>
          <span>24×7 REAL-TIME INTELLIGENT MONITORING</span>
          <span className="ticker-sep">✦</span>
        </div>
      </div>
    </div>
  );
}
