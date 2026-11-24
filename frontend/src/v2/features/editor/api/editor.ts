import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, saveBlob } from '../../../../api/client'
import { aiApi } from '../../../../shell/ai/aiApi'
import { workspaceApi } from '../../../../shell/ai/workspaceApi'
import { readKit } from './archive'

export const editorKeys = {
  project: (id: string) => ['editor', id] as const,
  workspace: (id: string, workspace: string) => [...editorKeys.project(id), 'workspace', workspace] as const,
  content: (id: string, workspace: string, path: string) => [...editorKeys.workspace(id, workspace), 'content', path] as const,
}

const options = { retry: false, retryOnMount: false, staleTime: 15_000 }
const projectId = encodeURIComponent

export const workspacesOptions = (id: string) => queryOptions({
  ...options, queryKey: [...editorKeys.project(id), 'workspaces'], queryFn: () => api.listWorkspaces(projectId(id)),
})
export const manifestOptions = (id: string) => queryOptions({
  ...options, queryKey: [...editorKeys.project(id), 'manifest'], queryFn: () => api.previewGeneration(projectId(id)),
})
export const kitOptions = (id: string) => queryOptions({
  ...options, queryKey: [...editorKeys.project(id), 'kit'],
  queryFn: async () => readKit((await api.downloadSelfHostKit(projectId(id), 'self-host.zip')).blob),
})
export const filesOptions = (id: string, workspace: string) => queryOptions({
  ...options, queryKey: [...editorKeys.workspace(id, workspace), 'files'],
  queryFn: () => workspaceApi.list(projectId(id), encodeURIComponent(workspace)),
})
export const contentOptions = (id: string, workspace: string, path: string) => queryOptions({
  ...options, queryKey: editorKeys.content(id, workspace, path),
  queryFn: () => workspaceApi.read(projectId(id), encodeURIComponent(workspace), path),
})
export const accountOptions = queryOptions({ ...options, queryKey: ['editor', 'account'], queryFn: api.me })
export const membersOptions = (id: string) => queryOptions({
  ...options, queryKey: [...editorKeys.project(id), 'members'], queryFn: () => api.listMembers(projectId(id)),
})
export const runOptions = (id: string, run: string) => queryOptions({
  ...options, queryKey: [...editorKeys.project(id), 'run', run],
  queryFn: () => aiApi.getRun(projectId(id), encodeURIComponent(run)),
  enabled: Boolean(run),
})

export const runChecksOptions = (id: string, run: string) => queryOptions({
  ...options, queryKey: [...editorKeys.project(id), 'checks', run],
  queryFn: () => aiApi.listApprovals(projectId(id), { run_id: run, limit: 200 }),
  enabled: Boolean(run),
})

export function useFileSave(id: string, workspace: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ path, content, sha }: { path: string; content: string; sha: string }) =>
      workspaceApi.write(projectId(id), encodeURIComponent(workspace), path, content, sha),
    onSuccess: async saved => {
      const key = editorKeys.content(id, workspace, saved.path)
      await client.cancelQueries({ queryKey: key, exact: true })
      client.setQueryData(key, saved)
      void client.invalidateQueries({ queryKey: filesOptions(id, workspace).queryKey })
    },
  })
}

export function useZipDownload(id: string) {
  return useMutation({ mutationFn: async () => {
    const { blob, filename } = await api.downloadZip(projectId(id), 'backend.zip')
    saveBlob(blob, filename)
  } })
}
