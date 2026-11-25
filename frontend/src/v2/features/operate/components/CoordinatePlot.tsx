import { useT } from '../../../i18n'
import { Stack } from '../../../ui'
import { dataPoints, fitBounds, makeProjection, VIEW_H, VIEW_W } from '../../../../shell/map/mapLogic'
import type { Fence, Point } from '../api/tools'
import { data, key } from './Runtime'
import '../runtime.css'
import '../tools.css'

export function CoordinatePlot({ label, points, fences = [], segment = false }: {
  label: string; points: { id: string; point: Point; name: string }[]; fences?: Fence[]; segment?: boolean
}) {
  const t = useT()
  const bounds = fitBounds(dataPoints([], points.map(item => item.point), fences))
  if (!bounds) return null
  const projection = makeProjection(bounds)
  const markers = points.map(item => ({ ...item, ...projection.project(item.point) }))
  return <figure><Stack gap={2}><figcaption>{t(key(label))}</figcaption>
    <div className="v2-runtime-map">
      <svg className="v2-runtime-map-shapes" viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} role="img" aria-label={t(key(label))}>
        {fences.map(fence => {
          if (fence.vertices?.length) return <polygon key={fence.id} points={fence.vertices.map(point => {
            const { x, y } = projection.project(point)
            return x + ',' + y
          }).join(' ')}><title>{data(t, fence.name)}</title></polygon>
          if (fence.center && fence.radius_m) {
            const { x, y } = projection.project(fence.center)
            return <circle key={fence.id} cx={x} cy={y} r={projection.metresToPx(fence.radius_m)}><title>{data(t, fence.name)}</title></circle>
          }
          return null
        })}
        {segment && markers.length === 2 && <line className="v2-tool-route-line"
          x1={markers[0].x} y1={markers[0].y} x2={markers[1].x} y2={markers[1].y} />}
        {markers.map(item => <circle key={item.id} className="v2-tool-map-point" cx={item.x} cy={item.y} r={9}>
          <title>{data(t, item.name)}</title>
        </circle>)}
      </svg>
    </div>
  </Stack></figure>
}
