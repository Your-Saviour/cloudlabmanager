import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Shield, Search } from 'lucide-react'
import api from '@/lib/api'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'

interface ServiceAccessEntry {
  name: string
  permissions: string[]
  source: string
}

const PERMISSION_COLUMNS = [
  { key: 'view', label: 'View', color: 'bg-blue-500/15 text-blue-400 border-blue-500/30' },
  { key: 'deploy', label: 'Deploy', color: 'bg-green-500/15 text-green-400 border-green-500/30' },
  { key: 'stop', label: 'Stop', color: 'bg-red-500/15 text-red-400 border-red-500/30' },
  { key: 'config', label: 'Config', color: 'bg-amber-500/15 text-amber-400 border-amber-500/30' },
] as const

interface UserServiceAccessProps {
  userId: number
}

export default function UserServiceAccess({ userId }: UserServiceAccessProps) {
  const [filter, setFilter] = useState('')

  const { data: services = [], isLoading } = useQuery({
    queryKey: ['user', userId, 'service-access'],
    queryFn: async () => {
      const { data } = await api.get(`/api/users/${userId}/service-access`)
      return (data.services || []) as ServiceAccessEntry[]
    },
  })

  const filtered = useMemo(
    () =>
      filter
        ? services.filter((s) => s.name.toLowerCase().includes(filter.toLowerCase()))
        : services,
    [services, filter]
  )

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    )
  }

  if (services.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        <Shield className="h-8 w-8 mx-auto mb-2 opacity-50" />
        <p>This user has no service access.</p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="relative">
        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Filter services..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="pl-9 h-9"
        />
      </div>

      <div className="rounded-md border overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/30">
              <th scope="col" className="text-left px-3 py-2 font-medium">Service</th>
              {PERMISSION_COLUMNS.map((p) => (
                <th key={p.key} scope="col" className="text-center px-2 py-2 font-medium w-20">
                  {p.label}
                </th>
              ))}
              <th scope="col" className="text-left px-3 py-2 font-medium">Source</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((svc) => (
              <tr key={svc.name} className="border-b last:border-0 hover:bg-muted/20 transition-colors">
                <td className="px-3 py-2 font-medium">{svc.name}</td>
                {PERMISSION_COLUMNS.map((p) => (
                  <td key={p.key} className="text-center px-2 py-2">
                    {svc.permissions.includes(p.key) ? (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Badge
                            variant="outline"
                            className={`text-[10px] px-1.5 py-0 ${p.color}`}
                          >
                            ✓
                          </Badge>
                        </TooltipTrigger>
                        <TooltipContent side="top" className="text-xs">
                          {p.label} access via {svc.source}
                        </TooltipContent>
                      </Tooltip>
                    ) : (
                      <span className="text-muted-foreground/30">—</span>
                    )}
                  </td>
                ))}
                <td className="px-3 py-2">
                  <Badge variant="outline" className="text-xs text-muted-foreground">
                    {svc.source}
                  </Badge>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="text-center py-4 text-muted-foreground">
                  No services match the filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-muted-foreground">
        Showing {filtered.length} of {services.length} service{services.length !== 1 ? 's' : ''}
      </p>
    </div>
  )
}
