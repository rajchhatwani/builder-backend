import type { JsonSchema } from '../../forms'
import geo from '../../forms/schemas/geo.json'
import location from '../../forms/schemas/location.json'
import matching from '../../forms/schemas/matching.json'
import prediction from '../../forms/schemas/prediction.json'
import { PackFormPage } from '../packs/PackFormPage'

type P = { projectId: string }

export const GeoSettingsPage = ({ projectId }: P) => (
  <PackFormPage projectId={projectId} pack="operations" block="geo" title="Geo settings" schema={geo as JsonSchema}
    intro="Places and geofences: who may read and write, the size limits and the index cell size. Distances and coordinates use integer metres and micro-degrees; the provider is always the built-in fake one." />
)
export const LocationSettingsPage = ({ projectId }: P) => (
  <PackFormPage projectId={projectId} pack="operations" block="location" title="Location settings" schema={location as JsonSchema}
    intro="Live positions: who may read and report, how many history rows are kept per subject and how many subjects are tracked." />
)
export const MatchingSettingsPage = ({ projectId }: P) => (
  <PackFormPage projectId={projectId} pack="operations" block="matching" title="Matching settings" schema={matching as JsonSchema}
    intro="Who may read and assign, the score weights (integers), the distance and load limits and how long an offer stays open." />
)
export const PredictionSettingsPage = ({ projectId }: P) => (
  <PackFormPage projectId={projectId} pack="operations" block="prediction" title="Prediction settings" schema={prediction as JsonSchema}
    intro="Who may read and record, the model id and unit shown on records and the prediction interval width in basis points." />
)
