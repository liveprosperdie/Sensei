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

// Greet on launch
setTimeout(() => say("Hey there!"), 800)
