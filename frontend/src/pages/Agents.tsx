import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { PageHeader } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { Agent } from '@/lib/types'

export default function Agents() {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['agents'], queryFn: () => api<Agent[]>('/agents') })
  const [name, setName] = useState('')
  const [newKey, setNewKey] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: () => api<Agent & { api_key: string }>('/agents', { method: 'POST', body: { name } }),
    onSuccess: (a) => {
      setNewKey(a.api_key)
      setName('')
      qc.invalidateQueries({ queryKey: ['agents'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })
  const rotate = useMutation({
    mutationFn: (id: string) => api<Agent & { api_key: string }>(`/agents/${id}/rotate`, { method: 'POST' }),
    onSuccess: (a) => setNewKey(a.api_key),
  })
  const del = useMutation({
    mutationFn: (id: string) => api(`/agents/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agents'] }),
  })

  return (
    <div>
      <PageHeader title="Agents">
        <div className="flex gap-2">
          <Input
            placeholder="agent name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-48"
          />
          <Button size="sm" onClick={() => create.mutate()} disabled={!name}>
            Create agent
          </Button>
        </div>
      </PageHeader>

      <Dialog open={newKey !== null} onOpenChange={(o) => !o && setNewKey(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>API key — copy it now</DialogTitle>
            <DialogDescription>
              This key is shown only once. Wardenix stores only its hash.
            </DialogDescription>
          </DialogHeader>
          <code className="block overflow-x-auto rounded-md bg-muted p-3 text-sm">{newKey}</code>
          <DialogFooter>
            <Button
              onClick={() => {
                navigator.clipboard.writeText(newKey ?? '')
                toast.success('Copied')
              }}
            >
              Copy
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.map((a) => (
              <TableRow key={a.id}>
                <TableCell className="font-medium">{a.name}</TableCell>
                <TableCell>
                  <Badge variant={a.enabled ? 'default' : 'outline'}>
                    {a.enabled ? 'enabled' : 'disabled'}
                  </Badge>
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-2">
                    <Button size="sm" variant="outline" onClick={() => rotate.mutate(a.id)}>
                      Rotate key
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-destructive"
                      onClick={() => del.mutate(a.id)}
                    >
                      Delete
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
