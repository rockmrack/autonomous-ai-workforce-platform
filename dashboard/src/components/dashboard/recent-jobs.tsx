'use client'

import { motion } from 'framer-motion'
import { ExternalLink, DollarSign, Clock } from 'lucide-react'
import { cn, formatCurrency, getStatusBgColor } from '@/lib/utils'

// Mock data
const jobs = [
  {
    id: '1',
    title: 'Full Stack Developer for E-commerce Platform',
    platform: 'Upwork',
    budget: 5000,
    status: 'in_progress',
    deadline: '2024-01-20',
    progress: 65,
    agent: 'Alex Thompson',
  },
  {
    id: '2',
    title: 'Content Writing - 10 Blog Articles',
    platform: 'Fiverr',
    budget: 800,
    status: 'pending',
    deadline: '2024-01-18',
    progress: 0,
    agent: 'Sarah Chen',
  },
  {
    id: '3',
    title: 'Logo and Brand Identity Design',
    platform: 'Upwork',
    budget: 1200,
    status: 'completed',
    deadline: '2024-01-15',
    progress: 100,
    agent: 'Emily Watson',
  },
  {
    id: '4',
    title: 'Data Analysis and Reporting',
    platform: 'Reddit',
    budget: 600,
    status: 'in_progress',
    deadline: '2024-01-22',
    progress: 30,
    agent: 'Mike Rodriguez',
  },
]

export function RecentJobs() {
  return (
    <div className="rounded-xl border bg-card p-6 shadow-sm">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold">Active Jobs</h3>
        <button className="text-sm text-brand-500 hover:text-brand-600">
          View all
        </button>
      </div>

      <div className="space-y-4">
        {jobs.map((job, index) => (
          <motion.div
            key={job.id}
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: index * 0.1 }}
            className="p-4 rounded-lg border hover:border-brand-200 hover:shadow-sm transition-all cursor-pointer"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <h4 className="font-medium text-sm truncate">{job.title}</h4>
                  <ExternalLink className="h-3 w-3 text-muted-foreground flex-shrink-0" />
                </div>
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <span className="px-1.5 py-0.5 rounded bg-muted">
                    {job.platform}
                  </span>
                  <span className="flex items-center gap-1">
                    <DollarSign className="h-3 w-3" />
                    {formatCurrency(job.budget)}
                  </span>
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {new Date(job.deadline).toLocaleDateString()}
                  </span>
                </div>
              </div>
              <span
                className={cn(
                  'px-2 py-1 rounded-full text-xs font-medium capitalize flex-shrink-0',
                  getStatusBgColor(job.status)
                )}
              >
                {job.status.replace('_', ' ')}
              </span>
            </div>

            {/* Progress Bar */}
            {job.status === 'in_progress' && (
              <div className="mt-3">
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="text-muted-foreground">Progress</span>
                  <span className="font-medium">{job.progress}%</span>
                </div>
                <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${job.progress}%` }}
                    transition={{ duration: 0.5, delay: index * 0.1 }}
                    className="h-full rounded-full bg-brand-500"
                  />
                </div>
              </div>
            )}

            <div className="mt-3 flex items-center gap-2">
              <div className="h-6 w-6 rounded-full bg-gradient-to-br from-brand-400 to-brand-600 flex items-center justify-center text-white text-[10px] font-medium">
                {job.agent.split(' ').map(n => n[0]).join('')}
              </div>
              <span className="text-xs text-muted-foreground">{job.agent}</span>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
