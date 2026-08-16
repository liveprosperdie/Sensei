"use client"

import { useRef } from "react"
import type { SenseiState } from "../state"
import { useBlink, usePupilOffset } from "../hooks"

/**
 * The Scholar — Sensei's primary avatar.
 * Built from the user's reference: chestnut wavy bob, round wire glasses,
 * warm brown eyes, rust cable-knit sweater over a teal collar.
 * Every facial feature is an independent layer so the backend states
 * (idle / listening / thinking / acting / guarded) drive real expressions.
 */
export default function Scholar({ state }: { state: SenseiState }) {
  const ref = useRef<HTMLDivElement>(null)
  const blinking = useBlink()
  const cursorPupil = usePupilOffset(ref, 3.2)

  // thinking: gaze drifts up and away instead of following the cursor
  const pupil = state === "thinking" ? { x: -2.6, y: -2.8 } : cursorPupil

  // 0 = fully open, 1 = fully closed
  const lidClose = blinking ? 1 : state === "guarded" ? 0.45 : 0
  const lidDrop = lidClose * 14

  const browLift = state === "listening" ? -2.5 : 0

  return (
    <div ref={ref} className={`avatar-root scholar-root state-${state}`} aria-label={`Sensei avatar, ${state}`}>
      <svg viewBox="0 0 200 220" width="200" height="220" role="img">
        <defs>
          <linearGradient id="sc-sweater" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#a4512a" />
            <stop offset="100%" stopColor="#7e3a1c" />
          </linearGradient>
          <linearGradient id="sc-hair" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#5a3822" />
            <stop offset="100%" stopColor="#3c2415" />
          </linearGradient>
          <clipPath id="sc-eye-l">
            <ellipse cx="82" cy="92" rx="8" ry="6.4" />
          </clipPath>
          <clipPath id="sc-eye-r">
            <ellipse cx="118" cy="92" rx="8" ry="6.4" />
          </clipPath>
        </defs>

        {/* ambient glow behind character */}
        <ellipse cx="100" cy="110" rx="86" ry="92" fill="rgba(214, 138, 74, 0.08)" className="aura-pulse" />

        <g className="breathe" style={{ transformOrigin: "50% 90%" }}>
          {/* back hair — falls behind shoulders */}
          <path
            d="M100 30
               C 58 30 40 60 42 98
               C 43 124 50 140 44 156
               C 56 156 62 148 64 138
               C 66 148 60 158 54 164
               C 68 166 76 156 78 146
               L 78 128 L 122 128 L 122 146
               C 124 156 132 166 146 164
               C 140 158 134 148 136 138
               C 138 148 144 156 156 156
               C 150 140 157 124 158 98
               C 160 60 142 30 100 30 Z"
            fill="url(#sc-hair)"
          />

          {/* sweater body */}
          <path
            d="M28 220 C 32 182 56 158 100 156 C 144 158 168 182 172 220 Z"
            fill="url(#sc-sweater)"
          />
          {/* knit texture — soft vertical ribs */}
          <g stroke="#6b2f14" strokeWidth="1.6" opacity="0.45" strokeLinecap="round">
            <path d="M62 172 C 60 188 59 204 59 220" fill="none" />
            <path d="M80 164 C 78 182 77 202 77 220" fill="none" />
            <path d="M100 162 C 100 182 100 202 100 220" fill="none" />
            <path d="M120 164 C 122 182 123 202 123 220" fill="none" />
            <path d="M138 172 C 140 188 141 204 141 220" fill="none" />
          </g>
          {/* cable chevrons */}
          <g stroke="#6b2f14" strokeWidth="1.4" opacity="0.35" fill="none" strokeLinecap="round">
            <path d="M88 186 L 100 194 L 112 186" />
            <path d="M88 202 L 100 210 L 112 202" />
          </g>

          {/* neck */}
          <path d="M89 126 L 111 126 L 111 152 C 104 156 96 156 89 152 Z" fill="#f0c29c" />
          <path d="M89 126 L 111 126 L 111 136 C 104 141 96 141 89 136 Z" fill="#d9a67e" opacity="0.7" />

          {/* teal collar */}
          <path
            d="M80 152 C 86 160 114 160 120 152 L 124 164 C 112 172 88 172 76 164 Z"
            fill="#2e6b64"
          />
          <path d="M76 164 C 88 172 112 172 124 164" stroke="#235049" strokeWidth="1.6" fill="none" opacity="0.8" />

          {/* head group — gentle tilt */}
          <g className="head-tilt" style={{ transformOrigin: "50% 45%" }}>
            {/* face */}
            <ellipse cx="100" cy="88" rx="33" ry="36" fill="#f4cba6" />
            {/* jaw soft shadow */}
            <path d="M74 104 C 80 122 120 122 126 104 C 122 118 108 124 100 124 C 92 124 78 118 74 104 Z" fill="#e2b48c" opacity="0.45" />

            {/* ears */}
            <ellipse cx="66" cy="94" rx="5" ry="8" fill="#f4cba6" />
            <ellipse cx="134" cy="94" rx="5" ry="8" fill="#f4cba6" />

            {/* eyes */}
            <g>
              {/* whites */}
              <ellipse cx="82" cy="92" rx="8" ry="6.4" fill="#fdf6ee" />
              <ellipse cx="118" cy="92" rx="8" ry="6.4" fill="#fdf6ee" />

              {/* iris + pupil, cursor-tracked, clipped inside eye */}
              <g clipPath="url(#sc-eye-l)">
                <g transform={`translate(${pupil.x}, ${pupil.y})`}>
                  <circle cx="82" cy="92" r="4.8" fill="#7a4a22" />
                  <circle cx="82" cy="92" r="2.3" fill="#2c1a10" />
                  <circle cx="80.4" cy="90.2" r="1.2" fill="#ffffff" opacity="0.9" />
                </g>
                {/* eyelid */}
                <rect
                  x="72" y="69.5" width="20" height="16"
                  fill="#f4cba6"
                  style={{ transform: `translateY(${lidDrop}px)`, transition: "transform 0.1s ease-out" }}
                />
              </g>
              <g clipPath="url(#sc-eye-r)">
                <g transform={`translate(${pupil.x}, ${pupil.y})`}>
                  <circle cx="118" cy="92" r="4.8" fill="#7a4a22" />
                  <circle cx="118" cy="92" r="2.3" fill="#2c1a10" />
                  <circle cx="116.4" cy="90.2" r="1.2" fill="#ffffff" opacity="0.9" />
                </g>
                <rect
                  x="108" y="69.5" width="20" height="16"
                  fill="#f4cba6"
                  style={{ transform: `translateY(${lidDrop}px)`, transition: "transform 0.1s ease-out" }}
                />
              </g>
              {/* upper lash lines */}
              <path d="M74.5 89.5 Q 82 85.5 89.5 89.5" stroke="#5a3822" strokeWidth="1.8" fill="none" strokeLinecap="round" />
              <path d="M110.5 89.5 Q 118 85.5 125.5 89.5" stroke="#5a3822" strokeWidth="1.8" fill="none" strokeLinecap="round" />
            </g>

            {/* brows */}
            <g
              stroke="#4a2c18"
              strokeWidth="2.6"
              fill="none"
              strokeLinecap="round"
              style={{ transform: `translateY(${browLift}px)`, transition: "transform 0.25s ease" }}
            >
              {state === "guarded" ? (
                <>
                  <path d="M73 78 L 90 82" />
                  <path d="M127 78 L 110 82" />
                </>
              ) : (
                <>
                  <path d="M73 80 Q 82 76 91 80" />
                  <path d="M109 80 Q 118 76 127 80" />
                </>
              )}
            </g>

            {/* round wire glasses */}
            <g stroke="#4a3527" strokeWidth="2" fill="none">
              <circle cx="82" cy="92" r="13.5" fill="rgba(255,255,255,0.05)" />
              <circle cx="118" cy="92" r="13.5" fill="rgba(255,255,255,0.05)" />
              <path d="M95.5 90 Q 100 87 104.5 90" />
              <path d="M68.5 90 L 66 92" />
              <path d="M131.5 90 L 134 92" />
            </g>
            {/* guarded: lens glint */}
            {state === "guarded" && (
              <g stroke="#ffffff" strokeWidth="1.6" opacity="0.7" strokeLinecap="round">
                <path d="M75 85 L 88 98" />
                <path d="M111 85 L 124 98" />
              </g>
            )}

            {/* nose */}
            <path d="M100 98 Q 102 103 99 105" stroke="#d9a67e" strokeWidth="1.8" fill="none" strokeLinecap="round" />

            {/* blush */}
            <ellipse cx="73" cy="103" rx="5.5" ry="3" fill="#e89a76" opacity="0.4" />
            <ellipse cx="127" cy="103" rx="5.5" ry="3" fill="#e89a76" opacity="0.4" />

            {/* mouth — per state */}
            {state === "acting" ? (
              <path d="M92 111 Q 100 121 108 111 Q 100 116 92 111 Z" fill="#a05438" stroke="#8a4028" strokeWidth="1" />
            ) : state === "guarded" ? (
              <path d="M93 116 Q 100 111.5 107 116" stroke="#a05438" strokeWidth="2.2" fill="none" strokeLinecap="round" />
            ) : state === "thinking" ? (
              <path d="M95 114 L 105 114" stroke="#a05438" strokeWidth="2.2" fill="none" strokeLinecap="round" />
            ) : state === "listening" ? (
              <ellipse cx="100" cy="114" rx="3.4" ry="4" fill="#a05438" />
            ) : (
              <path d="M92 112 Q 100 118 108 112" stroke="#a05438" strokeWidth="2.2" fill="none" strokeLinecap="round" />
            )}

            {/* front hair — bangs and face-framing locks, drawn over everything */}
            <path
              d="M100 30
                 C 62 30 62 56 66 74
                 C 68 62 74 54 84 52
                 C 80 60 79 68 81 74
                 C 84 60 96 50 110 50
                 C 106 56 105 62 107 68
                 C 112 56 124 52 132 58
                 C 136 64 136 70 134 76
                 C 140 66 141 52 134 42
                 C 126 32 114 30 100 30 Z"
              fill="url(#sc-hair)"
            />
            {/* side locks */}
            <path d="M66 70 C 60 84 61 102 66 114 C 70 104 70 84 68 72 Z" fill="url(#sc-hair)" />
            <path d="M134 70 C 140 84 139 102 134 114 C 130 104 130 84 132 72 Z" fill="url(#sc-hair)" />
            {/* caramel highlight strands */}
            <g stroke="#96602f" strokeWidth="2" fill="none" strokeLinecap="round" opacity="0.75">
              <path d="M88 40 C 82 46 79 56 80 66" />
              <path d="M114 42 C 110 48 108 56 109 62" />
              <path d="M65 80 C 63 92 64 102 66 110" />
              <path d="M135 80 C 137 92 136 102 134 110" />
            </g>
          </g>
        </g>

        {/* listening: sound ripples */}
        {state === "listening" && (
          <g stroke="#5cc8bd" fill="none" strokeLinecap="round">
            <path d="M150 82 Q 158 94 150 106" strokeWidth="2.4" className="ripple r1" />
            <path d="M158 76 Q 170 94 158 112" strokeWidth="2" className="ripple r2" />
          </g>
        )}

        {/* thinking: drifting thought dots */}
        {state === "thinking" && (
          <g fill="#d6a86a">
            <circle cx="144" cy="52" r="3" className="drop-anim" />
            <circle cx="154" cy="42" r="4" className="drop-anim" style={{ animationDelay: "0.3s" }} />
            <circle cx="166" cy="30" r="5" className="drop-anim" style={{ animationDelay: "0.6s" }} />
          </g>
        )}

        {/* acting: sparkles */}
        {state === "acting" && (
          <g fill="#ffd58a">
            <path d="M42 60 l 2.4 5.6 5.6 2.4 -5.6 2.4 -2.4 5.6 -2.4 -5.6 -5.6 -2.4 5.6 -2.4 Z" className="drop-anim" />
            <path d="M158 130 l 1.8 4.2 4.2 1.8 -4.2 1.8 -1.8 4.2 -1.8 -4.2 -4.2 -1.8 4.2 -1.8 Z" className="drop-anim" style={{ animationDelay: "0.4s" }} />
            <path d="M36 128 l 1.5 3.5 3.5 1.5 -3.5 1.5 -1.5 3.5 -1.5 -3.5 -3.5 -1.5 3.5 -1.5 Z" className="drop-anim" style={{ animationDelay: "0.8s" }} />
          </g>
        )}

        {/* guarded: warding ring */}
        {state === "guarded" && (
          <ellipse
            cx="100" cy="112" rx="80" ry="96"
            fill="none" stroke="#ff5d5d" strokeWidth="1.6"
            strokeDasharray="6 10" className="shield-spin" opacity="0.7"
          />
        )}
      </svg>
    </div>
  )
}
