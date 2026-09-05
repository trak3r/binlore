import { pathToRoot } from "../util/path"
import { QuartzComponent, QuartzComponentConstructor, QuartzComponentProps } from "./types"
import { classNames } from "../util/lang"
import { i18n } from "../i18n"

const PageTitle: QuartzComponent = ({ fileData, cfg, displayClass }: QuartzComponentProps) => {
  const title = cfg?.pageTitle ?? i18n(cfg.locale).propertyDefaults.title
  const baseDir = pathToRoot(fileData.slug!)
  const isBinLore = title === "BIN Lore"
  return (
    <h2 class={classNames(displayClass, "page-title")}>
      <a href={baseDir}>
        {isBinLore ? (
          <span class="bin-brand">
            <span class="bin-badge">BIN</span>
            <span class="bin-text">Lore</span>
          </span>
        ) : (
          title
        )}
      </a>
    </h2>
  )
}

PageTitle.css = `
.page-title {
  font-size: 1.75rem;
  margin: 0;
  font-family: var(--titleFont);
}

.page-title a {
  color: var(--dark);
  text-decoration: none;
}

.bin-brand {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.bin-badge {
  background-color: var(--secondary);
  color: #ffffff !important;
  font-family: var(--titleFont);
  font-weight: 700;
  font-size: 1.1rem;
  line-height: 1;
  padding: 0.2rem 0.45rem 0.18rem;
  border-radius: 4px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  box-shadow: 0 2px 8px rgba(220, 38, 38, 0.35);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

:root[saved-theme="dark"] .bin-badge {
  box-shadow: 0 0 12px rgba(239, 68, 68, 0.45);
}

.page-title a:hover .bin-badge {
  transform: scale(1.05);
  box-shadow: 0 0 16px rgba(239, 68, 68, 0.65);
}

.bin-text {
  font-family: var(--titleFont);
  font-weight: 700;
  font-size: 1.75rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--dark);
  transition: color 0.15s ease;
}

.page-title a:hover .bin-text {
  color: var(--tertiary);
}
`

export default (() => PageTitle) satisfies QuartzComponentConstructor
