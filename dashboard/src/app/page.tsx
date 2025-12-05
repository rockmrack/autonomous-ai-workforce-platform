'use client'

import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  Users,
  Briefcase,
  DollarSign,
  TrendingUp,
  Clock,
  CheckCircle,
  AlertTriangle,
  Activity,
} from 'lucide-react'
import { StatsCard } from '@/components/dashboard/stats-card'
import { RevenueChart } from '@/components/dashboard/revenue-chart'
import { AgentActivity } from '@/components/dashboard/agent-activity'
import { RecentJobs } from '@/components/dashboard/recent-jobs'
import { SystemHealth } from '@/components/dashboard/system-health'

async function fetchDashboardStats() {
  const response = await fetch('/api/system/status')
  if (!response.ok) throw new Error('Failed to fetch stats')
  return response.json()
}

export default function DashboardPage() {
  const { data: stats, isLoading } = useQuery({
    queryKey: ['dashboard-stats'],
    queryFn: fetchDashboardStats,
    refetchInterval: 30000, // Refresh every 30 seconds
  })

  const statsCards = [
    {
      title: 'Active Agents',
      value: stats?.agents?.active || 0,
      total: stats?.agents?.total || 0,
      icon: Users,
      color: 'brand',
      trend: '+12%',
    },
    {
      title: 'Jobs in Progress',
      value: stats?.jobs?.in_progress || 0,
      icon: Briefcase,
      color: 'warning',
      subtitle: `${stats?.jobs?.pending || 0} pending`,
    },
    {
      title: 'Revenue (30d)',
      value: `$${(stats?.revenue?.last_30_days || 0).toLocaleString()}`,
      icon: DollarSign,
      color: 'success',
      trend: '+8.5%',
    },
    {
      title: 'Success Rate',
      value: `${((stats?.metrics?.success_rate || 0) * 100).toFixed(1)}%`,
      icon: TrendingUp,
      color: 'brand',
      trend: '+2.3%',
    },
  ]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-muted-foreground">
            Real-time overview of your AI workforce
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Activity className="h-4 w-4 text-success-500 animate-pulse" />
          <span>Live</span>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {statsCards.map((stat, index) => (
          <motion.div
            key={stat.title}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.1 }}
          >
            <StatsCard {...stat} isLoading={isLoading} />
          </motion.div>
        ))}
      </div>

      {/* Charts Row */}
      <div className="grid gap-6 lg:grid-cols-3">
        <motion.div
          className="lg:col-span-2"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
        >
          <RevenueChart />
        </motion.div>
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5 }}
        >
          <SystemHealth />
        </motion.div>
      </div>

      {/* Activity Row */}
      <div className="grid gap-6 lg:grid-cols-2">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.6 }}
        >
          <AgentActivity />
        </motion.div>
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.7 }}
        >
          <RecentJobs />
        </motion.div>
      </div>
    </div>
  )
}
