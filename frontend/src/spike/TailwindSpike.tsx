import './spike.css'

/** Hidden route #/__spike: Tailwind utilities next to the existing Oat markup/styles. */
export default function TailwindSpike() {
  return (
    <div className="mx-auto max-w-xl p-6" data-testid="tailwind-spike">
      <h1 className="text-2xl font-semibold">Tailwind coexistence spike</h1>
      <p className="mt-2 text-sm opacity-70">Utility classes (this paragraph) next to Oat components (below).</p>
      <div className="mt-4 flex items-center gap-3">
        <button>Oat button</button>
        <span className="rounded-full bg-emerald-600 px-3 py-1 text-xs text-white" data-testid="tw-pill">
          tailwind pill
        </span>
      </div>
      <table className="mt-4">
        <thead>
          <tr>
            <th>Oat table</th>
            <th>head</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>cell</td>
            <td>cell</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}
