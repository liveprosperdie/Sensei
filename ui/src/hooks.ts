import { useEffect, useRef, useState } from "react"
import type { RefObject } from "react"

/** Random natural blinking. Returns true while the eyelids are closed. */
export function useBlink(minMs = 2600, maxMs = 5600) {
  const [blinking, setBlinking] = useState(false)

  useEffect(() => {
    let alive = true
    let timer: number

    const schedule = () => {
      timer = window.setTimeout(
        () => {
          if (!alive) return
          setBlinking(true)
          window.setTimeout(() => {
            if (!alive) return
            setBlinking(false)
            schedule()
          }, 130)
        },
        minMs + Math.random() * (maxMs - minMs),
      )
    }

    schedule()
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [minMs, maxMs])

  return blinking
}

/**
 * Tracks the cursor and returns a clamped pupil offset in px,
 * relative to the center of the referenced element.
 */
export function usePupilOffset(ref: RefObject<HTMLElement | null>, range = 4) {
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const frame = useRef(0)

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      cancelAnimationFrame(frame.current)
      frame.current = requestAnimationFrame(() => {
        const el = ref.current
        if (!el) return
        const rect = el.getBoundingClientRect()
        const cx = rect.left + rect.width / 2
        const cy = rect.top + rect.height / 2
        const dx = e.clientX - cx
        const dy = e.clientY - cy
        const dist = Math.hypot(dx, dy) || 1
        const clamped = Math.min(dist, 240) / 240
        setOffset({
          x: (dx / dist) * clamped * range,
          y: (dy / dist) * clamped * range,
        })
      })
    }

    window.addEventListener("mousemove", onMove)
    return () => {
      window.removeEventListener("mousemove", onMove)
      cancelAnimationFrame(frame.current)
    }
  }, [ref, range])

  return offset
}
