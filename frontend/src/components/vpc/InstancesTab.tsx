import { useState } from 'react'
import { Plus, X, Server } from 'lucide-react'

import api from '@/lib/api'
import type { Vpc, VpcInstance, FirewallGroup } from '@/types/vpc'
import { useVpcJobMutation } from './useVpcJobMutation'

import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { EmptyState } from '@/components/shared/EmptyState'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface InstancesTabProps {
  instances: Record<string, VpcInstance>
  vpcs: Vpc[]
  firewallGroups: FirewallGroup[]
  canManage: boolean
}

const NO_FIREWALL = '__none__'

export function InstancesTab({ instances, vpcs, firewallGroups, canManage }: InstancesTabProps) {
  const entries = Object.entries(instances)

  const [attachTarget, setAttachTarget] = useState<{ id: string; instance: VpcInstance } | null>(null)
  const [attachVpcId, setAttachVpcId] = useState('')
  const [detachTarget, setDetachTarget] = useState<{
    id: string
    instance: VpcInstance
    vpcId: string
    vpcDescription: string
  } | null>(null)

  const attachMutation = useVpcJobMutation({
    mutationFn: async (vars: { instanceId: string; vpcId: string }) => {
      const { data } = await api.post(`/api/vpc/instances/${vars.instanceId}/attach`, {
        vpc_id: vars.vpcId,
      })
      return data
    },
    successMessage: 'VPC attach started',
    errorMessage: 'Failed to attach VPC',
    onSuccess: () => {
      setAttachTarget(null)
      setAttachVpcId('')
    },
  })

  const detachMutation = useVpcJobMutation({
    mutationFn: async (vars: { instanceId: string; vpcId: string }) => {
      const { data } = await api.post(`/api/vpc/instances/${vars.instanceId}/detach`, {
        vpc_id: vars.vpcId,
      })
      return data
    },
    successMessage: 'VPC detach started',
    errorMessage: 'Failed to detach VPC',
    onSuccess: () => setDetachTarget(null),
  })

  const firewallMutation = useVpcJobMutation({
    mutationFn: async (vars: { instanceId: string; groupId: string }) => {
      const { data } = await api.post(`/api/vpc/instances/${vars.instanceId}/firewall`, {
        firewall_group_id: vars.groupId,
      })
      return data
    },
    successMessage: 'Firewall group update started',
    errorMessage: 'Failed to update firewall group',
  })

  const availableVpcs = attachTarget
    ? vpcs.filter(
        (v) =>
          v.region === attachTarget.instance.region &&
          !attachTarget.instance.attached_vpcs.some((a) => a.id === v.id),
      )
    : []

  if (entries.length === 0) {
    return (
      <EmptyState
        icon={<Server className="h-12 w-12" />}
        title="No instances"
        description="No instances found. Sync from Vultr to load instance networking data."
      />
    )
  }

  return (
    <div className="space-y-4">
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Instance</TableHead>
              <TableHead>Main IP</TableHead>
              <TableHead>Region</TableHead>
              <TableHead>Attached VPCs</TableHead>
              <TableHead>Firewall Group</TableHead>
              {canManage && <TableHead className="w-[130px]" />}
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map(([id, inst]) => (
              <TableRow key={id}>
                <TableCell>
                  <div>
                    <span className="font-medium">{inst.label || '(no label)'}</span>
                    <p className="text-xs text-muted-foreground">{inst.hostname}</p>
                  </div>
                </TableCell>
                <TableCell className="font-mono text-sm">{inst.main_ip}</TableCell>
                <TableCell>
                  <Badge variant="secondary">{inst.region}</Badge>
                </TableCell>
                <TableCell>
                  {inst.attached_vpcs.length === 0 ? (
                    <span className="text-sm text-muted-foreground">None</span>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {inst.attached_vpcs.map((vpc) => (
                        <Badge key={vpc.id} variant="outline" className="gap-1 pr-1">
                          <span>
                            {vpc.description || vpc.id}
                            {vpc.ip_address ? ` (${vpc.ip_address})` : ''}
                          </span>
                          {canManage && (
                            <button
                              type="button"
                              className="ml-0.5 rounded-full hover:bg-muted p-0.5"
                              onClick={() =>
                                setDetachTarget({
                                  id,
                                  instance: inst,
                                  vpcId: vpc.id,
                                  vpcDescription: vpc.description || vpc.id,
                                })
                              }
                            >
                              <X className="h-3 w-3" />
                              <span className="sr-only">Detach VPC</span>
                            </button>
                          )}
                        </Badge>
                      ))}
                    </div>
                  )}
                </TableCell>
                <TableCell>
                  {canManage ? (
                    <Select
                      value={inst.firewall_group_id || NO_FIREWALL}
                      onValueChange={(v) =>
                        firewallMutation.mutate({
                          instanceId: id,
                          groupId: v === NO_FIREWALL ? '' : v,
                        })
                      }
                      disabled={firewallMutation.isPending}
                    >
                      <SelectTrigger className="w-[180px]">
                        <SelectValue placeholder="No firewall" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={NO_FIREWALL}>No firewall</SelectItem>
                        {firewallGroups.map((g) => (
                          <SelectItem key={g.id} value={g.id}>
                            {g.description || g.id}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <span className="text-sm">
                      {firewallGroups.find((g) => g.id === inst.firewall_group_id)?.description ||
                        (inst.firewall_group_id ? inst.firewall_group_id : 'None')}
                    </span>
                  )}
                </TableCell>
                {canManage && (
                  <TableCell>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setAttachVpcId('')
                        setAttachTarget({ id, instance: inst })
                      }}
                    >
                      <Plus className="mr-2 h-4 w-4" />
                      Attach VPC
                    </Button>
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* Attach VPC Dialog */}
      <Dialog
        open={!!attachTarget}
        onOpenChange={(open) => {
          if (!open) {
            setAttachTarget(null)
            setAttachVpcId('')
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Attach VPC</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <p className="text-sm text-muted-foreground">
              Attach a VPC to{' '}
              <span className="font-medium text-foreground">
                {attachTarget?.instance.label || attachTarget?.instance.hostname}
              </span>{' '}
              (region: {attachTarget?.instance.region})
            </p>
            <div className="space-y-2">
              <Label>VPC</Label>
              <Select value={attachVpcId} onValueChange={setAttachVpcId}>
                <SelectTrigger>
                  <SelectValue placeholder="Select a VPC" />
                </SelectTrigger>
                <SelectContent>
                  {availableVpcs.length === 0 ? (
                    <div className="px-2 py-1.5 text-sm text-muted-foreground">
                      No unattached VPCs in this region
                    </div>
                  ) : (
                    availableVpcs.map((v) => (
                      <SelectItem key={v.id} value={v.id}>
                        {v.description || v.id} ({v.v4_subnet}/{v.v4_subnet_mask})
                      </SelectItem>
                    ))
                  )}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAttachTarget(null)}>
              Cancel
            </Button>
            <Button
              onClick={() =>
                attachTarget && attachMutation.mutate({ instanceId: attachTarget.id, vpcId: attachVpcId })
              }
              disabled={!attachVpcId || attachMutation.isPending}
            >
              {attachMutation.isPending ? 'Attaching...' : 'Attach'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Detach Confirmation */}
      <ConfirmDialog
        open={!!detachTarget}
        onOpenChange={() => setDetachTarget(null)}
        title="Detach VPC"
        description={`Detach VPC "${detachTarget?.vpcDescription}" from ${detachTarget?.instance.label || detachTarget?.instance.hostname}? The instance will lose connectivity on this VPC.`}
        confirmLabel="Detach"
        variant="destructive"
        onConfirm={() =>
          detachTarget && detachMutation.mutate({ instanceId: detachTarget.id, vpcId: detachTarget.vpcId })
        }
      />
    </div>
  )
}
