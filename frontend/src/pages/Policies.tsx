import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { isAdmin, useAuth } from '@/lib/auth'
import { PageHeader, TagBadge } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { Policy } from '@/lib/types'

function NewPolicyDialog() {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [defaultAction, setDefaultAction] = useState('deny')
  const m = useMutation({
    mutationFn: () => api('/policies', { method: 'POST', body: { name, default_action: defaultAction } }),
    onSuccess: () => {
      toast.success('Policy created')
      qc.invalidateQueries({ queryKey: ['policies'] })
      setOpen(false)
      setName('')
    },
    onError: (e: Error) => toast.error(e.message),
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">New policy</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New policy</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label>Default action</Label>
            <Select value={defaultAction} onValueChange={setDefaultAction}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="deny">deny</SelectItem>
                <SelectItem value="require_approval">require_approval</SelectItem>
                <SelectItem value="allow">allow</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button onClick={() => m.mutate()} disabled={!name}>
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function NewRuleDialog({ policies }: { policies: Policy[] }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [policyId, setPolicyId] = useState('')
  const [action, setAction] = useState('require_approval')
  const [priority, setPriority] = useState('100')
  const [conditions, setConditions] = useState('{\n  "tools": ["*"]\n}')
  const [message, setMessage] = useState('')

  const m = useMutation({
    mutationFn: () => {
      let parsed: unknown
      try {
        parsed = JSON.parse(conditions)
      } catch {
        throw new Error('conditions must be valid JSON')
      }
      return api('/policies/rules', {
        method: 'POST',
        body: {
          policy_id: policyId,
          action,
          priority: Number(priority),
          conditions: parsed,
          message: message || null,
        },
      })
    },
    onSuccess: () => {
      toast.success('Rule added')
      qc.invalidateQueries({ queryKey: ['policies'] })
      setOpen(false)
    },
    onError: (e: Error) => toast.error(e.message),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline" disabled={policies.length === 0}>
          Add rule
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add rule</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>Policy</Label>
            <Select value={policyId} onValueChange={setPolicyId}>
              <SelectTrigger>
                <SelectValue placeholder="Select a policy" />
              </SelectTrigger>
              <SelectContent>
                {policies.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label>Action</Label>
              <Select value={action} onValueChange={setAction}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="deny">deny</SelectItem>
                  <SelectItem value="require_approval">require_approval</SelectItem>
                  <SelectItem value="allow">allow</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Priority</Label>
              <Input value={priority} onChange={(e) => setPriority(e.target.value)} />
            </div>
          </div>
          <div className="space-y-2">
            <Label>Conditions (JSON)</Label>
            <Textarea
              rows={6}
              className="font-mono text-xs"
              value={conditions}
              onChange={(e) => setConditions(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Keys: agents, servers, tools (globs), min_risk_band, args
              [&#123;key, op, value&#125;]. Empty = match all.
            </p>
          </div>
          <div className="space-y-2">
            <Label>Message (optional)</Label>
            <Input value={message} onChange={(e) => setMessage(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button onClick={() => m.mutate()} disabled={!policyId}>
            Add rule
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default function Policies() {
  const { user } = useAuth()
  const admin = isAdmin(user?.role)
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['policies'], queryFn: () => api<Policy[]>('/policies') })

  const delPolicy = useMutation({
    mutationFn: (id: string) => api(`/policies/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['policies'] }),
    onError: (e: Error) => toast.error(e.message),
  })
  const delRule = useMutation({
    mutationFn: (id: string) => api(`/policies/rules/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['policies'] }),
    onError: (e: Error) => toast.error(e.message),
  })

  async function exportYaml() {
    const yaml = await api<string>('/policies/export')
    const blob = new Blob([yaml], { type: 'application/x-yaml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'wardenix-policies.yaml'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div>
      <PageHeader title="Policies">
        <Button variant="outline" size="sm" onClick={exportYaml}>
          Export YAML
        </Button>
        {admin && <NewRuleDialog policies={data ?? []} />}
        {admin && <NewPolicyDialog />}
      </PageHeader>

      <div className="space-y-4">
        {data?.map((p) => (
          <Card key={p.id}>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-base">
                {p.name}{' '}
                <span className="text-xs font-normal text-muted-foreground">
                  default: {p.default_action} {p.enabled ? '' : '(disabled)'}
                </span>
              </CardTitle>
              {admin && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive"
                  onClick={() => delPolicy.mutate(p.id)}
                >
                  Delete
                </Button>
              )}
            </CardHeader>
            <CardContent>
              {p.rules && p.rules.length > 0 ? (
                <div className="space-y-2">
                  {p.rules.map((r) => (
                    <div
                      key={r.id}
                      className="flex items-center gap-3 rounded-md border px-3 py-2 text-sm"
                    >
                      <span className="w-10 tabular-nums text-muted-foreground">{r.priority}</span>
                      <TagBadge value={r.action} />
                      <code className="flex-1 truncate text-xs text-muted-foreground">
                        {JSON.stringify(r.conditions)}
                      </code>
                      {admin && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive"
                          onClick={() => delRule.mutate(r.id)}
                        >
                          ✕
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">No rules.</p>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
