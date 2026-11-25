import type { Booking, Slot } from '../../../../shell/bookings/calendarLogic'
import type { ResourceRow } from '../../../../shell/bookings/bookingAdminLogic'
import { segment } from './live'
export type Resource = ResourceRow & { created_at: string }
export type BookingDetail = Booking & { idempotency_key: string | null; customer_id: string | null; expired_at: string | null; created_at: string }
export type Availability = { resource_id: string; timezone: string; slot_minutes: number; slots: Slot[] }
export type Capacity = { capacity: number; free: number; booked: number }
export type BookingInput = {
  resource_id: string; starts_at: string; ends_at: string; quantity?: number; confirm: boolean;
  idempotency_key: string; customer_ref?: string; notes?: string
}
export const resourcesPath = '/booking/resources'
export const bookingsPath = '/booking/bookings'
export const resourcePath = (id: string) => `${resourcesPath}/${segment(id)}` as const
export const bookingPath = (id: string) => `${bookingsPath}/${segment(id)}` as const
