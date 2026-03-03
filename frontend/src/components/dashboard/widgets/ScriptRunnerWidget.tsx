import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Play, Loader2, FileText } from 'lucide-react'
import api from '@/lib/api'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import type { InventoryObject } from '@/types'

interface ScriptRunnerConfig {
  serviceName?: string
  scriptName?: string
}

export function ScriptRunnerWidget({ config }: { config: Record<string, any> }) {
  const navigate = useNavigate()
  const { serviceName, scriptName } = config as ScriptRunnerConfig

  const { data: serviceObjects = [] } = useQuery({
    queryKey: ['inventory', 'service'],
    queryFn: async () => {
      const { data } = await api.get('/api/inventory/service')
      return (data.objects || []) as InventoryObject[]
    },
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
  const script = svcData?.scripts?.find((s: any) => s.name === scriptName)

  const runScript = useMutation({
    mutationFn: () =>
      api.post(`/api/inventory/service/${obj!.id}/actions/run_script`, { script: scriptName, inputs: {} }),
    onSuccess: (res) => {
      if (res.data.job_id) {
        toast.success(`Script "${scriptName}" started`)
        navigate(`/jobs/${res.data.job_id}`)
      }
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Script failed'),
  })

  if (!serviceName || !scriptName) {
    return <p className="text-sm text-muted-foreground text-center py-2">Configure service and script</p>
  }

  return (
    <div className="flex flex-col items-center justify-center h-full gap-3">
      <FileText className="h-5 w-5 text-muted-foreground" />
      <div className="text-center">
        <p className="font-medium text-sm">{scriptName}</p>
        <p className="text-xs text-muted-foreground">{serviceName}</p>
      </div>
      {script?.description && (
        <p className="text-xs text-muted-foreground text-center px-2 line-clamp-2">{script.description}</p>
      )}
      <Button
        size="sm"
        onClick={() => runScript.mutate()}
        disabled={!obj || runScript.isPending}
      >
        {runScript.isPending ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Play className="mr-1 h-3 w-3" />}
        Run
      </Button>
    </div>
  )
}
