import { PageLayout, SharedLayout } from "./quartz/cfg"
import * as Component from "./quartz/components"

/** Compact recently-modified list for post-update review (git dates via CreatedModifiedDate). */
const recentChanges = Component.DesktopOnly(
  Component.RecentNotes({
    title: "Recent changes",
    limit: 8,
    showTags: false,
    filter: (f) => {
      const slug = f.slug ?? ""
      if (!slug || slug === "index") return false
      if (slug.startsWith("tags/")) return false
      if (slug.endsWith("/index")) return false
      return true
    },
  }),
)

// components shared across all pages
export const sharedPageComponents: SharedLayout = {
  head: Component.Head(),
  header: [],
  afterBody: [Component.BuyMeACoffee()],
  footer: Component.Footer({
    links: {
      "Barely Informed News (Twitch)": "https://www.twitch.tv/caseblackwell",
      "YouTube Archive": "https://www.youtube.com/@CaseBlackwellStreams",
      GitHub: "https://github.com/trak3r/binlore",
      "☕ Buy Me a Coffee": "https://buymeacoffee.com/teflonted",
    },
  }),
}

// components for pages that display a single page (e.g. a single note)
export const defaultContentPageLayout: PageLayout = {
  beforeBody: [
    Component.ConditionalRender({
      component: Component.Breadcrumbs(),
      condition: (page) => page.fileData.slug !== "index",
    }),
    Component.ArticleTitle(),
    Component.ContentMeta(),
    Component.TagList(),
  ],
  left: [
    Component.PageTitle(),
    Component.MobileOnly(Component.Spacer()),
    Component.Flex({
      components: [
        {
          Component: Component.Search(),
          grow: true,
        },
        { Component: Component.Darkmode() },
        { Component: Component.ReaderMode() },
      ],
    }),
    Component.Explorer(),
    recentChanges,
  ],
  right: [
    Component.Graph(),
    Component.DesktopOnly(Component.TableOfContents()),
    Component.Backlinks(),
  ],
}

// components for pages that display lists of pages  (e.g. tags or folders)
export const defaultListPageLayout: PageLayout = {
  beforeBody: [Component.Breadcrumbs(), Component.ArticleTitle(), Component.ContentMeta()],
  left: [
    Component.PageTitle(),
    Component.MobileOnly(Component.Spacer()),
    Component.Flex({
      components: [
        {
          Component: Component.Search(),
          grow: true,
        },
        { Component: Component.Darkmode() },
      ],
    }),
    Component.Explorer(),
    recentChanges,
  ],
  right: [],
}
