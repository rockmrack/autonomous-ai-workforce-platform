'use client'

import { motion } from 'framer-motion'
import { cn, formatTimeAgo, getStatusBgColor } from '@/lib/utils'

// Mock data
const activities = [
  {
    id: '1',
    agent: 'Alex Thompson',
    action: 'Submitted proposal',
    target: 'Website Redesign Project',
    platform: 'Upwork',
    status: 'pending',
    timestamp: new Date(Date.now() - 5 * 60 * 1000),
  },
  {
    id: '2',
    agent: 'Sarah Chen',
    action: 'Completed task',
    target: 'SEO Article - 2000 words',
    platform: 'Fiverr',
    status: 'completed',
    timestamp: new Date(Date.now() - 15 * 60 * 1000),
  },
  {
    id: '3',
    agent: 'Mike Rodriguez',
    action: 'Started working on',
    target: 'Data Entry Project',
    platform: 'Upwork',
    status: 'in_progress',
    timestamp: new Date(Date.now() - 30 * 60 * 1000),
  },
  {
    id: '4',
    agent: 'Emily Watson',
    action: 'Received feedback',
    target: 'Logo Design',
    platform: 'Fiverr',
    status: 'completed',
    timestamp: new Date(Date.now() - 45 * 60 * 1000),
  },
  {
    id: '5',
    agent: 'James Park',
    action: 'Proposal accepted',
    target: 'React Development',
    platform: 'Upwork',
    status: 'active',
    timestamp: new Date(Date.now() - 60 * 60 * 1000),
  },
]

export function AgentActivity() {
  return (
    <div className="rounded-xl border bg-card p-6 shadow-sm">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold">Recent Activity</h3>
        <button className="text-sm text-brand-500 hover:text-brand-600">
          View all
        </button>
      </div>

      <div className="space-y-4">
        {activities.map((activity, index) => (
          <motion.div
            key={activity.id}
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: index * 0.1 }}
            className="flex items-start gap-4 p-3 rounded-lg hover:bg-muted/50 transition-colors"
          >
            {/* Avatar */}
            <div className="h-10 w-10 rounded-full bg-gradient-to-br from-brand-400 to-brand-600 flex items-center justify-center text-white font-medium text-sm flex-shrink-0">
              {activity.agent.split(' ').map(n => n[0]).join('')}
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0">
              <p className="text-sm">
                <span className="font-medium">{activity.agent}</span>
                {' '}
                <span className="text-muted-foreground">{activity.action}</span>
              </p>
              <p className="text-sm font-medium truncate">{activity.target}</p>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-xs text-muted-foreground">
                  {activity.platform}
                </span>
                <span className="text-muted-foreground">•</span>
                <span className="text-xs text-muted-foreground">
                  {formatTimeAgo(activity.timestamp)}
                </span>
              </div>
            </div>

            {/* Status Badge */}
            <span
              className={cn(
                'px-2 py-1 rounded-full text-xs font-medium capitalize',
                getStatusBgColor(activity.status)
              )}
            >
              {activity.status.replace('_', ' ')}
            </span>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
