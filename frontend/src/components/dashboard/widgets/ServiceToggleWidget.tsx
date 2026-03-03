import { useQuery, useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Play, Square, Loader2 } from 'lucide-react'
import api from '@/lib/api'
import { cn } from '@/lib/utils'
import { useHasPermission } from '@/lib/permissions'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import type { InventoryObject } from '@/types'

interface ServiceToggleConfig {
  serviceName?: string
}

export function ServiceToggleWidget({ config }: { config: Record<string, any> }) {
  const navigate = useNavigate()
  const { serviceName } = config as ServiceToggleConfig
  const canDeploy = useHasPermission('services.deploy')
  const canStop = useHasPermission('services.stop')

  const { data: serviceObjects = [] } = useQuery({
    queryKey: ['inventory', 'service'],
    queryFn: async () => {
      const { data } = await api.get('/api/inventory/service')
      return (data.objects || []) as InventoryObject[]
    },
    refetchInterval: 10000,
  })

  const { data: servicesData = [] } = useQuery({
    queryKey: ['services'],
    queryFn: async () => {
      const { data } = await api.get('/api/services')
      return data.services || []
    },
  })

  const obj = serviceObjects.find((o) => (o.data.name as string) === serviceName || o.name === serviceName)
  const svcData = servicesData.find((s: any) => s.name === serviceName)
  const hasDeployScript = svcData?.scripts?.some((s: any) => s.name === 'deploy')
  const isRunning = obj?.data.power_status === 'running'

  const runAction = useMutation({
    mutationFn: ({ actionName, body }: { actionName: string; body?: any }) =>
      api.post(`/api/inventory/service/${obj!.id}/actions/${actionName}`, body || {}),
    onSuccess: (res) => {
      if (res.data.job_id) {
        toast.success('Action started')
        navigate(`/jobs/${res.data.job_id}`)
      }
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Action failed'),
  })

  if (!serviceName) {
    return <p className="text-sm text-muted-foreground text-center py-2">Configure a service</p>
  }

  return (
    <div className="flex flex-col items-center justify-center h-full gap-3">
      <div className="flex items-center gap-2">
        <span className={cn(
          "h-2.5 w-2.5 rounded-full",
          isRunning ? "bg-emerald-500 animate-status-pulse" : "bg-zinc-600"
        )} />
        <span className="font-medium text-sm">{serviceName}</span>
      </div>
      <span className="text-xs text-muted-foreground">{isRunning ? 'Running' : 'Stopped'}</span>
      {isRunning && canStop ? (
        <Button
          size="sm"
          variant="outline"
          className="border-destructive/40 text-destructive hover:bg-destructive/10"
          onClick={() => obj && runAction.mutate({ actionName: 'stop' })}
          disabled={!obj || runAction.isPending}
        >
          {runAction.isPending ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Square className="mr-1 h-3 w-3" />}
          Stop
        </Button>
      ) : !isRunning && canDeploy && hasDeployScript ? (
        <Button
          size="sm"
          variant="outline"
          onClick={() => obj && runAction.mutate({ actionName: 'run_script', body: { script: 'deploy', inputs: {} } })}
          disabled={!obj || runAction.isPending}
        >
          {runAction.isPending ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Play className="mr-1 h-3 w-3" />}
          Deploy
        </Button>
      ) : (
        <span className="text-xs text-muted-foreground">No actions available</span>
      )}
    </div>
  )
}
