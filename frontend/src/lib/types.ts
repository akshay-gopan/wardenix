// Shared API types (mirror the backend Control Plane responses).

export type Role = 'admin' | 'approver' | 'viewer'

export interface User {
  id: string
  email: string
  role: Role
  is_active: boolean
  created_at: string | null
}

export interface Approval {
  id: string
  correlation_id: string
  agent_id: string
  server_id: string
  tool: string
  args_redacted: Record<string, unknown>
  risk_score: number
  risk_band: 'low' | 'medium' | 'high' | 'critical'
  status: 'pending' | 'approved' | 'consumed' | 'denied' | 'expired'
  created_at: string | null
  expires_at: string | null
  decided_at: string | null
}

export interface Rule {
  id: string
  policy_id: string
  priority: number
  enabled: boolean
  conditions: Record<string, unknown>
  action: 'allow' | 'deny' | 'require_approval'
  message: string | null
}

export interface Policy {
  id: string
  name: string
  enabled: boolean
  default_action: string
  version: number
  rules?: Rule[]
}

export interface Server {
  id: string
  name: string
  transport: 'stdio' | 'http'
  enabled: boolean
  command: string | null
  args: string[] | null
  url: string | null
  tags: string[]
  health: string
}

export interface Agent {
  id: string
  name: string
  enabled: boolean
  meta: Record<string, unknown>
  created_at: string | null
}

export interface AuditEvent {
  seq: number
  correlation_id: string
  ts: string | null
  event_type: 'decision' | 'outcome'
  tool: string | null
  decision: string | null
  risk_score: number | null
  risk_band: string | null
  risk_signals: Record<string, unknown>
  outcome: string | null
  latency_ms: number | null
}
