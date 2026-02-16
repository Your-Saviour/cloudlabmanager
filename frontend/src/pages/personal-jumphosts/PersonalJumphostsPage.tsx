import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Trash, ExternalLink, Copy, Monitor, TimerReset } from 'lucide-react'
import { toast } from 'sonner'

import { useHasPermission } from '@/lib/permissions'
import {
  usePersonalJumphosts,
  usePersonalJumphostConfig,
  useCreateJumphost,
  useDestroyJumphost,
  useExtendJumphostTTL,
  type PersonalJumphost,
} from '@/hooks/usePersonalJumphosts'

import { PageHeader } from '@/components/shared/PageHeader'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip'
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

const DOMAIN = 'ye-et.com'

const REGIONS: { value: string; label: string }[] = [
  { value: 'mel', label: 'Melbourne (mel)' },
  { value: 'syd', label: 'Sydney (syd)' },
]

function formatTTL(ttlHours: number | null, createdAt: string | null): { text: string; color: string } | null {
  if (!ttlHours || ttlHours === 0 || !createdAt) return null
  const created = new Date(createdAt)
  const expiresAt = new Date(created.getTime() + ttlHours * 60 * 60 * 1000)
  const now = new Date()
  const remainingMs = expiresAt.getTime() - now.getTime()
  if (remainingMs <= 0) return { text: 'Expired', color: 'text-red-500' }

  const hours = Math.floor(remainingMs / (60 * 60 * 1000))
  const minutes = Math.floor((remainingMs % (60 * 60 * 1000)) / (60 * 1000))
  const text = hours > 0 ? `${hours}h ${minutes}m remaining` : `${minutes}m remaining`

  // Color: red < 15min, amber < 1h, default otherwise
  let color = ''
  if (remainingMs < 15 * 60 * 1000) color = 'text-red-500'
  else if (remainingMs < 60 * 60 * 1000) color = 'text-amber-500'

  return { text, color }
}

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text).then(
    () => toast.success('Copied to clipboard'),
    () => toast.error('Failed to copy to clipboard'),
  )
}

