import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, getToken } from '@/lib/api'
import { canApprove, useAuth } from '@/lib/auth'
import { PageHeader, RiskBadge } from '@/components/common'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { Approval } from '@/lib/types'

function useApprovalEvents() {
  const qc = useQueryClient()
  useEffect(() => {
    const token = getToken()
    if (!token) return
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(token)}`)
    // The DB is the source of truth: on any event, refetch the pending list.
    ws.onmessage = () => qc.invalidateQueries({ queryKey: ['approvals'] })
    return () => ws.close()
  }, [qc])
}

export default function Approvals() {
  const { user } = useAuth()
  const qc = useQueryClient()
  useApprovalEvents()

  const { data, isLoading } = useQuery({
    queryKey: ['approvals'],
    queryFn: () => api<Approval[]>('/approvals'),
    refetchInterval: 15000, // fallback poll if the WS drops
  })

  const decide = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'approve' | 'deny' }) =>
      api(`/approvals/${id}/${action}`, { method: 'POST' }),
    onSuccess: (_d, v) => {
      toast.success(`Request ${v.action === 'approve' ? 'approved' : 'denied'}`)
      qc.invalidateQueries({ queryKey: ['approvals'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const allowed = canApprove(user?.role)

  return (
    <div>
      <PageHeader title="Approvals" />
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Tool</TableHead>
              <TableHead>Risk</TableHead>
              <TableHead>Arguments</TableHead>
              <TableHead>Expires</TableHead>
              <TableHead className="text-right">Action</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={5} className="text-muted-foreground">
                  Loading…
                </TableCell>
              </TableRow>
            )}
            {data?.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="text-muted-foreground">
                  No pending approvals.
                </TableCell>
              </TableRow>
            )}
            {data?.map((a) => (
              <TableRow key={a.id}>
                <TableCell className="font-mono text-sm">{a.tool}</TableCell>
                <TableCell>
                  <RiskBadge band={a.risk_band} />
                </TableCell>
                <TableCell className="max-w-xs truncate font-mono text-xs text-muted-foreground">
                  {JSON.stringify(a.args_redacted)}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {a.expires_at ? new Date(a.expires_at).toLocaleTimeString() : '—'}
                </TableCell>
                <TableCell className="text-right">
                  {allowed ? (
                    <div className="flex justify-end gap-2">
                      <Button
                        size="sm"
                        onClick={() => decide.mutate({ id: a.id, action: 'approve' })}
                      >
                        Approve
                      </Button>
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => decide.mutate({ id: a.id, action: 'deny' })}
                      >
                        Deny
                      </Button>
                    </div>
                  ) : (
                    <span className="text-xs text-muted-foreground">view only</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
