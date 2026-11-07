import { QuartzComponent, QuartzComponentConstructor, QuartzComponentProps } from "./types"
// @ts-ignore
import episodesScript from "./scripts/episodes.inline"
import style from "./styles/footer.scss"
import { version } from "../../package.json"
import { i18n } from "../i18n"
import { pathToRoot } from "../util/path"

interface Options {
  links: Record<string, string>
}

const brandIcons: Record<string, string> = {
  twitch:
    "M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714Z",
  youtube:
    "M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z",
  tiktok:
    "M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.15 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z",
}

function brandOf(link: string): string | undefined {
  return Object.keys(brandIcons).find(
    (brand) => link.includes(`${brand}.com`) || link.includes(`${brand}.tv`),
  )
}

const BrandIcon = ({ brand }: { brand: string }) => (
  <svg class="footer-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <path d={brandIcons[brand]} />
  </svg>
)

const ScaleIcon = () => (
  <svg
    class="footer-icon"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z" />
    <path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z" />
    <path d="M7 21h10" />
    <path d="M12 3v18" />
    <path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2" />
  </svg>
)

export default ((opts?: Options) => {
  const Footer: QuartzComponent = ({ displayClass, cfg, fileData }: QuartzComponentProps) => {
    const year = new Date().getFullYear()
    const links = opts?.links ?? []
    const baseDir = pathToRoot(fileData.slug!)
    const disclaimerHref = baseDir === "." ? "./disclaimer" : `${baseDir}/disclaimer`
    return (
      <footer class={`${displayClass ?? ""}`}>
        <p>
          {i18n(cfg.locale).components.footer.createdWith}{" "}
          <a href="https://quartz.jzhao.xyz/">Quartz v{version}</a> © {year}
        </p>
        <ul class="footer-links">
          {Object.entries(links).map(([text, link]) => {
            const brand = brandOf(link)
            return (
              <li>
                <a
                  href={link}
                  class={brand ? `footer-link-${brand}` : undefined}
                  target={link.startsWith("http") ? "_blank" : undefined}
                  rel={link.startsWith("http") ? "noopener noreferrer" : undefined}
                >
                  {brand && <BrandIcon brand={brand} />}
                  <span>{text}</span>
                </a>
              </li>
            )
          })}
          <li>
            <a href={disclaimerHref}>
              <ScaleIcon />
              <span>Legal Disclaimer</span>
            </a>
          </li>
        </ul>
        <div class="bmac-footer-pill">
          <a
            href="https://buymeacoffee.com/teflonted"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Support the BIN Lore project on Buy Me a Coffee"
          >
            <span class="bmac-coffee-emoji">☕</span>
            <span>Support BIN Lore development on Buy Me a Coffee</span>
          </a>
        </div>
        <p class="footer-disclaimer">
          <strong>Fan Site Disclaimer:</strong> BIN Lore is an unofficial, non-commercial fan
          documentation project. Not affiliated with, endorsed by, or sponsored by Case Blackwell,
          Barely Informed News, or Twitch. All character names, trademarks, and media assets belong
          to their respective owners and are referenced under fair use (17 U.S.C. § 107) for
          commentary, criticism, and archival purposes. Not operated for profit.{" "}
          <a href={disclaimerHref}>Read full disclaimer</a>.
        </p>
      </footer>
    )
  }

  Footer.css = style
  Footer.afterDOMLoaded = episodesScript
  return Footer
}) satisfies QuartzComponentConstructor
