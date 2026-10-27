/** "March 3, 2027" for a deletion date; "soon" when the server sent none. */
export function formatDeletionDate(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleDateString(undefined, { dateStyle: 'long' }) : 'soon'
}
