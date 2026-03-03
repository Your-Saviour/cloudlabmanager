import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { QuickLinksSection } from '@/components/dashboard/QuickLinksSection'

export function QuickLinksWidget(_props: { config: Record<string, any> }) {
  const { data: serviceOutputs } = useQuery({
    queryKey: ['service-outputs'],
    queryFn: async () => {
      const { data } = await api.get('/api/services/outputs')
      return data.outputs as Record<string, { label: string; type: string; value: string }[]>
    },
    refetchInterval: 30000,
  })

  const quickLinks: { service: string; label: string; url: string }[] = []
  if (serviceOutputs) {
    for (const [service, outputs] of Object.entries(serviceOutputs)) {
      for (const out of outputs) {
        if (out.type === 'url' && out.value) {
          quickLinks.push({ service, label: out.label, url: out.value })
        }
      }
    }
  }

  if (quickLinks.length === 0) {
    return <p className="text-sm text-muted-foreground text-center py-4">No quick links available yet.</p>
  }

  return <QuickLinksSection quickLinks={quickLinks} />
}
