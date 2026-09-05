import { QuartzConfig } from "./quartz/cfg"
import * as Plugin from "./quartz/plugins"

/**
 * Quartz 4 Configuration — BIN Lore
 * Fan lore wiki for Barely Informed News (Case Blackwell).
 * See https://quartz.jzhao.xyz/configuration for more information.
 */
const config: QuartzConfig = {
  configuration: {
    pageTitle: "BIN Lore",
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
        title: "Oswald",
        header: { name: "Oswald", weights: [500, 600, 700] },
        body: "Inter",
        code: "IBM Plex Mono",
      },
      colors: {
        lightMode: {
          light: "#f8fafc",
          lightgray: "#e2e8f0",
          gray: "#64748b",
          darkgray: "#1e293b",
          dark: "#090d16",
          secondary: "#dc2626",
          tertiary: "#0284c7",
          highlight: "rgba(220, 38, 38, 0.08)",
          textHighlight: "#fef08a88",
        },
        darkMode: {
          light: "#0c1017",
          lightgray: "#1e2638",
          gray: "#8b9bb4",
          darkgray: "#e2e8f0",
          dark: "#ffffff",
          secondary: "#ef4444",
          tertiary: "#38bdf8",
          highlight: "rgba(239, 68, 68, 0.15)",
          textHighlight: "#facc1544",
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
