'use client'

import { useQuery } from '@tanstack/react-query'
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  CartesianGrid,
} from 'recharts'
import { formatCurrency } from '@/lib/utils'

// Mock data - in production, fetch from API
const mockData = [
  { date: 'Jan 1', revenue: 4200, jobs: 12 },
  { date: 'Jan 2', revenue: 5100, jobs: 15 },
  { date: 'Jan 3', revenue: 4800, jobs: 14 },
  { date: 'Jan 4', revenue: 6200, jobs: 18 },
  { date: 'Jan 5', revenue: 5800, jobs: 16 },
  { date: 'Jan 6', revenue: 7100, jobs: 21 },
  { date: 'Jan 7', revenue: 6500, jobs: 19 },
  { date: 'Jan 8', revenue: 5900, jobs: 17 },
  { date: 'Jan 9', revenue: 6800, jobs: 20 },
  { date: 'Jan 10', revenue: 7500, jobs: 22 },
  { date: 'Jan 11', revenue: 8200, jobs: 24 },
  { date: 'Jan 12', revenue: 7800, jobs: 23 },
  { date: 'Jan 13', revenue: 8500, jobs: 25 },
  { date: 'Jan 14', revenue: 9100, jobs: 27 },
]

export function RevenueChart() {
  return (
    <div className="rounded-xl border bg-card p-6 shadow-sm">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-lg font-semibold">Revenue Overview</h3>
          <p className="text-sm text-muted-foreground">
            Daily revenue for the last 14 days
          </p>
        </div>
        <div className="flex gap-4">
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 rounded-full bg-brand-500" />
            <span className="text-sm text-muted-foreground">Revenue</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 rounded-full bg-success-500" />
            <span className="text-sm text-muted-foreground">Jobs</span>
          </div>
        </div>
      </div>

      <div className="h-[300px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={mockData}>
            <defs>
              <linearGradient id="colorRevenue" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#0ea5e9" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#0ea5e9" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="colorJobs" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
            <XAxis
              dataKey="date"
              stroke="#888888"
              fontSize={12}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              stroke="#888888"
              fontSize={12}
              tickLine={false}
              axisLine={false}
              tickFormatter={(value) => `$${value}`}
            />
            <Tooltip
              content={({ active, payload }) => {
                if (active && payload && payload.length) {
                  return (
                    <div className="rounded-lg border bg-card p-3 shadow-lg">
                      <p className="text-sm font-medium">
                        {payload[0]?.payload?.date}
                      </p>
                      <p className="text-sm text-brand-500">
                        Revenue: {formatCurrency(payload[0]?.value as number)}
                      </p>
                      <p className="text-sm text-success-500">
                        Jobs: {payload[1]?.value}
                      </p>
                    </div>
                  )
                }
                return null
              }}
            />
            <Area
              type="monotone"
              dataKey="revenue"
              stroke="#0ea5e9"
              strokeWidth={2}
              fillOpacity={1}
              fill="url(#colorRevenue)"
            />
            <Area
              type="monotone"
              dataKey="jobs"
              stroke="#22c55e"
              strokeWidth={2}
              fillOpacity={1}
              fill="url(#colorJobs)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
