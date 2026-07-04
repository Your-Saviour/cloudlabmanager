import { useState } from 'react'
import { Plus, Trash, ChevronDown, ChevronRight, Shield } from 'lucide-react'

import api from '@/lib/api'
import type { FirewallGroup, FirewallRule } from '@/types/vpc'
import { useVpcJobMutation } from './useVpcJobMutation'

import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { EmptyState } from '@/components/shared/EmptyState'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
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

interface FirewallGroupsTabProps {
  groups: FirewallGroup[]
  canManage: boolean
}

const PROTOCOLS = ['tcp', 'udp', 'icmp', 'gre', 'esp', 'ah']

export function FirewallGroupsTab({ groups, canManage }: FirewallGroupsTabProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [createGroupOpen, setCreateGroupOpen] = useState(false)
  const [groupDescription, setGroupDescription] = useState('')
  const [deleteGroup, setDeleteGroup] = useState<FirewallGroup | null>(null)

  // Add rule dialog state
  const [ruleGroup, setRuleGroup] = useState<FirewallGroup | null>(null)
  const [protocol, setProtocol] = useState('tcp')
  const [port, setPort] = useState('')
  const [subnet, setSubnet] = useState('0.0.0.0')
  const [subnetSize, setSubnetSize] = useState('0')
  const [ipType, setIpType] = useState('v4')
  const [source, setSource] = useState('')
  const [notes, setNotes] = useState('')
  const [deleteRule, setDeleteRule] = useState<{ group: FirewallGroup; rule: FirewallRule } | null>(null)

  const toggleExpanded = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const resetRuleForm = () => {
    setProtocol('tcp')
    setPort('')
    setSubnet('0.0.0.0')
    setSubnetSize('0')
    setIpType('v4')
    setSource('')
    setNotes('')
  }

  const createGroupMutation = useVpcJobMutation({
    mutationFn: async () => {
      const { data } = await api.post('/api/vpc/firewall-groups', { description: groupDescription })
      return data
    },
    successMessage: 'Firewall group creation started',
    errorMessage: 'Failed to create firewall group',
    onSuccess: () => {
      setCreateGroupOpen(false)
      setGroupDescription('')
    },
  })

  const deleteGroupMutation = useVpcJobMutation({
    mutationFn: async (groupId: string) => {
      const { data } = await api.delete(`/api/vpc/firewall-groups/${groupId}`)
      return data
    },
    successMessage: 'Firewall group deletion started',
    errorMessage: 'Failed to delete firewall group',
    onSuccess: () => setDeleteGroup(null),
  })

  const addRuleMutation = useVpcJobMutation({
    mutationFn: async (groupId: string) => {
      const { data } = await api.post(`/api/vpc/firewall-groups/${groupId}/rules`, {
        protocol,
        port,
        subnet,
        subnet_size: Number(subnetSize),
        ip_type: ipType,
        source,
        notes,
      })
      return data
    },
    successMessage: 'Firewall rule creation started',
    errorMessage: 'Failed to add firewall rule',
    onSuccess: () => {
      setRuleGroup(null)
      resetRuleForm()
    },
  })

  const deleteRuleMutation = useVpcJobMutation({
    mutationFn: async (vars: { groupId: string; ruleId: number }) => {
      const { data } = await api.delete(`/api/vpc/firewall-groups/${vars.groupId}/rules/${vars.ruleId}`)
      return data
    },
    successMessage: 'Firewall rule deletion started',
    errorMessage: 'Failed to delete firewall rule',
    onSuccess: () => setDeleteRule(null),
  })

  return (
    <div className="space-y-4">
      {canManage && (
        <div className="flex justify-end">
          <Button size="sm" onClick={() => setCreateGroupOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Create Group
          </Button>
        </div>
      )}

      {groups.length === 0 ? (
        <EmptyState
          icon={<Shield className="h-12 w-12" />}
          title="No firewall groups"
          description="No firewall groups found. Sync from Vultr or create one to get started."
        />
      ) : (
        <div className="space-y-3">
          {groups.map((group) => {
            const isOpen = expanded.has(group.id)
            return (
              <Card key={group.id}>
                <CardHeader
                  className="py-3 cursor-pointer"
                  onClick={() => toggleExpanded(group.id)}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      {isOpen ? (
                        <ChevronDown className="h-4 w-4 text-muted-foreground" />
                      ) : (
                        <ChevronRight className="h-4 w-4 text-muted-foreground" />
                      )}
                      <span className="font-medium">{group.description || '(no description)'}</span>
                      <span className="font-mono text-xs text-muted-foreground">{group.id}</span>
                      <Badge variant="outline">{group.rules.length} rule{group.rules.length === 1 ? '' : 's'}</Badge>
                    </div>
                    {canManage && (
                      <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            resetRuleForm()
                            setRuleGroup(group)
                          }}
                        >
                          <Plus className="mr-2 h-4 w-4" />
                          Add Rule
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-8 w-8 p-0 text-destructive"
                          onClick={() => setDeleteGroup(group)}
                        >
                          <Trash className="h-4 w-4" />
                          <span className="sr-only">Delete group</span>
                        </Button>
                      </div>
                    )}
                  </div>
                </CardHeader>
                {isOpen && (
                  <CardContent className="pt-0">
                    {group.rules.length === 0 ? (
                      <p className="text-sm text-muted-foreground py-2">No rules in this group.</p>
                    ) : (
                      <div className="rounded-md border">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>Protocol</TableHead>
                              <TableHead>Port</TableHead>
                              <TableHead>Source</TableHead>
                              <TableHead>IP Type</TableHead>
                              <TableHead>Notes</TableHead>
                              {canManage && <TableHead className="w-[60px]" />}
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {group.rules.map((rule) => (
                              <TableRow key={rule.id}>
                                <TableCell>
                                  <Badge variant="secondary">{rule.protocol}</Badge>
                                </TableCell>
                                <TableCell className="font-mono text-sm">{rule.port || '-'}</TableCell>
                                <TableCell className="font-mono text-sm">
                                  {rule.source === 'cloudflare'
                                    ? 'cloudflare'
                                    : `${rule.subnet}/${rule.subnet_size}`}
                                </TableCell>
                                <TableCell>{rule.ip_type}</TableCell>
                                <TableCell className="text-sm text-muted-foreground max-w-[220px] truncate">
                                  {rule.notes || '-'}
                                </TableCell>
                                {canManage && (
                                  <TableCell>
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      className="h-8 w-8 p-0 text-destructive"
                                      onClick={() => setDeleteRule({ group, rule })}
                                    >
                                      <Trash className="h-4 w-4" />
                                      <span className="sr-only">Delete rule</span>
                                    </Button>
                                  </TableCell>
                                )}
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    )}
                  </CardContent>
                )}
              </Card>
            )
          })}
        </div>
      )}

      {/* Create Group Dialog */}
      <Dialog
        open={createGroupOpen}
        onOpenChange={(open) => {
          setCreateGroupOpen(open)
          if (!open) setGroupDescription('')
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create Firewall Group</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label>Description</Label>
              <Input
                placeholder="web-servers"
                value={groupDescription}
                onChange={(e) => setGroupDescription(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateGroupOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => createGroupMutation.mutate(undefined)}
              disabled={!groupDescription || createGroupMutation.isPending}
            >
              {createGroupMutation.isPending ? 'Creating...' : 'Create Group'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Add Rule Dialog */}
      <Dialog
        open={!!ruleGroup}
        onOpenChange={(open) => {
          if (!open) {
            setRuleGroup(null)
            resetRuleForm()
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Firewall Rule</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <p className="text-sm text-muted-foreground">
              Group: <span className="font-medium text-foreground">{ruleGroup?.description || ruleGroup?.id}</span>
            </p>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Protocol</Label>
                <Select value={protocol} onValueChange={setProtocol}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PROTOCOLS.map((p) => (
                      <SelectItem key={p} value={p}>
                        {p}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Port / Range</Label>
                <Input
                  placeholder="443 or 8000:9000"
                  value={port}
                  onChange={(e) => setPort(e.target.value)}
                  disabled={!['tcp', 'udp'].includes(protocol)}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Subnet</Label>
                <Input
                  placeholder="0.0.0.0"
                  value={subnet}
                  onChange={(e) => setSubnet(e.target.value)}
                  disabled={source === 'cloudflare'}
                />
              </div>
              <div className="space-y-2">
                <Label>Subnet Size</Label>
                <Input
                  placeholder="0"
                  type="number"
                  value={subnetSize}
                  onChange={(e) => setSubnetSize(e.target.value)}
                  disabled={source === 'cloudflare'}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>IP Type</Label>
                <Select value={ipType} onValueChange={setIpType}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="v4">v4</SelectItem>
                    <SelectItem value="v6">v6</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Source</Label>
                <Select
                  value={source || 'subnet'}
                  onValueChange={(v) => setSource(v === 'subnet' ? '' : v)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="subnet">Subnet</SelectItem>
                    <SelectItem value="cloudflare">Cloudflare</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-2">
              <Label>Notes</Label>
              <Input
                placeholder="Allow HTTPS"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRuleGroup(null)}>
              Cancel
            </Button>
            <Button
              onClick={() => ruleGroup && addRuleMutation.mutate(ruleGroup.id)}
              disabled={addRuleMutation.isPending}
            >
              {addRuleMutation.isPending ? 'Adding...' : 'Add Rule'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Group Confirmation */}
      <ConfirmDialog
        open={!!deleteGroup}
        onOpenChange={() => setDeleteGroup(null)}
        title="Delete Firewall Group"
        description={`Permanently delete firewall group "${deleteGroup?.description || deleteGroup?.id}" and all its rules? Instances using this group will lose its protection.`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => deleteGroup && deleteGroupMutation.mutate(deleteGroup.id)}
      />

      {/* Delete Rule Confirmation */}
      <ConfirmDialog
        open={!!deleteRule}
        onOpenChange={() => setDeleteRule(null)}
        title="Delete Firewall Rule"
        description={`Delete ${deleteRule?.rule.protocol} rule${deleteRule?.rule.port ? ` for port ${deleteRule.rule.port}` : ''} from "${deleteRule?.group.description || deleteRule?.group.id}"?`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() =>
          deleteRule && deleteRuleMutation.mutate({ groupId: deleteRule.group.id, ruleId: deleteRule.rule.id })
        }
      />
    </div>
  )
}
