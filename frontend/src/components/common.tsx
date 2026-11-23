import type { ReactNode } from 'react'
import { Badge } from '@/components/ui/badge'

export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-6 flex items-center justify-between">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <div className="flex gap-2">{children}</div>
    </div>
  )
}

const RISK_COLORS: Record<string, string> = {
  low: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300',
  medium: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
  high: 'bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300',
  critical: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300',
}

export function RiskBadge({ band }: { band: string | null }) {
  if (!band) return <span className="text-muted-foreground">—</span>
  return <Badge className={RISK_COLORS[band] ?? ''}>{band}</Badge>
}

const DECISION_COLORS: Record<string, string> = {
  allow: 'bg-emerald-100 text-emerald-800',
  deny: 'bg-red-100 text-red-800',
  require_approval: 'bg-amber-100 text-amber-800',
  success: 'bg-emerald-100 text-emerald-800',
  error: 'bg-red-100 text-red-800',
  denied: 'bg-red-100 text-red-800',
  unknown: 'bg-purple-100 text-purple-800',
}

export function TagBadge({ value }: { value: string | null }) {
  if (!value) return <span className="text-muted-foreground">—</span>
  return <Badge variant="outline" className={DECISION_COLORS[value] ?? ''}>{value}</Badge>
}
