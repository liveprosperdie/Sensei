"use client"

import { useRef } from "react"
import type { SenseiState } from "../state"
import { useBlink, usePupilOffset } from "../hooks"

/**
 * Concept B — Fox Sage
 * A small kitsune spirit. Warm, friendly, expressive ears and tail.
 */
export default function FoxSage({ state }: { state: SenseiState }) {
  const ref = useRef<HTMLDivElement>(null)
  const blinking = useBlink()
  const pupil = usePupilOffset(ref, 4)

  const eyesClosed = blinking || state === "thinking"
  const accent =
    state === "guarded" ? "#ff6b5d" : state === "acting" ? "#5eead4" : state === "listening" ? "#93b4ff" : "#ffb35c"

  // ear rotation: listening perks up, guarded flattens back
  const earAngle = state === "listening" ? -10 : state === "guarded" ? 24 : 0

  return (
    <div ref={ref} className={`avatar-root float-anim state-${state}`} aria-label={`Sensei fox avatar, ${state}`}>
      <svg viewBox="0 0 170 180" width="170" height="180" role="img">
        <defs>
          <linearGradient id="fx-fur" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f5f0e8" />
            <stop offset="100%" stopColor="#e3dbcd" />
          </linearGradient>
          <linearGradient id="fx-marking" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#e8863a" />
            <stop offset="100%" stopColor="#c96b28" />
          </linearGradient>
        </defs>

        {/* floating shadow */}
        <ellipse cx="85" cy="170" rx="36" ry="6" fill="rgba(0,0,0,0.35)" className="shadow-anim" />

        {/* tail — swishes */}
        <g className={state === "acting" ? "tail-fast" : "tail-slow"}>
          <path d="M124 118 C154 110 160 84 148 66 C150 92 138 104 118 108 Z" fill="url(#fx-marking)" />
          <path d="M148 66 C150 80 145 92 133 100 C142 90 146 78 144 70 Z" fill="#f5f0e8" />
        </g>

        {/* body — breathing */}
        <g className="breathe">
          <ellipse cx="85" cy="126" rx="40" ry="34" fill="url(#fx-fur)" />
          {/* chest marking */}
          <ellipse cx="85" cy="134" rx="24" ry="22" fill="#faf7f0" />
          {/* paws */}
          <ellipse cx="66" cy="154" rx="10" ry="7" fill="#e8863a" opacity="0.85" />
          <ellipse cx="104" cy="154" rx="10" ry="7" fill="#e8863a" opacity="0.85" />
        </g>

        {/* head group */}
        <g className="head-tilt">
          {/* ears */}
          <g transform={`rotate(${-earAngle} 56 30)`}>
            <path d="M48 44 L40 8 L70 30 Z" fill="url(#fx-marking)" />
            <path d="M50 38 L46 18 L62 30 Z" fill="#2e2620" />
          </g>
          <g transform={`rotate(${earAngle} 114 30)`}>
            <path d="M122 44 L130 8 L100 30 Z" fill="url(#fx-marking)" />
            <path d="M120 38 L124 18 L108 30 Z" fill="#2e2620" />
          </g>

          {/* head */}
          <ellipse cx="85" cy="62" rx="41" ry="36" fill="url(#fx-fur)" />
          {/* cheek markings */}
          <path d="M46 62 C50 50 60 42 72 40 C60 48 52 56 50 68 Z" fill="url(#fx-marking)" opacity="0.9" />
          <path d="M124 62 C120 50 110 42 98 40 C110 48 118 56 120 68 Z" fill="url(#fx-marking)" opacity="0.9" />

          {/* eyes */}
          <g transform={`translate(${pupil.x}, ${pupil.y})`}>
            {eyesClosed ? (
              <g stroke="#2e2620" strokeWidth="2.6" fill="none" strokeLinecap="round">
                <path d="M62 62 Q69 66 76 62" />
                <path d="M94 62 Q101 66 108 62" />
              </g>
            ) : (
              <g>
                <ellipse cx="69" cy="61" rx="6.5" ry={state === "guarded" ? 4.5 : 7.5} fill="#2e2620" />
                <ellipse cx="101" cy="61" rx="6.5" ry={state === "guarded" ? 4.5 : 7.5} fill="#2e2620" />
                <circle cx="71" cy="58.5" r="2" fill="#fff" />
                <circle cx="103" cy="58.5" r="2" fill="#fff" />
              </g>
            )}
          </g>

          {/* snout + nose */}
          <ellipse cx="85" cy="76" rx="12" ry="9" fill="#faf7f0" />
          <path d="M81 73 L89 73 L85 78 Z" fill="#2e2620" />

          {/* mouth by state */}
          {state === "acting" && <path d="M78 82 Q85 88 92 82" stroke="#2e2620" strokeWidth="2" fill="none" strokeLinecap="round" />}
          {state === "idle" && <path d="M81 82 Q85 85 89 82" stroke="#2e2620" strokeWidth="1.8" fill="none" strokeLinecap="round" />}
          {state === "guarded" && <path d="M79 84 Q85 81 91 84" stroke="#2e2620" strokeWidth="2" fill="none" strokeLinecap="round" />}
          {state === "listening" && <ellipse cx="85" cy="83" rx="3" ry="4" fill="#2e2620" />}
          {state === "thinking" && <path d="M80 83 L90 83" stroke="#2e2620" strokeWidth="2" strokeLinecap="round" />}

          {/* guarded blush of alarm / thinking sweat drop */}
          {state === "thinking" && <path d="M118 46 C122 52 122 56 118 58 C114 56 114 52 118 46 Z" fill="#93b4ff" opacity="0.9" className="drop-anim" />}
        </g>

        {/* state accent: floating wisp orbs (kitsune fire) */}
        <g className="orbit">
          <circle cx="30" cy="52" r={state === "acting" ? 4 : 3} fill={accent} opacity="0.9" />
          <circle cx="146" cy="130" r={state === "acting" ? 3.4 : 2.4} fill={accent} opacity="0.7" />
        </g>

        {/* listening ripples */}
        {state === "listening" && (
          <g stroke="#93b4ff" fill="none" strokeLinecap="round">
            <path d="M138 50 Q146 62 138 74" strokeWidth="2.4" className="ripple r1" />
            <path d="M146 44 Q158 62 146 80" strokeWidth="2" className="ripple r2" />
          </g>
        )}

        {/* guarded shield */}
        {state === "guarded" && (
          <ellipse cx="85" cy="95" rx="66" ry="74" fill="none" stroke="#ff6b5d" strokeWidth="1.6" strokeDasharray="6 10" className="shield-spin" opacity="0.75" />
        )}
      </svg>
    </div>
  )
}
