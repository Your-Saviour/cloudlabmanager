import { useQuery } from '@tanstack/react-query'
import { RefreshCw, Network } from 'lucide-react'
import { toast } from 'sonner'

import api from '@/lib/api'
import { useHasPermission } from '@/lib/permissions'
import { relativeTime } from '@/lib/utils'
import type { VpcReportResponse } from '@/types/vpc'
import { useVpcJobMutation } from '@/components/vpc/useVpcJobMutation'

import { PageHeader } from '@/components/shared/PageHeader'
import { EmptyState } from '@/components/shared/EmptyState'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

import { VpcsTab } from '@/components/vpc/VpcsTab'
import { FirewallGroupsTab } from '@/components/vpc/FirewallGroupsTab'
import { InstancesTab } from '@/components/vpc/InstancesTab'

export default function VpcPage() {
  const canManage = useHasPermission('vpc.manage')

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['vpc', 'report'],
    queryFn: async () => {
      const { data } = await api.get('/api/vpc/report')
      return data as VpcReportResponse
    },
    refetchInterval: 15000,
  })

  const syncMutation = useVpcJobMutation({
    mutationFn: async () => {
      const { data } = await api.post('/api/vpc/sync')
      return data
    },
    successMessage: 'Sync from Vultr started',
    errorMessage: 'Failed to start sync',
  })

  const report = data?.last_synced ? data : null

  if (isLoading) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      <PageHeader title="Networking" description="Manage VPCs, firewall groups, and instance network attachments">
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground">
            {data?.last_synced ? `Last synced ${relativeTime(data.last_synced)}` : 'Never synced'}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => syncMutation.mutate(undefined)}
            disabled={syncMutation.isPending}
          >
            <RefreshCw className={`mr-2 h-4 w-4 ${syncMutation.isPending ? 'animate-spin' : ''}`} />
            Sync from Vultr
          </Button>
        </div>
      </PageHeader>

      {!report ? (
        <EmptyState
          icon={<Network className="h-12 w-12" />}
          title="No networking data"
          description="Sync from Vultr to load VPC, firewall, and instance networking data."
        >
          <Button
            onClick={() => {
              syncMutation.mutate(undefined)
              toast.info('Data will appear once the sync job completes')
              refetch()
            }}
            disabled={syncMutation.isPending}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            Sync from Vultr
          </Button>
        </EmptyState>
      ) : (
        <Tabs defaultValue="vpcs">
          <TabsList>
            <TabsTrigger value="vpcs">VPCs</TabsTrigger>
            <TabsTrigger value="firewall">Firewall Groups</TabsTrigger>
            <TabsTrigger value="instances">Instances</TabsTrigger>
          </TabsList>
          <TabsContent value="vpcs" className="mt-4">
            <VpcsTab vpcs={report.vpcs || []} instances={report.instances || {}} canManage={canManage} />
          </TabsContent>
          <TabsContent value="firewall" className="mt-4">
            <FirewallGroupsTab groups={report.firewall_groups || []} canManage={canManage} />
          </TabsContent>
          <TabsContent value="instances" className="mt-4">
            <InstancesTab
              instances={report.instances || {}}
              vpcs={report.vpcs || []}
              firewallGroups={report.firewall_groups || []}
              canManage={canManage}
            />
          </TabsContent>
        </Tabs>
      )}
    </div>
  )
}