export default function PersonalJumphostsPage() {
  const navigate = useNavigate()
  const canCreate = useHasPermission('personal_jumphosts.create')
  const canDestroy = useHasPermission('personal_jumphosts.destroy')

  const { data: hosts = [], isLoading } = usePersonalJumphosts()
  const { data: config } = usePersonalJumphostConfig()

  const createMutation = useCreateJumphost()
  const destroyMutation = useDestroyJumphost()
  const extendMutation = useExtendJumphostTTL()

  const [createOpen, setCreateOpen] = useState(false)
  const [createRegion, setCreateRegion] = useState('')
  const [destroyHost, setDestroyHost] = useState<PersonalJumphost | null>(null)

  const handleCreate = () => {
    const region = createRegion || config?.default_region || 'mel'
    createMutation.mutate(region, {
      onSuccess: (data) => {
        toast.success(`Creating jump host: ${data.hostname}`)
        setCreateOpen(false)
        setCreateRegion('')
        if (data.job_id) navigate(`/jobs/${data.job_id}`)
      },
      onError: (err: any) => {
        toast.error(err.response?.data?.detail || 'Failed to create jump host')
      },
    })
  }

  const handleDestroy = () => {
    if (!destroyHost) return
    destroyMutation.mutate(destroyHost.hostname, {
      onSuccess: (data) => {
        toast.success(`Destroying ${destroyHost.hostname}`)
        setDestroyHost(null)
        if (data.job_id) navigate(`/jobs/${data.job_id}`)
      },
      onError: (err: any) => {
        toast.error(err.response?.data?.detail || 'Failed to destroy jump host')
      },
    })
  }

  const maxPerUser = config?.max_per_user ?? 3
  const limitText = maxPerUser > 0 ? `${hosts.length}/${maxPerUser} used` : `${hosts.length} active`

  if (isLoading) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      <PageHeader title="My Jump Hosts" description="Personal web-based terminal hosts">
        {canCreate && (
          <Button
            size="sm"
            onClick={() => setCreateOpen(true)}
            disabled={maxPerUser > 0 && hosts.length >= maxPerUser}
          >
            <Plus className="mr-2 h-4 w-4" />
            Create
          </Button>
        )}
      </PageHeader>

      {/* Limit indicator */}
      <div className="flex items-center gap-2">
        <Badge variant="secondary">{limitText}</Badge>
      </div>

      {/* Host cards */}
      {hosts.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <Monitor className="mx-auto h-10 w-10 text-muted-foreground mb-3" />
            <p className="text-muted-foreground">No personal jump hosts running.</p>
            {canCreate && (
              <p className="text-sm text-muted-foreground mt-1">
                Click "Create" to spin up a web terminal.
              </p>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          {hosts.map((host) => {
            const url = `https://${host.hostname}.${DOMAIN}`
            const ttl = formatTTL(host.ttl_hours, host.created_at)
            return (
              <Card key={host.hostname}>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-base font-mono">{host.hostname}</CardTitle>
                    <StatusBadge status={host.power_status} />
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                    <div>
                      <span className="text-muted-foreground">Region</span>
                      <p>{host.region || '-'}</p>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Plan</span>
                      <p>{host.plan || '-'}</p>
                    </div>
                    <div>
                      <span className="text-muted-foreground">User</span>
                      <p>{host.owner}</p>
                    </div>
                    {ttl && (
                      <div>
                        <span className="text-muted-foreground">TTL</span>
                        <p className={ttl.color}>{ttl.text}</p>
                      </div>
                    )}
                  </div>

                  {/* URL row */}
                  <div className="flex items-center gap-2 text-sm">
                    <span className="text-muted-foreground shrink-0">URL</span>
                    <a
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-primary hover:underline truncate"
                    >
                      {url}
                    </a>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6 shrink-0"
                          aria-label="Copy URL to clipboard"
                          onClick={() => copyToClipboard(url)}
                        >
                          <Copy className="h-3 w-3" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>Copy URL</TooltipContent>
                    </Tooltip>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6 shrink-0"
                          aria-label={`Open ${host.hostname} in new tab`}
                          onClick={() => window.open(url, '_blank')}
                        >
                          <ExternalLink className="h-3 w-3" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>Open in new tab</TooltipContent>
                    </Tooltip>
                  </div>

                  {/* Actions */}
                  <div className="flex justify-end gap-2 pt-2 border-t">
                    {ttl && ttl.text !== 'Expired' && canCreate && (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={extendMutation.isPending}
                        onClick={() => {
                          extendMutation.mutate(host.hostname, {
                            onSuccess: (data) => {
                              toast.success(`Extended TTL for ${host.hostname} (${data.ttl_hours}h)`)
                            },
                            onError: (err: any) => {
                              toast.error(err.response?.data?.detail || 'Failed to extend TTL')
                            },
                          })
                        }}
                      >
                        <TimerReset className="mr-2 h-4 w-4" />
                        Extend
                      </Button>
                    )}
                    {canDestroy && (
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => setDestroyHost(host)}
                      >
                        <Trash className="mr-2 h-4 w-4" />
                        Destroy
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      {/* Create Dialog */}
      <Dialog
        open={createOpen}
        onOpenChange={(open) => {
          setCreateOpen(open)
          if (!open) setCreateRegion('')
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create Personal Jump Host</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label>Region</Label>
              <Select
                value={createRegion || config?.default_region || 'mel'}
                onValueChange={setCreateRegion}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select a region" />
                </SelectTrigger>
                <SelectContent>
                  {REGIONS.map((r) => (
                    <SelectItem key={r.value} value={r.value}>
                      {r.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <p className="text-sm text-muted-foreground">
              A web-based terminal will be provisioned in the selected region.
              {config?.default_ttl_hours ? ` It will auto-expire after ${config.default_ttl_hours} hours.` : ''}
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreate} disabled={createMutation.isPending}>
              {createMutation.isPending ? 'Creating...' : 'Create'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Destroy Confirmation */}
      <ConfirmDialog
        open={!!destroyHost}
        onOpenChange={(open) => { if (!open) setDestroyHost(null) }}
        title="Destroy Jump Host"
        description={`This will permanently destroy "${destroyHost?.hostname}" and delete all data on it. This cannot be undone.`}
        confirmLabel="Destroy"
        variant="destructive"
        onConfirm={handleDestroy}
      />
    </div>
  )
}
