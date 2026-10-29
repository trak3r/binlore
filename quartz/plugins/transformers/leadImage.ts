import { Root as HTMLRoot, Element } from "hast"
import { visit, EXIT } from "unist-util-visit"
import { createHash } from "crypto"
import { extname, basename } from "path"
import { QuartzTransformerPlugin } from "../types"

const imageExtensions = new Set([".jpg", ".jpeg", ".png", ".webp", ".gif"])

// Picks the first remote image in a page's body and assigns it a stable local path under og/,
// which the LeadImages emitter populates and Head advertises as the social preview image.
export const LeadImage: QuartzTransformerPlugin = () => ({
  name: "LeadImage",
  htmlPlugins() {
    return [
      () => {
        return (tree: HTMLRoot, file) => {
          let src: string | undefined
          visit(tree, "element", (node: Element) => {
            const candidate = node.tagName === "img" ? node.properties?.src : undefined
            if (typeof candidate === "string" && /^https?:\/\//.test(candidate)) {
              src = candidate
              return EXIT
            }
          })
          if (!src) return

          const pathname = new URL(src).pathname
          const ext = extname(pathname).toLowerCase()
          if (!imageExtensions.has(ext)) return

          const stem = basename(pathname, extname(pathname)).replace(/[^\w-]/g, "")
          const hash = createHash("sha1").update(src).digest("hex").slice(0, 8)
          file.data.leadImageSrc = src
          file.data.leadImage = `og/${stem}-${hash}${ext}`
        }
      },
    ]
  },
})

declare module "vfile" {
  interface DataMap {
    leadImageSrc: string
    leadImage: string
  }
}
