'use client'

import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  CheckCircle,
  AlertTriangle,
  XCircle,
  Database,
  Server,
  Wifi,
  Cpu,
} from 'lucide-react'
import { cn } from '@/lib/utils'

interface HealthCheck {
  name: string
  status: 'healthy' | 'warning' | 'error'
  latency?: number
  message?: string
  icon: React.ElementType
}

// Mock data - in production fetch from API
const healthChecks: HealthCheck[] = [
  { name: 'Database', status: 'healthy', latency: 12, icon: Database },
  { name: 'Cache (Redis)', status: 'healthy', latency: 3, icon: Server },
  { name: 'API Server', status: 'healthy', latency: 45, icon: Wifi },
  { name: 'LLM Services', status: 'warning', message: 'High latency', icon: Cpu },
]

const statusConfig = {
  healthy: {
    icon: CheckCircle,
    color: 'text-success-500',
    bg: 'bg-success-50',
    label: 'Healthy',
  },
  warning: {
    icon: AlertTriangle,
    color: 'text-warning-500',
    bg: 'bg-warning-50',
    label: 'Warning',
  },
  error: {
    icon: XCircle,
    color: 'text-danger-500',
    bg: 'bg-danger-50',
    label: 'Error',
  },
}

export function SystemHealth() {
  const overallHealth = healthChecks.every(c => c.status === 'healthy')
    ? 'healthy'
    : healthChecks.some(c => c.status === 'error')
    ? 'error'
    : 'warning'

  const config = statusConfig[overallHealth]
  const StatusIcon = config.icon

  return (
    <div className="rounded-xl border bg-card p-6 shadow-sm h-full">
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-lg font-semibold">System Health</h3>
        <div className={cn('flex items-center gap-2 px-2.5 py-1 rounded-full', config.bg)}>
          <StatusIcon className={cn('h-4 w-4', config.color)} />
          <span className={cn('text-xs font-medium', config.color)}>
            {config.label}
          </span>
        </div>
      </div>

      <div className="space-y-4">
        {healthChecks.map((check, index) => {
          const checkConfig = statusConfig[check.status]
          const CheckStatusIcon = checkConfig.icon

          return (
            <motion.div
              key={check.name}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.1 }}
              className="flex items-center justify-between p-3 rounded-lg bg-muted/30"
            >
              <div className="flex items-center gap-3">
                <div className={cn('p-2 rounded-lg', checkConfig.bg)}>
                  <check.icon className={cn('h-4 w-4', checkConfig.color)} />
                </div>
                <div>
                  <p className="text-sm font-medium">{check.name}</p>
                  {check.latency && (
                    <p className="text-xs text-muted-foreground">
                      {check.latency}ms latency
                    </p>
                  )}
                  {check.message && (
                    <p className="text-xs text-warning-500">{check.message}</p>
                  )}
                </div>
              </div>
              <CheckStatusIcon className={cn('h-5 w-5', checkConfig.color)} />
            </motion.div>
          )
        })}
      </div>

      {/* Quick Stats */}
      <div className="mt-6 pt-4 border-t">
        <div className="grid grid-cols-2 gap-4">
          <div className="text-center">
            <p className="text-2xl font-bold text-brand-500">99.9%</p>
            <p className="text-xs text-muted-foreground">Uptime (30d)</p>
          </div>
          <div className="text-center">
            <p className="text-2xl font-bold text-success-500">48ms</p>
            <p className="text-xs text-muted-foreground">Avg Response</p>
          </div>
        </div>
      </div>
    </div>
  )
}
