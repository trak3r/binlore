import fs from "fs"
import { dirname } from "path"
import { FilePath, joinSegments } from "../../util/path"
import { QuartzEmitterPlugin } from "../types"
import { ProcessedContent } from "../vfile"
import { BuildCtx } from "../../util/ctx"

const cacheDir = ".quartz-cache/og"
const concurrency = 8

// Remote hosts (e.g. GitHub release assets) serve images as application/octet-stream downloads,
// which link-preview crawlers like Discord reject, so preview images are mirrored onto our domain.
async function mirrorLeadImages({ argv }: BuildCtx, content: ProcessedContent[]) {
  const wanted = new Map<string, string>()
  for (const [, file] of content) {
    const { leadImage, leadImageSrc } = file.data
    if (leadImage && leadImageSrc) wanted.set(leadImage, leadImageSrc)
  }

  await fs.promises.mkdir(cacheDir, { recursive: true })
  const emitted: FilePath[] = []
  const queue = [...wanted.entries()]

  async function worker() {
    for (let next = queue.shift(); next; next = queue.shift()) {
      const [relPath, src] = next
      const cached = joinSegments(cacheDir, relPath.replace(/^og\//, ""))
      const dest = joinSegments(argv.output, relPath) as FilePath
      try {
        if (!fs.existsSync(cached)) {
          const res = await fetch(src)
          if (!res.ok) throw new Error(`HTTP ${res.status}`)
          await fs.promises.writeFile(cached, Buffer.from(await res.arrayBuffer()))
        }
        await fs.promises.mkdir(dirname(dest), { recursive: true })
        await fs.promises.copyFile(cached, dest)
        emitted.push(dest)
      } catch (err) {
        console.warn(`[LeadImages] could not mirror ${src}: ${err}`)
      }
    }
  }

  await Promise.all(Array.from({ length: concurrency }, worker))
  return emitted
}

export const LeadImages: QuartzEmitterPlugin = () => ({
  name: "LeadImages",
  async emit(ctx, content) {
    return mirrorLeadImages(ctx, content)
  },
  async partialEmit(ctx, content) {
    return mirrorLeadImages(ctx, content)
  },
})
