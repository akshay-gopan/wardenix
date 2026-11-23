import { execSync } from 'node:child_process'
import path from 'node:path'

// Seed a PENDING approval via a real MCP call before the browser flow runs.
export default function globalSetup() {
  const py = path.resolve(import.meta.dirname, '../backend/.venv/bin/python')
  const script = path.resolve(import.meta.dirname, 'seed_pending.py')
  const out = execSync(`"${py}" "${script}"`, { encoding: 'utf8' })
  if (!out.includes('SEEDED_PENDING')) throw new Error(`seed failed: ${out}`)
}
