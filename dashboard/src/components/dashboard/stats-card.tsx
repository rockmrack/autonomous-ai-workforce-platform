'use client'

import { LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

interface StatsCardProps {
  title: string
  value: string | number
  total?: number
  icon: LucideIcon
  color: 'brand' | 'success' | 'warning' | 'danger'
  trend?: string
  subtitle?: string
  isLoading?: boolean
}

const colorClasses = {
  brand: 'from-brand-500 to-brand-700',
  success: 'from-success-500 to-success-700',
  warning: 'from-warning-500 to-warning-700',
  danger: 'from-danger-500 to-danger-700',
}

const bgColorClasses = {
  brand: 'bg-brand-50',
  success: 'bg-success-50',
  warning: 'bg-warning-50',
  danger: 'bg-danger-50',
}

const textColorClasses = {
  brand: 'text-brand-600',
  success: 'text-success-600',
  warning: 'text-warning-600',
  danger: 'text-danger-600',
}

export function StatsCard({
  title,
  value,
  total,
  icon: Icon,
  color,
  trend,
  subtitle,
  isLoading,
}: StatsCardProps) {
  return (
    <div className="rounded-xl border bg-card p-6 shadow-sm card-hover">
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <p className="text-sm font-medium text-muted-foreground">{title}</p>
          {isLoading ? (
            <div className="h-8 w-24 animate-pulse rounded bg-muted" />
          ) : (
            <div className="flex items-baseline gap-2">
              <h3 className="text-2xl font-bold">{value}</h3>
              {total && (
                <span className="text-sm text-muted-foreground">
                  / {total}
                </span>
              )}
            </div>
          )}
        </div>
        <div
          className={cn(
            'flex h-10 w-10 items-center justify-center rounded-lg',
            bgColorClasses[color]
          )}
        >
          <Icon className={cn('h-5 w-5', textColorClasses[color])} />
        </div>
      </div>

      {(trend || subtitle) && (
        <div className="mt-4 flex items-center gap-2">
          {trend && (
            <span
              className={cn(
                'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
                trend.startsWith('+')
                  ? 'bg-success-50 text-success-700'
                  : 'bg-danger-50 text-danger-700'
              )}
            >
              {trend}
            </span>
          )}
          {subtitle && (
            <span className="text-xs text-muted-foreground">{subtitle}</span>
          )}
        </div>
      )}
    </div>
  )
}
