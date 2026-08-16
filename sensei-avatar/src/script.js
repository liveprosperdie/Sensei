// Akira desktop avatar — idle motion + interactions
const stage = document.getElementById("stage")
const container = document.getElementById("avatar-container")
const bubble = document.getElementById("speech-bubble")
const particles = document.getElementById("particles")

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches

// ---------- Idle animation scheduler ----------
const IDLE_CLASSES = ["sway", "tilt", "stretch", "bounce-idle"]
let idleTimer = null
let busy = false

function playClass(cls, duration) {
  if (busy) return
  busy = true
  stage.classList.add(cls)
  setTimeout(() => {
    stage.classList.remove(cls)
    busy = false
  }, duration)
}

function scheduleIdle() {
  clearTimeout(idleTimer)
  // Random idle motion every 6–14 seconds
  const delay = 6000 + Math.random() * 8000
  idleTimer = setTimeout(() => {
    if (!reducedMotion) {
      const cls = IDLE_CLASSES[Math.floor(Math.random() * IDLE_CLASSES.length)]
      const durations = { sway: 2600, tilt: 1800, stretch: 2200, "bounce-idle": 1400 }
      playClass(cls, durations[cls])
    }
    scheduleIdle()
  }, delay)
}
scheduleIdle()

// ---------- Speech bubble ----------
const GREETINGS = [
  "Hey there!",
  "Need something?",
  "Back to work!",
  "You've got this.",
  "Hmm?",
  "One step at a time.",
  "Stay focused!",
  "I'm watching you code...",
]
const PAT_LINES = ["Hehe~", "That tickles!", "Okay, okay!", "Thanks!", "Again!"]

let bubbleTimer = null
function say(text, ms = 2200) {
  bubble.textContent = text
  bubble.classList.add("visible")
  clearTimeout(bubbleTimer)
  bubbleTimer = setTimeout(() => bubble.classList.remove("visible"), ms)
}

// ---------- Heart particles ----------
function spawnHearts(count = 5) {
  if (reducedMotion) return
  const rect = stage.getBoundingClientRect()
  for (let i = 0; i < count; i++) {
    const h = document.createElement("span")
    h.className = "heart"
    h.textContent = Math.random() > 0.3 ? "\u2665" : "\u2726" // hearts + sparkles
    h.style.color = Math.random() > 0.5 ? "#e8607a" : "#f0a04b"
    h.style.left = rect.width * (0.35 + Math.random() * 0.3) + "px"
    h.style.top = rect.height * (0.25 + Math.random() * 0.2) + "px"
    h.style.setProperty("--dx", (Math.random() * 60 - 30).toFixed(0) + "px")
    h.style.setProperty("--r", (Math.random() * 30 - 15).toFixed(0) + "deg")
    h.style.animationDelay = (i * 0.09).toFixed(2) + "s"
    particles.appendChild(h)
    setTimeout(() => h.remove(), 2200)
  }
}

// ---------- Interactions ----------
// Hover: perk up once per mouseenter
container.addEventListener("mouseenter", () => {
  if (!reducedMotion) playClass("perk", 500)
})

// Double-click: pat reaction (single click starts a window drag via
// data-tauri-drag-region, so dblclick is the reliable interaction)
container.addEventListener("dblclick", () => {
  stage.classList.remove("pat")
  // Force reflow so the animation can restart back-to-back
  void stage.offsetWidth
  stage.classList.add("pat")
  setTimeout(() => stage.classList.remove("pat"), 900)
  spawnHearts(4 + Math.floor(Math.random() * 4))
  say(PAT_LINES[Math.floor(Math.random() * PAT_LINES.length)], 1800)
})

// Occasional unprompted remark every 45–120 seconds
function scheduleRemark() {
  const delay = 45000 + Math.random() * 75000
  setTimeout(() => {
    say(GREETINGS[Math.floor(Math.random() * GREETINGS.length)])
    scheduleRemark()
  }, delay)
}
scheduleRemark()

// ---------- Eye tracking: pupils + body lean follow the cursor ----------
const lean = document.getElementById("lean")
const avatar = document.getElementById("avatar")
const pupilLeft = document.getElementById("pupil-left")
const pupilRight = document.getElementById("pupil-right")

let cursorInside = false
let glanceTimer = null

function setGaze(nx, ny) {
  // nx, ny are normalized -1..1 from the face center
  const maxX = avatar.clientWidth * 0.011
  const maxY = avatar.clientHeight * 0.007
  // Quantize to 2px steps to keep the pixel-art feel
  const px = Math.round((nx * maxX) / 2) * 2
  const py = Math.round((ny * maxY) / 2) * 2
  for (const p of [pupilLeft, pupilRight]) {
    p.style.setProperty("--px", px + "px")
    p.style.setProperty("--py", py + "px")
  }
  if (!reducedMotion) {
    lean.style.transform = `translateX(${(nx * 5).toFixed(1)}px) rotate(${(nx * 1.2).toFixed(2)}deg)`
  }
}

function resetGaze() {
  setGaze(0, 0)
  lean.style.transform = ""
}

window.addEventListener("mousemove", (e) => {
  cursorInside = true
  const rect = avatar.getBoundingClientRect()
  // Face center: between the eyes, ~33% down the sprite
  const cx = rect.left + rect.width * 0.445
  const cy = rect.top + rect.height * 0.334
  const nx = Math.max(-1, Math.min(1, (e.clientX - cx) / (rect.width * 0.6)))
  const ny = Math.max(-1, Math.min(1, (e.clientY - cy) / (rect.height * 0.5)))
  setGaze(nx, ny)
})

// When the cursor leaves the window, drift back to center after a beat
document.addEventListener("mouseleave", () => {
  cursorInside = false
  setTimeout(() => {
    if (!cursorInside) resetGaze()
  }, 900)
})

// Idle glances: when the cursor is away, occasionally look around
function scheduleGlance() {
  clearTimeout(glanceTimer)
  glanceTimer = setTimeout(() => {
    if (!cursorInside && !reducedMotion) {
      setGaze(Math.random() * 2 - 1, Math.random() * 1.2 - 0.4)
      setTimeout(() => {
        if (!cursorInside) resetGaze()
      }, 1200 + Math.random() * 1500)
    }
    scheduleGlance()
  }, 8000 + Math.random() * 12000)
}
scheduleGlance()

// Greet on launch
setTimeout(() => say("Hey there!"), 800)
