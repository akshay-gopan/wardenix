import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { isAdmin, useAuth } from '@/lib/auth'
import { PageHeader } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { Server } from '@/lib/types'

function NewServerDialog() {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [transport, setTransport] = useState('stdio')
  const [command, setCommand] = useState('')
  const [args, setArgs] = useState('')
  const [url, setUrl] = useState('')

  const m = useMutation({
    mutationFn: () =>
      api('/servers', {
        method: 'POST',
        body: {
          name,
          transport,
          command: transport === 'stdio' ? command : null,
          args: transport === 'stdio' && args ? args.split(/\s+/) : null,
          url: transport === 'http' ? url : null,
        },
      }),
    onSuccess: () => {
      toast.success('Server registered')
      qc.invalidateQueries({ queryKey: ['servers'] })
      setOpen(false)
    },
    onError: (e: Error) => toast.error(e.message),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">Register server</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Register upstream MCP server</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label>Transport</Label>
            <Select value={transport} onValueChange={setTransport}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="stdio">stdio</SelectItem>
                <SelectItem value="http">http</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {transport === 'stdio' ? (
            <>
              <div className="space-y-2">
                <Label>Command</Label>
                <Input
                  value={command}
                  onChange={(e) => setCommand(e.target.value)}
                  placeholder="python"
                />
              </div>
              <div className="space-y-2">
                <Label>Args (space-separated)</Label>
                <Input value={args} onChange={(e) => setArgs(e.target.value)} />
              </div>
            </>
          ) : (
            <div className="space-y-2">
              <Label>URL</Label>
              <Input
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="http://host:port/mcp"
              />
            </div>
          )}
        </div>
        <DialogFooter>
          <Button onClick={() => m.mutate()} disabled={!name}>
            Register
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default function Servers() {
  const { user } = useAuth()
  const admin = isAdmin(user?.role)
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['servers'], queryFn: () => api<Server[]>('/servers') })

  const test = useMutation({
    mutationFn: (id: string) => api<{ ok: boolean; tools?: string[]; error?: string }>(
      `/servers/${id}/test`,
      { method: 'POST' },
    ),
    onSuccess: (r) =>
      r.ok ? toast.success(`Healthy — ${r.tools?.length ?? 0} tools`) : toast.error(r.error ?? 'unreachable'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['servers'] }),
  })
  const del = useMutation({
    mutationFn: (id: string) => api(`/servers/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['servers'] }),
  })

  return (
    <div>
      <PageHeader title="Servers">{admin && <NewServerDialog />}</PageHeader>
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Transport</TableHead>
              <TableHead>Target</TableHead>
              <TableHead>Health</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.map((s) => (
              <TableRow key={s.id}>
                <TableCell className="font-medium">{s.name}</TableCell>
                <TableCell>{s.transport}</TableCell>
                <TableCell className="max-w-xs truncate font-mono text-xs text-muted-foreground">
                  {s.transport === 'stdio' ? `${s.command ?? ''} ${(s.args ?? []).join(' ')}` : s.url}
                </TableCell>
                <TableCell>
                  <Badge variant={s.health === 'healthy' ? 'default' : 'outline'}>{s.health}</Badge>
                </TableCell>
                <TableCell className="text-right">
                  {admin && (
                    <div className="flex justify-end gap-2">
                      <Button size="sm" variant="outline" onClick={() => test.mutate(s.id)}>
                        Test
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-destructive"
                        onClick={() => del.mutate(s.id)}
                      >
                        Delete
                      </Button>
                    </div>
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
