"use client"

import { useRef } from "react"
import type { SenseiState } from "../state"
import { useBlink, usePupilOffset } from "../hooks"

/**
 * Concept A — Hooded Sensei Spirit
 * A calm, floating hooded figure. Mature, minimal, slightly mysterious.
 */
export default function HoodedSpirit({ state }: { state: SenseiState }) {
  const ref = useRef<HTMLDivElement>(null)
  const blinking = useBlink()
  const pupil = usePupilOffset(ref, 3.5)

  const eyesClosed = blinking || state === "thinking"
  const eyeGlow =
    state === "guarded" ? "#ff5d5d" : state === "acting" ? "#7ef0c9" : state === "listening" ? "#9db8ff" : "#bfe3ff"
  const auraColor =
    state === "guarded"
      ? "rgba(255, 93, 93, 0.22)"
      : state === "acting"
        ? "rgba(126, 240, 201, 0.2)"
        : state === "listening"
          ? "rgba(157, 184, 255, 0.22)"
          : "rgba(148, 190, 255, 0.12)"

  // thinking: eyes closed meditation; guarded: narrowed; listening: wide
  const eyeHeight = eyesClosed ? 0.6 : state === "guarded" ? 3.2 : state === "listening" ? 6.4 : 5.2

  return (
    <div ref={ref} className={`avatar-root float-anim state-${state}`} aria-label={`Sensei avatar, ${state}`}>
      <svg viewBox="0 0 160 180" width="160" height="180" role="img">
        <defs>
          <radialGradient id="hs-aura" cx="50%" cy="42%" r="55%">
            <stop offset="0%" stopColor={auraColor} />
            <stop offset="100%" stopColor="transparent" />
          </radialGradient>
          <linearGradient id="hs-robe" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3d4460" />
            <stop offset="100%" stopColor="#232739" />
          </linearGradient>
          <linearGradient id="hs-hood" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#4b5378" />
            <stop offset="100%" stopColor="#2e3350" />
          </linearGradient>
        </defs>

        {/* aura */}
        <ellipse cx="80" cy="82" rx="74" ry="80" fill="url(#hs-aura)" className="aura-pulse" />

        {/* floating shadow */}
        <ellipse cx="80" cy="168" rx="34" ry="6" fill="rgba(0,0,0,0.35)" className="shadow-anim" />

        {/* body / robe — breathing */}
        <g className="breathe">
          <path d="M80 58 C46 62 36 96 38 132 C39 150 56 158 80 158 C104 158 121 150 122 132 C124 96 114 62 80 58 Z" fill="url(#hs-robe)" />
          {/* robe fold */}
          <path d="M80 92 C70 108 68 128 72 152" stroke="#1b1f30" strokeWidth="2.5" fill="none" strokeLinecap="round" opacity="0.6" />
          <path d="M92 96 C98 112 99 130 96 150" stroke="#1b1f30" strokeWidth="2" fill="none" strokeLinecap="round" opacity="0.4" />
          {/* sash */}
          <path d="M50 118 C66 126 94 126 110 118 L108 128 C92 135 68 135 52 128 Z" fill="#c9a15e" opacity="0.9" />
        </g>

        {/* head + hood */}
        <g className="head-tilt">
          <ellipse cx="80" cy="52" rx="34" ry="33" fill="url(#hs-hood)" />
          {/* hood opening — dark face cavity */}
          <ellipse cx="80" cy="56" rx="24" ry="23" fill="#141726" />
          {/* hood rim highlight */}
          <path d="M49 44 C56 22 104 22 111 44" stroke="#6b74a3" strokeWidth="3" fill="none" strokeLinecap="round" opacity="0.7" />

          {/* eyes — glowing slits inside the hood */}
          <g transform={`translate(${pupil.x}, ${pupil.y})`}>
            <ellipse cx="70" cy="56" rx="4.6" ry={eyeHeight} fill={eyeGlow} className="eye-glow" />
            <ellipse cx="90" cy="56" rx="4.6" ry={eyeHeight} fill={eyeGlow} className="eye-glow" />
          </g>

          {/* thinking: meditation arc brows */}
          {state === "thinking" && (
            <g stroke={eyeGlow} strokeWidth="2" fill="none" strokeLinecap="round" opacity="0.85">
              <path d="M63 50 Q70 46 77 50" />
              <path d="M83 50 Q90 46 97 50" />
            </g>
          )}
        </g>

        {/* acting: orbiting energy particles */}
        {state === "acting" && (
          <g className="orbit">
            <circle cx="80" cy="18" r="3" fill="#7ef0c9" />
            <circle cx="140" cy="90" r="2.2" fill="#7ef0c9" opacity="0.7" />
            <circle cx="24" cy="110" r="2.6" fill="#7ef0c9" opacity="0.8" />
          </g>
        )}

        {/* listening: sound ripples */}
        {state === "listening" && (
          <g stroke="#9db8ff" fill="none" strokeLinecap="round">
            <path d="M126 46 Q134 56 126 66" strokeWidth="2.4" className="ripple r1" />
            <path d="M134 40 Q146 56 134 72" strokeWidth="2" className="ripple r2" />
          </g>
        )}

        {/* guarded: shield shimmer */}
        {state === "guarded" && (
          <ellipse cx="80" cy="90" rx="62" ry="72" fill="none" stroke="#ff5d5d" strokeWidth="1.6" strokeDasharray="6 10" className="shield-spin" opacity="0.75" />
        )}
      </svg>
    </div>
  )
}
