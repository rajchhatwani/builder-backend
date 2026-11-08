import { BASE_URL } from '../../api/session'
import { resolvePreviewOrigin } from './workbenchLogic'

/** The only origin the Workbench may call (build-time config). Unset until the preview runtime provides one. */
export const PREVIEW_ORIGIN = resolvePreviewOrigin(import.meta.env.VITE_PREVIEW_API_ORIGIN as string | undefined, [BASE_URL])
