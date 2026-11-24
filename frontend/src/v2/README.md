# Backbone customer UI v2

The application mounts from `frontend/src/main.tsx`. Use `/v2-kit` to exercise the component library, including keyboard interactions and the light and dark themes. Project readiness is at `/projects/<project-id>/overview`. The backend remains the source of project data.

## Layers

| Layer | Owns |
| --- | --- |
| `tokens` | Theme variables, typography, spacing, radii, motion and stacking |
| `ui` | Generic controls, overlays, accessibility, layout and feedback |
| `patterns` | Reusable forms, tables, sections, save and conflict handling |
| `features/<name>` | Screen logic, typed API adapters, query keys and local reducers |
| `app` | Router, lazy boundaries, providers and workspace shell |

Imports point down. Only feature code imports the existing `src/api` client, and features share generic code through lower layers. The `i18n` catalog and validators are shared across layers. Use `Stack`, `Row` and `Grid` for parent-owned spacing. Primitives accept translated labels. Give each `Pagination` the label of the content it controls so screen reader users can distinguish the navigation landmarks. Feature copy belongs in `i18n/locales/en.json` and goes through `useT()`.

## Add a screen

1. Define a component in its feature and register a split point with `lazyScreen` in `app/routeScreens.ts`. Add a route to `app/router.tsx` and update the shared project navigation metadata when it needs a rail item. Intent preloading should load the screen module and prefetch applicable queries.
2. Keep a query-key factory and typed hooks in `features/<name>/api`. See `features/projects/api/status.ts` for a query shared across the shell and screen, with mutation invalidation. Validate tab, filter, page and selected item in the route's search schema.
3. Use field-specific schema constraints with `validators.ts` and map server errors to the matching `Form` field. Use `ConfirmDestructive` and `ConflictBanner` where the backend semantics call for them. Include loading, empty, retry and permission states. Render `DesktopOnlyCard` on phones for desktop-only authoring screens.
4. Add a Vitest screen test, contract coverage and mocked Playwright screenshots in light and dark at 360, 768 and 1280. Add English catalog keys for new copy. Test with the supervisor's `playwright.v2.config.ts`.

The shell uses browser-history routes. Deployment of a static build needs the usual SPA fallback to `index.html` for direct navigation. The RTL tests use the supervisor's shared test environment with `@testing-library/react` and `@testing-library/dom` available.
