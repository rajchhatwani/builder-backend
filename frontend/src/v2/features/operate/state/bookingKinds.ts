import { kindFormOf, newKindForm } from '../../../../shell/bookings/bookingAdminLogic'
import type { KindForm, Obj } from '../../../../shell/bookings/bookingAdminLogic'
import type { Mode } from '../../../../shell/bookings/calendarLogic'

type Kind = { id: number; initial: KindForm; original?: Obj }
export type KindState = { items: Kind[]; next: number }
type Action = { type: 'add'; mode: Mode } | { type: 'remove'; id: number }

export function initialKinds(kinds: Obj[]): KindState {
  return { items: kinds.map((original, id) => ({ id, initial: kindFormOf(original), original })), next: kinds.length }
}
export function bookingKinds(state: KindState, action: Action): KindState {
  if (action.type === 'remove') return { ...state, items: state.items.filter(item => item.id !== action.id) }
  if (state.items.length >= 20) return state
  return { items: [...state.items, { id: state.next, initial: newKindForm(action.mode) }], next: state.next + 1 }
}
