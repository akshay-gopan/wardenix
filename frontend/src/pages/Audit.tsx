import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { PageHeader, RiskBadge, TagBadge } from '@/components/common'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { AuditEvent } from '@/lib/types'

export default function Audit() {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['audit', 'list'],
    queryFn: () => api<AuditEvent[]>('/audit?limit=200'),
  })
  const verify = useQuery({
    queryKey: ['audit', 'verify'],
    queryFn: () => api<{ ok: boolean; count: number; first_bad_seq?: number }>('/audit/verify'),
  })

  async function reverify() {
    await qc.invalidateQueries({ queryKey: ['audit'] })
    toast.success('Re-verified audit chain')
  }

  return (
    <div>
      <PageHeader title="Audit Log">
        {verify.data && (
          <span
            className={
              'rounded-md px-3 py-1.5 text-sm ' +
              (verify.data.ok
                ? 'bg-emerald-100 text-emerald-800'
                : 'bg-red-100 text-red-800')
            }
          >
            {verify.data.ok
              ? `✓ chain verified (${verify.data.count})`
              : `✗ broken at seq ${verify.data.first_bad_seq}`}
          </span>
        )}
        <Button variant="outline" size="sm" onClick={reverify}>
          Re-verify
        </Button>
      </PageHeader>
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Seq</TableHead>
              <TableHead>Time</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Tool</TableHead>
              <TableHead>Decision</TableHead>
              <TableHead>Risk</TableHead>
              <TableHead>Outcome</TableHead>
              <TableHead className="text-right">Latency</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.map((e) => (
              <TableRow key={e.seq}>
                <TableCell className="tabular-nums text-muted-foreground">{e.seq}</TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {e.ts ? new Date(e.ts).toLocaleString() : '—'}
                </TableCell>
                <TableCell className="text-xs">{e.event_type}</TableCell>
                <TableCell className="font-mono text-sm">{e.tool ?? '—'}</TableCell>
                <TableCell>
                  <TagBadge value={e.decision} />
                </TableCell>
                <TableCell>
                  <RiskBadge band={e.risk_band} />
                </TableCell>
                <TableCell>
                  <TagBadge value={e.outcome} />
                </TableCell>
                <TableCell className="text-right tabular-nums text-muted-foreground">
                  {e.latency_ms != null ? `${e.latency_ms} ms` : '—'}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
