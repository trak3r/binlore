import { QuartzComponent, QuartzComponentConstructor, QuartzComponentProps } from "./types"
import style from "./styles/footer.scss"
import { version } from "../../package.json"
import { i18n } from "../i18n"
import { pathToRoot } from "../util/path"

interface Options {
  links: Record<string, string>
}

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
        <ul>
          {Object.entries(links).map(([text, link]) => (
            <li>
              <a
                href={link}
                target={link.startsWith("http") ? "_blank" : undefined}
                rel={link.startsWith("http") ? "noopener noreferrer" : undefined}
              >
                {text}
              </a>
            </li>
          ))}
          <li>
            <a href={disclaimerHref}>Legal Disclaimer</a>
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
            <span>Support BIN Lore hosting on Buy Me a Coffee</span>
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
  return Footer
}) satisfies QuartzComponentConstructor
