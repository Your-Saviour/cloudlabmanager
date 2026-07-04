import { useState } from 'react'
import { Plus, Trash, Network } from 'lucide-react'

import api from '@/lib/api'
import type { Vpc, VpcInstance } from '@/types/vpc'
import { useVpcJobMutation } from './useVpcJobMutation'

import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { EmptyState } from '@/components/shared/EmptyState'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
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

interface VpcsTabProps {
  vpcs: Vpc[]
  instances: Record<string, VpcInstance>
  canManage: boolean
}

export function VpcsTab({ vpcs, instances, canManage }: VpcsTabProps) {
  const [createOpen, setCreateOpen] = useState(false)
  const [deleteVpc, setDeleteVpc] = useState<Vpc | null>(null)

  const [description, setDescription] = useState('')
  const [region, setRegion] = useState('')
  const [subnet, setSubnet] = useState('')
  const [subnetMask, setSubnetMask] = useState('')

  const attachedCount = (vpcId: string) =>
    Object.values(instances).filter((i) => i.attached_vpcs.some((v) => v.id === vpcId)).length

  const resetForm = () => {
    setDescription('')
    setRegion('')
    setSubnet('')
    setSubnetMask('')
  }

  const createMutation = useVpcJobMutation({
    mutationFn: async () => {
      const body: Record<string, unknown> = { description, region }
      if (subnet) body.v4_subnet = subnet
      if (subnetMask) body.v4_subnet_mask = Number(subnetMask)
      const { data } = await api.post('/api/vpc/vpcs', body)
      return data
    },
    successMessage: 'VPC creation started',
    errorMessage: 'Failed to create VPC',
    onSuccess: () => {
      setCreateOpen(false)
      resetForm()
    },
  })

  const deleteMutation = useVpcJobMutation({
    mutationFn: async (vpcId: string) => {
      const { data } = await api.delete(`/api/vpc/vpcs/${vpcId}`)
      return data
    },
    successMessage: 'VPC deletion started',
    errorMessage: 'Failed to delete VPC',
    onSuccess: () => setDeleteVpc(null),
  })

  return (
    <div className="space-y-4">
      {canManage && (
        <div className="flex justify-end">
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Create VPC
          </Button>
        </div>
      )}

      {vpcs.length === 0 ? (
        <EmptyState
          icon={<Network className="h-12 w-12" />}
          title="No VPCs"
          description="No VPCs found. Sync from Vultr or create one to get started."
        />
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Description</TableHead>
                <TableHead>Region</TableHead>
                <TableHead>Subnet</TableHead>
                <TableHead>ID</TableHead>
                <TableHead>Instances</TableHead>
                {canManage && <TableHead className="w-[60px]" />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {vpcs.map((vpc) => (
                <TableRow key={vpc.id}>
                  <TableCell className="font-medium">{vpc.description || '(no description)'}</TableCell>
                  <TableCell>
                    <Badge variant="secondary">{vpc.region}</Badge>
                  </TableCell>
                  <TableCell className="font-mono text-sm">
                    {vpc.v4_subnet}/{vpc.v4_subnet_mask}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground max-w-[220px] truncate">
                    {vpc.id}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{attachedCount(vpc.id)}</Badge>
                  </TableCell>
                  {canManage && (
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 w-8 p-0 text-destructive"
                        onClick={() => setDeleteVpc(vpc)}
                      >
                        <Trash className="h-4 w-4" />
                        <span className="sr-only">Delete VPC</span>
                      </Button>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Create VPC Dialog */}
      <Dialog
        open={createOpen}
        onOpenChange={(open) => {
          setCreateOpen(open)
          if (!open) resetForm()
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create VPC</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label>Description</Label>
              <Input
                placeholder="my-vpc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>Region</Label>
              <Select value={region} onValueChange={setRegion}>
                <SelectTrigger>
                  <SelectValue placeholder="Select a region" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="syd">Sydney (syd)</SelectItem>
                  <SelectItem value="mel">Melbourne (mel)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Subnet (optional)</Label>
                <Input
                  placeholder="10.10.0.0"
                  value={subnet}
                  onChange={(e) => setSubnet(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label>Mask (optional)</Label>
                <Input
                  placeholder="24"
                  type="number"
                  value={subnetMask}
                  onChange={(e) => setSubnetMask(e.target.value)}
                />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => createMutation.mutate(undefined)}
              disabled={!description || !region || createMutation.isPending}
            >
              {createMutation.isPending ? 'Creating...' : 'Create VPC'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <ConfirmDialog
        open={!!deleteVpc}
        onOpenChange={() => setDeleteVpc(null)}
        title="Delete VPC"
        description={`Permanently delete VPC "${deleteVpc?.description || deleteVpc?.id}"? All instances must be detached from this VPC first — deletion will fail otherwise.${deleteVpc && attachedCount(deleteVpc.id) > 0 ? ` Warning: ${attachedCount(deleteVpc.id)} instance(s) are currently attached.` : ''}`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => deleteVpc && deleteMutation.mutate(deleteVpc.id)}
      />
    </div>
  )
}
