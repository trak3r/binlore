import { QuartzConfig } from "./quartz/cfg"
import * as Plugin from "./quartz/plugins"

/**
 * Quartz 4 Configuration — Binlore
 * Fan lore wiki for Barely Informed News (Case Blackwell).
 * See https://quartz.jzhao.xyz/configuration for more information.
 */
const config: QuartzConfig = {
  configuration: {
    pageTitle: "Binlore",
    pageTitleSuffix: " · Barely Informed News",
    enableSPA: true,
    enablePopovers: true,
    analytics: null,
    locale: "en-US",
    baseUrl: "trak3r.github.io/binlore",
    ignorePatterns: ["private", "templates", ".obsidian"],
    defaultDateType: "modified",
    theme: {
      fontOrigin: "googleFonts",
      cdnCaching: true,
      typography: {
        header: "Schibsted Grotesk",
        body: "Source Sans Pro",
        code: "IBM Plex Mono",
      },
      colors: {
        lightMode: {
          light: "#f7f4ef",
          lightgray: "#e4ddd2",
          gray: "#a89f91",
          darkgray: "#3f3a34",
          dark: "#1c1916",
          secondary: "#8b1e1e",
          tertiary: "#c45c26",
          highlight: "rgba(139, 30, 30, 0.12)",
          textHighlight: "#f0c04088",
        },
        darkMode: {
          light: "#161412",
          lightgray: "#2e2a26",
          gray: "#7a7268",
          darkgray: "#d8d0c4",
          dark: "#f2ebe3",
          secondary: "#e07070",
          tertiary: "#e09a5c",
          highlight: "rgba(224, 112, 112, 0.15)",
          textHighlight: "#c45c2688",
        },
      },
    },
  },
  plugins: {
    transformers: [
      Plugin.FrontMatter(),
      Plugin.CreatedModifiedDate({
        priority: ["frontmatter", "git", "filesystem"],
      }),
      Plugin.SyntaxHighlighting({
        theme: {
          light: "github-light",
          dark: "github-dark",
        },
        keepBackground: false,
      }),
      Plugin.ObsidianFlavoredMarkdown({ enableInHtmlEmbed: false }),
      Plugin.GitHubFlavoredMarkdown(),
      Plugin.TableOfContents(),
      Plugin.CrawlLinks({ markdownLinkResolution: "shortest" }),
      Plugin.Description(),
      Plugin.Latex({ renderEngine: "katex" }),
    ],
    filters: [Plugin.RemoveDrafts()],
    emitters: [
      Plugin.AliasRedirects(),
      Plugin.ComponentResources(),
      Plugin.ContentPage(),
      Plugin.FolderPage(),
      Plugin.TagPage(),
      Plugin.ContentIndex({
        enableSiteMap: true,
        enableRSS: true,
      }),
      Plugin.Assets(),
      Plugin.Static(),
      Plugin.Favicon(),
      Plugin.NotFoundPage(),
      // Disabled for faster local builds; re-enable once sharp installs cleanly in CI
      // Plugin.CustomOgImages(),
    ],
  },
}

export default config
