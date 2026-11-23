import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PageHeader } from '@/components/common'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { Approval, AuditEvent, Server } from '@/lib/types'

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-semibold">{value}</div>
        {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
      </CardContent>
    </Card>
  )
}

export default function Overview() {
  const approvals = useQuery({
    queryKey: ['approvals'],
    queryFn: () => api<Approval[]>('/approvals'),
  })
  const servers = useQuery({ queryKey: ['servers'], queryFn: () => api<Server[]>('/servers') })
  const events = useQuery({
    queryKey: ['audit', 'overview'],
    queryFn: () => api<AuditEvent[]>('/audit?limit=500'),
  })
  const chain = useQuery({
    queryKey: ['audit', 'verify'],
    queryFn: () => api<{ ok: boolean; count: number }>('/audit/verify'),
  })

  const decisions = events.data?.filter((e) => e.event_type === 'decision') ?? []
  const denied = decisions.filter((e) => e.decision === 'deny').length
  const approvalsReq = decisions.filter((e) => e.decision === 'require_approval').length
  const riskCounts = decisions.reduce<Record<string, number>>((acc, e) => {
    if (e.risk_band) acc[e.risk_band] = (acc[e.risk_band] ?? 0) + 1
    return acc
  }, {})

  return (
    <div>
      <PageHeader title="Overview" />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Pending approvals" value={approvals.data?.length ?? '—'} />
        <Stat
          label="Upstream servers"
          value={servers.data?.length ?? '—'}
          hint={`${servers.data?.filter((s) => s.health === 'healthy').length ?? 0} healthy`}
        />
        <Stat label="Decisions (recent)" value={decisions.length} hint={`${denied} denied`} />
        <Stat label="Approval-gated" value={approvalsReq} />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Risk distribution (recent decisions)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {['low', 'medium', 'high', 'critical'].map((band) => {
              const n = riskCounts[band] ?? 0
              const total = decisions.length || 1
              return (
                <div key={band} className="flex items-center gap-3">
                  <span className="w-16 text-sm capitalize text-muted-foreground">{band}</span>
                  <div className="h-3 flex-1 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full bg-primary"
                      style={{ width: `${(n / total) * 100}%` }}
                    />
                  </div>
                  <span className="w-8 text-right text-sm tabular-nums">{n}</span>
                </div>
              )
            })}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Audit chain integrity</CardTitle>
          </CardHeader>
          <CardContent>
            {chain.data ? (
              <div className="space-y-1">
                <div className={chain.data.ok ? 'text-emerald-600' : 'text-destructive'}>
                  {chain.data.ok ? '✓ Chain verified — no tampering detected' : '✗ Chain broken'}
                </div>
                <div className="text-sm text-muted-foreground">{chain.data.count} events</div>
              </div>
            ) : (
              <div className="text-muted-foreground">Checking…</div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
