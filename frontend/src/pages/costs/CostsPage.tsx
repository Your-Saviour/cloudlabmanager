import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, DollarSign } from 'lucide-react'
import api from '@/lib/api'
import { PageHeader } from '@/components/shared/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from 'sonner'
import type { CostData } from '@/types'

export default function CostsPage() {
  const queryClient = useQueryClient()

  const { data: costs, isLoading } = useQuery({
    queryKey: ['costs'],
    queryFn: async () => {
      const { data } = await api.get('/api/costs')
      return data as CostData
    },
  })

  const { data: byTag } = useQuery({
    queryKey: ['costs', 'by-tag'],
    queryFn: async () => {
      const { data } = await api.get('/api/costs/by-tag')
      return data.by_tag as Record<string, number>
    },
  })

  const { data: byRegion } = useQuery({
    queryKey: ['costs', 'by-region'],
    queryFn: async () => {
      const { data } = await api.get('/api/costs/by-region')
      return data.by_region as Record<string, number>
    },
  })

  const refreshMutation = useMutation({
    mutationFn: () => api.post('/api/costs/refresh'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['costs'] })
      toast.success('Costs refreshed')
    },
    onError: () => toast.error('Refresh failed'),
  })

  return (
    <div>
      <PageHeader title="Costs" description="Infrastructure cost breakdown">
        <Button
          variant="outline"
          size="sm"
          onClick={() => refreshMutation.mutate()}
          disabled={refreshMutation.isPending}
        >
          <RefreshCw className={`mr-2 h-3 w-3 ${refreshMutation.isPending ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </PageHeader>

      {isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-24 w-64" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : (
        <>
          {/* Total */}
          <Card className="mb-6 max-w-xs">
            <CardContent className="pt-6">
              <div className="flex items-center gap-3">
                <DollarSign className="h-8 w-8 text-primary" />
                <div>
                  <p className="text-sm text-muted-foreground">Monthly Total</p>
                  <p className="text-3xl font-bold">
                    ${costs?.total_monthly_cost?.toFixed(2) || '0.00'}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-6 lg:grid-cols-2 mb-6">
            {/* By Tag */}
            {byTag && Object.keys(byTag).length > 0 && (
              <Card>
                <CardHeader><CardTitle className="text-sm">By Tag</CardTitle></CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    {Object.entries(byTag)
                      .sort(([, a], [, b]) => b - a)
                      .map(([tag, cost]) => (
                        <div key={tag} className="flex items-center justify-between">
                          <Badge variant="outline">{tag}</Badge>
                          <span className="font-mono text-sm">${cost.toFixed(2)}</span>
                        </div>
                      ))}
                  </div>
                </CardContent>
              </Card>
            )}

            {/* By Region */}
            {byRegion && Object.keys(byRegion).length > 0 && (
              <Card>
                <CardHeader><CardTitle className="text-sm">By Region</CardTitle></CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    {Object.entries(byRegion)
                      .sort(([, a], [, b]) => b - a)
                      .map(([region, cost]) => (
                        <div key={region} className="flex items-center justify-between">
                          <span className="text-sm text-muted-foreground">{region}</span>
                          <span className="font-mono text-sm">${cost.toFixed(2)}</span>
                        </div>
                      ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>

          {/* Instances */}
          <Card>
            <CardHeader><CardTitle className="text-sm">Instances</CardTitle></CardHeader>
            <CardContent>
              {(!costs?.instances || costs.instances.length === 0) ? (
                <p className="text-sm text-muted-foreground text-center py-4">No instance data available</p>
              ) : (
                <div className="space-y-2">
                  {costs.instances
                    .sort((a, b) => b.monthly_cost - a.monthly_cost)
                    .map((inst, i) => (
                      <div key={i} className="flex items-center justify-between px-3 py-2 rounded-md hover:bg-muted/30">
                        <div>
                          <p className="text-sm font-medium">{inst.label}</p>
                          <p className="text-xs text-muted-foreground">
                            {inst.region} &middot; {inst.plan}
                          </p>
                        </div>
                        <div className="text-right">
                          <p className="font-mono text-sm">${inst.monthly_cost.toFixed(2)}/mo</p>
                          {inst.tags.length > 0 && (
                            <div className="flex gap-1 justify-end mt-1">
                              {inst.tags.map((t) => (
                                <Badge key={t} variant="outline" className="text-[10px]">{t}</Badge>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
