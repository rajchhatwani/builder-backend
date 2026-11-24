export const editorSectionRoute = '/projects/$projectId/$section' as const

export type EditorFileTarget = {
  projectId: string
  path?: string
  workspace?: string
  run?: string
  source?: 'manifest' | 'kit'
}

/** Router link options shared by callers without loading the editor feature. */
export function openInEditor(file: EditorFileTarget) {
  return {
    to: editorSectionRoute,
    params: { projectId: file.projectId, section: 'code' },
    search: { file: file.path, workspace: file.workspace, run: file.run, source: file.source },
  }
}
