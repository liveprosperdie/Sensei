"use client"

import { useRef } from "react"
import type { SenseiState } from "../state"
import { useBlink, usePupilOffset } from "../hooks"

/**
 * Concept C — Orb Spirit
 * Ultra-minimal modern companion. A soft glass orb with expressive eyes.
 * The most "professional" option — reads well next to productivity tools.
 */
export default function OrbSpirit({ state }: { state: SenseiState }) {
  const ref = useRef<HTMLDivElement>(null)
  const blinking = useBlink()
  const pupil = usePupilOffset(ref, 5)

  const eyesClosed = blinking || state === "thinking"
  const core =
    state === "guarded" ? "#ff5d5d" : state === "acting" ? "#34d399" : state === "listening" ? "#818cf8" : "#38bdf8"

  const eyeRy = eyesClosed ? 0.8 : state === "guarded" ? 5 : state === "listening" ? 10 : 8.5

  return (
    <div ref={ref} className={`avatar-root float-anim state-${state}`} aria-label={`Sensei orb avatar, ${state}`}>
      <svg viewBox="0 0 160 180" width="160" height="180" role="img">
        <defs>
          <radialGradient id="orb-body" cx="38%" cy="32%" r="75%">
            <stop offset="0%" stopColor="#3a4358" />
            <stop offset="70%" stopColor="#1e2433" />
            <stop offset="100%" stopColor="#151a26" />
          </radialGradient>
          <radialGradient id="orb-core" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor={core} stopOpacity="0.55" />
            <stop offset="100%" stopColor={core} stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* floating shadow */}
        <ellipse cx="80" cy="168" rx="32" ry="6" fill="rgba(0,0,0,0.35)" className="shadow-anim" />

        {/* orb body — breathing */}
        <g className="breathe">
          <circle cx="80" cy="88" r="54" fill="url(#orb-body)" />
          {/* inner energy core */}
          <circle cx="80" cy="88" r="44" fill="url(#orb-core)" className="aura-pulse" />
          {/* glass highlight */}
          <ellipse cx="60" cy="60" rx="16" ry="10" fill="#ffffff" opacity="0.14" transform="rotate(-24 60 60)" />
          {/* rim light */}
          <circle cx="80" cy="88" r="53" fill="none" stroke={core} strokeWidth="1.4" opacity="0.5" />
        </g>

        {/* face */}
        <g transform={`translate(${pupil.x}, ${pupil.y})`}>
          <ellipse cx="64" cy="86" rx="6" ry={eyeRy} fill={core} className="eye-glow" />
          <ellipse cx="96" cy="86" rx="6" ry={eyeRy} fill={core} className="eye-glow" />
        </g>

        {/* mouth by state */}
        {state === "acting" && <path d="M72 106 Q80 113 88 106" stroke={core} strokeWidth="2.4" fill="none" strokeLinecap="round" />}
        {state === "idle" && <path d="M75 106 Q80 110 85 106" stroke={core} strokeWidth="2" fill="none" strokeLinecap="round" opacity="0.8" />}
        {state === "listening" && <circle cx="80" cy="107" r="3.4" fill={core} opacity="0.9" />}
        {state === "guarded" && <path d="M73 108 Q80 104 87 108" stroke={core} strokeWidth="2.4" fill="none" strokeLinecap="round" />}
        {state === "thinking" && <path d="M74 107 L86 107" stroke={core} strokeWidth="2.2" strokeLinecap="round" opacity="0.8" />}

        {/* thinking: orbiting thought dots */}
        {state === "thinking" && (
          <g className="orbit" fill={core}>
            <circle cx="80" cy="20" r="3" />
            <circle cx="118" cy="34" r="2.2" opacity="0.7" />
            <circle cx="42" cy="34" r="2.5" opacity="0.8" />
          </g>
        )}

        {/* acting: energy ring */}
        {state === "acting" && (
          <circle cx="80" cy="88" r="62" fill="none" stroke={core} strokeWidth="1.6" strokeDasharray="4 14" className="shield-spin" opacity="0.7" />
        )}

        {/* listening: ripples */}
        {state === "listening" && (
          <g stroke={core} fill="none" strokeLinecap="round">
            <path d="M142 74 Q150 88 142 102" strokeWidth="2.4" className="ripple r1" />
            <path d="M150 66 Q162 88 150 110" strokeWidth="2" className="ripple r2" />
            <path d="M18 74 Q10 88 18 102" strokeWidth="2.4" className="ripple r1" />
            <path d="M10 66 Q-2 88 10 110" strokeWidth="2" className="ripple r2" />
          </g>
        )}

        {/* guarded: hex shield */}
        {state === "guarded" && (
          <circle cx="80" cy="88" r="64" fill="none" stroke={core} strokeWidth="1.6" strokeDasharray="7 9" className="shield-spin" opacity="0.8" />
        )}
      </svg>
    </div>
  )
}
