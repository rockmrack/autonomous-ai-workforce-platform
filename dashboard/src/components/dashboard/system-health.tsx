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
  RefreshCw,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api'

interface HealthCheck {
  name: string
  status: 'healthy' | 'warning' | 'error'
  latency?: number
  message?: string
  icon: React.ElementType
}

interface HealthResponse {
  healthy: boolean
  components: {
    database: { healthy: boolean; latency_ms?: number }
    cache: { healthy: boolean; used_memory?: string }
    scheduler: { running: boolean }
  }
}

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
  const { data, isLoading, error, refetch } = useQuery<HealthResponse>({
    queryKey: ['system-health'],
    queryFn: () => apiClient.get('/health').then(res => res.data),
    refetchInterval: 30000, // Refresh every 30 seconds
  })

  // Build health checks from API response
  const healthChecks: HealthCheck[] = data ? [
    {
      name: 'Database',
      status: data.components.database.healthy ? 'healthy' : 'error',
      latency: data.components.database.latency_ms,
      icon: Database,
    },
    {
      name: 'Cache (Redis)',
      status: data.components.cache.healthy ? 'healthy' : 'error',
      message: data.components.cache.used_memory,
      icon: Server,
    },
    {
      name: 'Scheduler',
      status: data.components.scheduler.running ? 'healthy' : 'warning',
      message: data.components.scheduler.running ? undefined : 'Not running',
      icon: Cpu,
    },
  ] : []

  const overallHealth = isLoading
    ? 'warning'
    : error
    ? 'error'
    : healthChecks.every(c => c.status === 'healthy')
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
        <div className="flex items-center gap-2">
          <button
            onClick={() => refetch()}
            className="p-1 hover:bg-muted rounded"
            title="Refresh"
          >
            <RefreshCw className={cn('h-4 w-4 text-muted-foreground', isLoading && 'animate-spin')} />
          </button>
          <div className={cn('flex items-center gap-2 px-2.5 py-1 rounded-full', config.bg)}>
            <StatusIcon className={cn('h-4 w-4', config.color)} />
            <span className={cn('text-xs font-medium', config.color)}>
              {isLoading ? 'Checking...' : config.label}
            </span>
          </div>
        </div>
      </div>

      <div className="space-y-4">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : error ? (
          <div className="text-center py-8 text-danger-500">
            Failed to fetch health status
          </div>
        ) : (
          healthChecks.map((check, index) => {
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
          })
        )}
      </div>

      {/* Quick Stats */}
      <div className="mt-6 pt-4 border-t">
        <div className="grid grid-cols-2 gap-4">
          <div className="text-center">
            <p className="text-2xl font-bold text-brand-500">
              {data?.healthy ? '100%' : '--'}
            </p>
            <p className="text-xs text-muted-foreground">Current Status</p>
          </div>
          <div className="text-center">
            <p className="text-2xl font-bold text-success-500">
              {healthChecks.filter(c => c.status === 'healthy').length}/{healthChecks.length}
            </p>
            <p className="text-xs text-muted-foreground">Components OK</p>
          </div>
        </div>
      </div>
    </div>
  )
}
