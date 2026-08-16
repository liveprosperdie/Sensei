import sharp from "sharp"

const IN = "public/akira-raw.png"
const OUT = "public/akira.png"
const TOLERANCE = 18 // how close to white counts as background

const { data, info } = await sharp(IN)
  .ensureAlpha()
  .raw()
  .toBuffer({ resolveWithObject: true })

const { width, height, channels } = info

const isWhite = (i) =>
  255 - data[i] <= TOLERANCE &&
  255 - data[i + 1] <= TOLERANCE &&
  255 - data[i + 2] <= TOLERANCE

// BFS flood fill from all border pixels
const visited = new Uint8Array(width * height)
const queue = []
for (let x = 0; x < width; x++) {
  queue.push(x, (height - 1) * width + x)
}
for (let y = 0; y < height; y++) {
  queue.push(y * width, y * width + (width - 1))
}

while (queue.length) {
  const p = queue.pop()
  if (visited[p]) continue
  visited[p] = 1
  const i = p * channels
  if (!isWhite(i)) continue
  data[i + 3] = 0 // make transparent
  const x = p % width
  const y = (p / width) | 0
  if (x > 0) queue.push(p - 1)
  if (x < width - 1) queue.push(p + 1)
  if (y > 0) queue.push(p - width)
  if (y < height - 1) queue.push(p + width)
}

// Soften edges: any opaque pixel adjacent to transparent gets partial alpha
const alphaCopy = new Uint8Array(width * height)
for (let p = 0; p < width * height; p++) alphaCopy[p] = data[p * channels + 3]
for (let y = 1; y < height - 1; y++) {
  for (let x = 1; x < width - 1; x++) {
    const p = y * width + x
    if (alphaCopy[p] === 0) continue
    let transparentNeighbors = 0
    if (alphaCopy[p - 1] === 0) transparentNeighbors++
    if (alphaCopy[p + 1] === 0) transparentNeighbors++
    if (alphaCopy[p - width] === 0) transparentNeighbors++
    if (alphaCopy[p + width] === 0) transparentNeighbors++
    if (transparentNeighbors > 0) {
      data[p * channels + 3] = Math.max(0, 255 - transparentNeighbors * 80)
    }
  }
}

await sharp(data, { raw: { width, height, channels } })
  .png()
  .trim({ threshold: 1 })
  .toFile(OUT)

console.log("[v0] Cutout complete:", OUT)
