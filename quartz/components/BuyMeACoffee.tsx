import { QuartzComponent, QuartzComponentConstructor, QuartzComponentProps } from "./types"

const BuyMeACoffee: QuartzComponent = ({ displayClass }: QuartzComponentProps) => {
  return (
    <div class={`buymeacoffee-widget ${displayClass ?? ""}`}>
      <script
        data-name="BMC-Widget"
        data-cfasync="false"
        src="https://cdnjs.buymeacoffee.com/1.0.0/widget.prod.min.js"
        data-id="teflonted"
        data-description="Support me on Buy me a coffee!"
        data-message="Support the BIN Lore project!"
        data-color="#dc2626"
        data-position="Right"
        data-x_margin="18"
        data-y_margin="18"
      ></script>
    </div>
  )
}

export default (() => BuyMeACoffee) satisfies QuartzComponentConstructor
