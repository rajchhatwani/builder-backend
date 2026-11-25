import type { ComponentProps } from 'react'
import { RouteTranslations } from '../../../i18n'
import { RuntimeContents, runtimeEnglish } from './Runtime'
import english from '../toolsCopy.json'

export function ToolTranslations({ children }: { children: React.ReactNode }) {
  return <RouteTranslations english={{
    operate: { ...runtimeEnglish.operate, roleError: english.operate.roleError },
    runtime: { ...runtimeEnglish.runtime, ...english.runtime },
  }}>{children}</RouteTranslations>
}

export function ToolScreen(props: ComponentProps<typeof RuntimeContents>) {
  return <ToolTranslations><RuntimeContents {...props} /></ToolTranslations>
}
