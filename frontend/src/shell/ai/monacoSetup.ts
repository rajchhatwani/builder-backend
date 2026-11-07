/* Loaded only with the lazy editor chunk. Bundles Monaco locally (no CDN) and wires the workers through Vite. */
import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor/editor/editor.api'
import 'monaco-editor/language/json/monaco.contribution'
import 'monaco-editor/languages/definitions/python/register'
import 'monaco-editor/languages/definitions/yaml/register'
import 'monaco-editor/languages/definitions/markdown/register'
import EditorWorker from 'monaco-editor/editor/editor.worker?worker'
import JsonWorker from 'monaco-editor/language/json/json.worker?worker'

;(self as unknown as { MonacoEnvironment: unknown }).MonacoEnvironment = {
  getWorker(_id: string, label: string) {
    return label === 'json' ? new JsonWorker() : new EditorWorker()
  },
}
loader.config({ monaco })
export { monaco }
