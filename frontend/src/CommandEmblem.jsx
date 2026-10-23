export function CommandEmblem({ size = 28, spinning = true, className = "" }) {
  return (
    <div
      className={`emblem-wrapper ${spinning ? "emblem-pulse" : ""} ${className}`}
      style={{
        width: size,
        height: size,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
      }}
      title="Incident Desk Command Center"
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 100 100"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          {/* Subtle deep warm background */}
          <linearGradient id="emblemDarkBase" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#2e0d04" />
            <stop offset="100%" stopColor="#170501" />
          </linearGradient>

          {/* Warm Amber-Orange Metallic Ring */}
          <linearGradient id="emblemAmberRing" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#fde047" />
            <stop offset="40%" stopColor="#fb923c" />
            <stop offset="100%" stopColor="#ea580c" />
          </linearGradient>

          {/* Luminous Center Optical Sensor Core */}
          <radialGradient id="sensorCoreGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#ffffff" />
            <stop offset="35%" stopColor="#fef08a" />
            <stop offset="70%" stopColor="#f97316" />
            <stop offset="100%" stopColor="#c2410c" />
          </radialGradient>
        </defs>

        {/* Outer Circular Base Shield */}
        <circle cx="50" cy="50" r="46" fill="url(#emblemDarkBase)" stroke="#ffedd5" strokeWidth="2" />

        {/* Precision Outer Calibration Ring */}
        <circle cx="50" cy="50" r="41" stroke="#fdba74" strokeWidth="1.2" strokeDasharray="5 3" />

        {/* Tactical Crosshair Reticle Markers */}
        <line x1="50" y1="8" x2="50" y2="18" stroke="#ffffff" strokeWidth="2.5" strokeLinecap="round" />
        <line x1="50" y1="82" x2="50" y2="92" stroke="#ffffff" strokeWidth="2.5" strokeLinecap="round" />
        <line x1="8" y1="50" x2="18" y2="50" stroke="#ffffff" strokeWidth="2.5" strokeLinecap="round" />
        <line x1="82" y1="50" x2="92" y2="50" stroke="#ffffff" strokeWidth="2.5" strokeLinecap="round" />

        {/* Corner HUD Brackets */}
        <path d="M26 31 L26 26 L31 26" stroke="#fed7aa" strokeWidth="1.8" fill="none" strokeLinecap="round" />
        <path d="M74 31 L74 26 L69 26" stroke="#fed7aa" strokeWidth="1.8" fill="none" strokeLinecap="round" />
        <path d="M26 69 L26 74 L31 74" stroke="#fed7aa" strokeWidth="1.8" fill="none" strokeLinecap="round" />
        <path d="M74 69 L74 74 L69 74" stroke="#fed7aa" strokeWidth="1.8" fill="none" strokeLinecap="round" />

        {/* Middle Surveillance Radar Ring */}
        <circle cx="50" cy="50" r="27" stroke="url(#emblemAmberRing)" strokeWidth="2.5" />
        <circle cx="50" cy="50" r="19" stroke="#fed7aa" strokeWidth="1" strokeDasharray="3 3" opacity="0.8" />

        {/* Center Camera Optical Aperture Core */}
        <circle cx="50" cy="50" r="13" fill="url(#sensorCoreGlow)" />
        <circle cx="50" cy="50" r="6" fill="#ffffff" />
        <circle cx="52" cy="48" r="2.2" fill="#fff7ed" />
      </svg>
    </div>
  );
}
