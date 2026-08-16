"use client"

import { SENSEI_STATES, STATE_LABELS, useMockSenseiState } from "./state"
import Scholar from "./avatars/Scholar"
import HoodedSpirit from "./avatars/HoodedSpirit"
import FoxSage from "./avatars/FoxSage"
import OrbSpirit from "./avatars/OrbSpirit"

const CONCEPTS = [
  {
    id: "hooded",
    name: "Hooded Spirit",
    tagline: "Calm, mysterious, mature. Leans into the sensei fantasy.",
    Component: HoodedSpirit,
  },
  {
    id: "fox",
    name: "Fox Sage",
    tagline: "Warm kitsune companion. Most expressive, broadest charm.",
    Component: FoxSage,
  },
  {
    id: "orb",
    name: "Orb Spirit",
    tagline: "Minimal glass orb. Cleanest fit next to productivity tools.",
    Component: OrbSpirit,
  },
]

export default function App() {
  const { state, auto, setAuto, select } = useMockSenseiState()

  return (
    <main className="page">
      <header className="header">
        <h1 className="title">Sensei — The Scholar</h1>
        <p className="subtitle">
          Primary avatar built from your reference: the cozy library scholar. Driven by the same mock state machine
          the backend will replace over WebSocket. Move your cursor — her eyes follow it.
        </p>
      </header>

      <section className="controls" aria-label="State controls">
        <div className="state-buttons" role="group" aria-label="Avatar state">
          {SENSEI_STATES.map((s) => (
            <button
              key={s}
              type="button"
              className={`state-btn ${state === s ? "active" : ""} btn-${s}`}
              onClick={() => select(s)}
              aria-pressed={state === s}
            >
              {STATE_LABELS[s]}
            </button>
          ))}
        </div>
        <label className="auto-toggle">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
          <span>Auto-cycle states</span>
        </label>
      </section>

      <section className="featured" aria-label="Primary avatar">
        <article className="card featured-card">
          <div className="stage featured-stage">
            <Scholar state={state} />
          </div>
          <div className="card-meta">
            <h2 className="card-name">The Scholar</h2>
            <p className="card-tagline">
              Chestnut bob, round wire glasses, rust cable-knit over teal. Blinks, breathes, tracks your cursor, and
              changes expression per state — brows, eyelids, gaze, and mouth are all independent layers.
            </p>
          </div>
        </article>
      </section>

      <section className="gallery" aria-label="Earlier concepts">
        {CONCEPTS.map(({ id, name, tagline, Component }) => (
          <article key={id} className="card">
            <div className="stage">
              <Component state={state} />
            </div>
            <div className="card-meta">
              <h2 className="card-name">{name}</h2>
              <p className="card-tagline">{tagline}</p>
            </div>
          </article>
        ))}
      </section>

      <footer className="footnote">
        <p>
          Current state: <span className="state-chip">{STATE_LABELS[state]}</span> — each avatar reacts with its own
          eyes, posture, and effects. The winning concept becomes the transparent Tauri overlay.
        </p>
      </footer>
    </main>
  )
}
