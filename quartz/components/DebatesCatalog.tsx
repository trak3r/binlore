import { QuartzComponent, QuartzComponentConstructor, QuartzComponentProps } from "./types"
// @ts-ignore
import script from "./scripts/debates.inline"
import style from "./styles/debates.scss"
import { classNames } from "../util/lang"

const DebatesCatalog: QuartzComponent = ({ displayClass }: QuartzComponentProps) => {
  return (
    <div class={classNames(displayClass, "debates-catalog")} data-debates-root>
      <div data-main>
        <section class="debates-scoreboard" data-scoreboard aria-live="polite"></section>

        <h2>Catalog</h2>
        <div class="debates-controls">
          <label>
            Search
            <input type="search" data-q placeholder="Topic, summary, winner…" />
          </label>
          <label>
            Year
            <select data-year></select>
          </label>
          <label>
            Winner
            <select data-winner></select>
          </label>
          <label>
            Participant
            <select data-participant></select>
          </label>
          <div class="debates-count" data-count></div>
        </div>

        <div class="debates-table-wrap">
          <table class="debates-table">
            <thead>
              <tr>
                <th data-sort="date">Date</th>
                <th data-sort="topic">Topic</th>
                <th>Participants</th>
                <th data-sort="winner">Winner</th>
                <th>Summary</th>
              </tr>
            </thead>
            <tbody data-tbody>
              <tr>
                <td colspan={5} class="debates-empty">
                  Loading debates…
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

DebatesCatalog.css = style
DebatesCatalog.afterDOMLoaded = script

export default (() => DebatesCatalog) satisfies QuartzComponentConstructor
