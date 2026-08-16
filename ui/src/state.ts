import { useCallback, useEffect, useRef, useState } from "react"

/**
 * Sensei avatar state contract.
 * This is the exact schema the Python backend will emit over WebSocket later:
 *   { "type": "state", "state": "thinking", "ts": 1723800000000 }
 */
export type SenseiState = "idle" | "listening" | "thinking" | "acting" | "guarded"

export interface SenseiStateEvent {
  type: "state"
  state: SenseiState
  ts: number
}

export const SENSEI_STATES: SenseiState[] = ["idle", "listening", "thinking", "acting", "guarded"]

export const STATE_LABELS: Record<SenseiState, string> = {
  idle: "Idle",
  listening: "Listening",
  thinking: "Thinking",
  acting: "Acting",
  guarded: "Guarded",
}

const AUTO_CYCLE_MS = 3500

/**
 * Mock state driver. Stands in for the WebSocket connection to sensei.py.
 * When the backend unfreezes, swap this for a hook that consumes real
 * SenseiStateEvent messages — the components will not change.
 */
export function useMockSenseiState() {
  const [state, setState] = useState<SenseiState>("idle")
  const [auto, setAuto] = useState(true)
  const indexRef = useRef(0)

  useEffect(() => {
    if (!auto) return
    const id = window.setInterval(() => {
      indexRef.current = (indexRef.current + 1) % SENSEI_STATES.length
      setState(SENSEI_STATES[indexRef.current])
    }, AUTO_CYCLE_MS)
    return () => window.clearInterval(id)
  }, [auto])

  const select = useCallback((next: SenseiState) => {
    indexRef.current = SENSEI_STATES.indexOf(next)
    setAuto(false)
    setState(next)
  }, [])

  const event: SenseiStateEvent = { type: "state", state, ts: Date.now() }

  return { state, auto, setAuto, select, event }
}
