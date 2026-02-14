import { useMutation } from '@tanstack/react-query'
import {
  CircleCheck,
  AlertTriangle,
  CircleX,
  DollarSign,
  Globe,
  Key,
  ShieldCheck,
} from 'lucide-react'
import api from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import type { DryRunResult, DryRunValidation } from '@/types'

interface DryRunPreviewProps {
  serviceName: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: () => void
}

function StatusIcon({ status }: { status: 'pass' | 'warn' | 'fail' }) {
  if (status === 'pass') return <CircleCheck className="h-4 w-4 text-emerald-500 shrink-0" aria-hidden="true" />
  if (status === 'warn') return <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0" aria-hidden="true" />
  return <CircleX className="h-4 w-4 text-red-500 shrink-0" aria-hidden="true" />
}

function StatusBadge({ status }: { status: 'pass' | 'warn' | 'fail' }) {
  const variants: Record<string, string> = {
    pass: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20',
    warn: 'bg-amber-500/10 text-amber-500 border-amber-500/20',
    fail: 'bg-red-500/10 text-red-500 border-red-500/20',
  }
  return (
    <Badge variant="outline" className={variants[status]}>
      {status === 'pass' ? 'Ready' : status === 'warn' ? 'Warnings' : 'Failed'}
    </Badge>
  )
}

export function DryRunPreview({ serviceName, open, onOpenChange, onConfirm }: DryRunPreviewProps) {
  const {
    data,
    mutate: runDryRun,
    isPending,
    isError,
    error,
  } = useMutation({
    mutationFn: async () => {
      const { data } = await api.post(`/api/services/${serviceName}/dry-run`)
      return data as DryRunResult
    },
  })

  // Trigger dry run when modal opens
  const handleOpenChange = (nextOpen: boolean) => {
    if (nextOpen) {
      runDryRun()
    }
    onOpenChange(nextOpen)
  }

  const hasFailure = data?.validations?.some((v: DryRunValidation) => v.status === 'fail')
  const hasWarning = data?.validations?.some((v: DryRunValidation) => v.status === 'warn')

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-3">
            Deploy {serviceName}
            {data && <StatusBadge status={data.status} />}
          </DialogTitle>
          <DialogDescription>
            Review the deployment plan before proceeding
          </DialogDescription>
        </DialogHeader>

        <div className="overflow-y-auto flex-1 -mx-6 px-6">
        {isPending ? (
          <div className="space-y-4">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-32 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        ) : isError ? (
          <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-4" role="alert">
            <p className="text-sm text-red-400">
              {(error as any)?.response?.data?.detail || 'Failed to run dry-run check'}
            </p>
          </div>
        ) : data ? (
          <div className="space-y-4">
            {/* Cost Estimate & Instances */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm flex items-center gap-2">
                  <DollarSign className="h-4 w-4" aria-hidden="true" /> Cost Estimate
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="mb-4">
                  <p className="text-sm text-muted-foreground">Monthly Total</p>
                  <p className="text-3xl font-bold">
                    ${data.cost_estimate.total_monthly_cost.toFixed(2)}
                  </p>
                </div>
                {data.cost_estimate.instances.length > 0 && (
                  <div className="space-y-2">
                    {data.cost_estimate.instances.map((inst, i) => (
                      <div key={i} className="flex items-center justify-between px-3 py-2 rounded-md bg-muted/20">
                        <div>
                          <p className="text-sm font-medium">{inst.hostname}</p>
                          <p className="text-xs text-muted-foreground">
                            {inst.plan} &middot; {inst.region} &middot; {inst.os}
                          </p>
                        </div>
                        <span className="font-mono text-sm">${inst.monthly_cost.toFixed(2)}/mo</span>
                      </div>
                    ))}
                  </div>
                )}
                {!data.cost_estimate.plans_cache_available && (
                  <p className="text-xs text-amber-400 mt-2">
                    Plans cache unavailable — costs are estimated from instance definitions
                  </p>
                )}
              </CardContent>
            </Card>

            {/* DNS Records */}
            {data.dns_records.length > 0 && (
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Globe className="h-4 w-4" aria-hidden="true" /> DNS Records
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    {data.dns_records.map((rec, i) => (
                      <div key={i} className="px-3 py-2 rounded-md bg-muted/20">
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className="text-[10px]">{rec.type}</Badge>
                          <span className="text-sm font-mono">{rec.fqdn}</span>
                        </div>
                        {rec.note && (
                          <p className="text-xs text-muted-foreground mt-1">{rec.note}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}

            {/* SSH Keys */}
            {data.ssh_keys && (
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Key className="h-4 w-4" aria-hidden="true" /> SSH Keys
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="px-3 py-2 rounded-md bg-muted/20">
                    <p className="text-sm">
                      <span className="text-muted-foreground">Type:</span> {data.ssh_keys.key_type}
                    </p>
                    <p className="text-sm">
                      <span className="text-muted-foreground">Name:</span> {data.ssh_keys.key_name}
                    </p>
                    <p className="text-xs font-mono">
                      <span className="text-muted-foreground">Location:</span> {data.ssh_keys.key_location}
                    </p>
                    {data.ssh_keys.note && (
                      <p className="text-xs text-amber-400 mt-1">{data.ssh_keys.note}</p>
                    )}
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Validation Results */}
            {data.validations.length > 0 && (
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <ShieldCheck className="h-4 w-4" aria-hidden="true" /> Validation Checks
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    {data.validations.map((v, i) => (
                      <div key={i} className="flex items-start gap-3 px-3 py-2 rounded-md bg-muted/20">
                        <StatusIcon status={v.status} />
                        <div>
                          <p className="text-sm font-medium">{v.check}</p>
                          <p className="text-xs text-muted-foreground">{v.message}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        ) : null}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={onConfirm}
            disabled={isPending || isError || hasFailure}
            variant={hasWarning ? 'destructive' : 'default'}
          >
            Deploy
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
