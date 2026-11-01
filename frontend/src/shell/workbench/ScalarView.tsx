import { ApiReferenceReact } from '@scalar/api-reference-react'

/** Own chunk (lazy-imported by ApiReference): Scalar and its CSS load only when the API tab is first shown.
 *  Read-only reference: Scalar's own "Test request" and client picker are off, so the only way to send a
 *  request is our console (fixed origin, no storage). Telemetry, proxy, fonts CDN, MCP and auth persistence are off. */
export default function ScalarView({ document: doc, origin }: { document: Record<string, unknown>; origin: string }) {
  return (
    <ApiReferenceReact
      configuration={{
        content: doc,
        servers: [{ url: origin }],
        hideClientButton: true,
        hideTestRequestButton: true,
        hideDownloadButton: true,
        documentDownloadType: 'none',
        showDeveloperTools: 'never',
        persistAuth: false,
        telemetry: false,
        withDefaultFonts: false,
        mcp: { disabled: true },
        layout: 'classic',
        hideDarkModeToggle: true,
        // follow the dashboard theme; Scalar must not pick its own (it toggles dark-mode classes on the page)
        forceDarkModeState: document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light',
        showSidebar: true,
        defaultOpenAllTags: true,
      }}
    />
  )
}
