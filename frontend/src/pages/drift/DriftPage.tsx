import { useState } from 'react'
import { GitCompare, RefreshCw, Loader2, ChevronDown, ChevronRight, AlertTriangle, Clock } from 'lucide-react'
import { toast } from 'sonner'
import { cn, relativeTime, formatDate } from '@/lib/utils'
import { useHasPermission } from '@/lib/permissions'
import { PageHeader } from '@/components/shared/PageHeader'
import { EmptyState } from '@/components/shared/EmptyState'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useDriftSummary,
  useDriftHistory,
  useDriftReport,
  useDriftCheck,
  type DriftInstance,
  type DriftReport,
  type OrphanedInstance,
} from '@/hooks/useDrift'

const statusColors = {
  in_sync: { text: 'text-green-400', bg: 'bg-green-400/10', dot: 'bg-green-400', border: 'border-green-400/30' },
  drifted: { text: 'text-amber-400', bg: 'bg-amber-400/10', dot: 'bg-amber-400', border: 'border-amber-400/30' },
  missing: { text: 'text-red-400', bg: 'bg-red-400/10', dot: 'bg-red-400', border: 'border-red-400/30' },
  orphaned: { text: 'text-orange-400', bg: 'bg-orange-400/10', dot: 'bg-orange-400', border: 'border-orange-400/30' },
  unknown: { text: 'text-gray-400', bg: 'bg-gray-400/10', dot: 'bg-gray-400', border: 'border-gray-400/30' },
} as const

const dnsColors = {
  match: { text: 'text-green-400', bg: 'bg-green-400/10' },
  mismatch: { text: 'text-amber-400', bg: 'bg-amber-400/10' },
  missing: { text: 'text-red-400', bg: 'bg-red-400/10' },
  unknown: { text: 'text-gray-400', bg: 'bg-gray-400/10' },
} as const

export default function DriftPage() {
  const canManage = useHasPermission('drift.manage')
  const { data: summary, isLoading: summaryLoading } = useDriftSummary()
  const { data: history, isLoading: historyLoading } = useDriftHistory(10)
  const driftCheck = useDriftCheck()
  const [selectedReportId, setSelectedReportId] = useState<number | null>(null)
  const [historyExpanded, setHistoryExpanded] = useState(false)

  const latestReport = history?.[0] ?? null
  const activeReport = selectedReportId ? history?.find((r) => r.id === selectedReportId) ?? null : latestReport

  const handleCheck = async () => {
    try {
      await driftCheck.mutateAsync()
      toast.success('Drift check started')
    } catch {
      toast.error('Failed to start drift check')
    }
  }

  const isLoading = summaryLoading || historyLoading

  if (isLoading) {
    return (
      <div>
        <PageHeader title="Drift Detection" description="Compare defined infrastructure with actual state" />
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-20" />)}
          </div>
          <Skeleton className="h-64" />
        </div>
      </div>
    )
  }

  if (!latestReport) {
    return (
      <div>
        <PageHeader title="Drift Detection" description="Compare defined infrastructure with actual state" />
        <Card>
          <CardContent className="py-12">
            <EmptyState
              icon={<GitCompare className="h-12 w-12" />}
              title="No drift reports yet"
              description="Run your first drift check to compare defined infrastructure against actual state."
            >
              {canManage && (
                <Button onClick={handleCheck} disabled={driftCheck.isPending}>
                  {driftCheck.isPending
                    ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    : <GitCompare className="mr-2 h-4 w-4" />}
                  Run First Check
                </Button>
              )}
            </EmptyState>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div>
      <PageHeader title="Drift Detection" description="Compare defined infrastructure with actual state">
        <div className="flex items-center gap-3">
          {summary?.last_checked && (
            <span className="text-xs text-muted-foreground">
              Last checked {relativeTime(summary.last_checked)}
            </span>
          )}
          {canManage && (
            <Button variant="outline" size="sm" onClick={handleCheck} disabled={driftCheck.isPending}>
              {driftCheck.isPending
                ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                : <RefreshCw className="mr-2 h-3.5 w-3.5" />}
              Check Now
            </Button>
          )}
        </div>
      </PageHeader>

      {/* Summary cards */}
      {summary && <SummaryCards summary={summary} />}

      {/* Instance table */}
      {activeReport && (
        <>
          <InstanceTable instances={activeReport.instances} />

          {/* Orphaned instances */}
          {activeReport.orphaned.length > 0 && (
            <OrphanedSection orphaned={activeReport.orphaned} />
          )}
        </>
      )}

      {/* Report history */}
      {history && history.length > 1 && (
        <div className="mt-6">
          <button
            className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors mb-3"
            onClick={() => setHistoryExpanded(!historyExpanded)}
            aria-expanded={historyExpanded}
            aria-label="Toggle report history"
          >
            {historyExpanded
              ? <ChevronDown className="h-4 w-4" aria-hidden="true" />
              : <ChevronRight className="h-4 w-4" aria-hidden="true" />}
            Report History ({history.length})
          </button>
          {historyExpanded && (
            <ReportHistory
              reports={history}
              activeId={activeReport?.id ?? null}
              onSelect={setSelectedReportId}
            />
          )}
        </div>
      )}
    </div>
  )
}

function SummaryCards({ summary }: { summary: { total: number; in_sync: number; drifted: number; missing: number; orphaned: number } }) {
  const cards = [
    { label: 'Total Defined', value: summary.total, color: statusColors.unknown },
    { label: 'In Sync', value: summary.in_sync, color: statusColors.in_sync },
    { label: 'Drifted', value: summary.drifted, color: statusColors.drifted },
    { label: 'Missing', value: summary.missing, color: statusColors.missing },
    { label: 'Orphaned', value: summary.orphaned, color: statusColors.orphaned },
  ]

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
      {cards.map((card) => (
        <Card key={card.label}>
          <CardContent className="py-4 px-4">
            <p className="text-xs text-muted-foreground mb-1">{card.label}</p>
            <p className={cn("text-2xl font-bold", card.value > 0 ? card.color.text : 'text-muted-foreground')}>
              {card.value}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function InstanceTable({ instances }: { instances: DriftInstance[] }) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  if (instances.length === 0) return null

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Instances</CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground border-b">
                <th scope="col" className="pb-2 pr-4 font-medium w-6" />
                <th scope="col" className="pb-2 pr-4 font-medium">Service</th>
                <th scope="col" className="pb-2 pr-4 font-medium">Hostname</th>
                <th scope="col" className="pb-2 pr-4 font-medium">Status</th>
                <th scope="col" className="pb-2 pr-4 font-medium">DNS</th>
                <th scope="col" className="pb-2 pr-4 font-medium">Region</th>
                <th scope="col" className="pb-2 font-medium">Plan</th>
              </tr>
            </thead>
            <tbody>
              {instances.map((inst, i) => (
                <InstanceRow
                  key={`${inst.service}-${inst.hostname}`}
                  instance={inst}
                  expanded={expandedIdx === i}
                  onToggle={() => setExpandedIdx(expandedIdx === i ? null : i)}
                />
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}

function InstanceRow({ instance, expanded, onToggle }: { instance: DriftInstance; expanded: boolean; onToggle: () => void }) {
  const sc = statusColors[instance.status] || statusColors.unknown
  const dnsStatus = instance.dns?.status ?? 'unknown'
  const dc = dnsColors[dnsStatus] || dnsColors.unknown

  return (
    <>
      <tr
        className="border-b last:border-0 cursor-pointer hover:bg-muted/50 transition-colors"
        onClick={onToggle}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle() } }}
        tabIndex={0}
        role="button"
        aria-expanded={expanded}
        aria-label={`${instance.hostname} - ${instance.status.replace('_', ' ')}`}
      >
        <td className="py-2 pr-2">
          {expanded
            ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
            : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />}
        </td>
        <td className="py-2 pr-4 font-medium">{instance.service}</td>
        <td className="py-2 pr-4 font-mono text-xs">{instance.hostname}</td>
        <td className="py-2 pr-4">
          <Badge variant="outline" className={cn(sc.text, sc.border, 'text-xs')}>
            <span className={cn("mr-1.5 inline-block h-2 w-2 rounded-full", sc.dot)} aria-hidden="true" />
            {instance.status.replace('_', ' ')}
          </Badge>
        </td>
        <td className="py-2 pr-4">
          <Badge variant="outline" className={cn(dc.text, 'text-xs')}>
            {dnsStatus}
          </Badge>
        </td>
        <td className="py-2 pr-4 text-muted-foreground">{instance.region}</td>
        <td className="py-2 text-muted-foreground">{instance.plan}</td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={7} className="px-4 py-3 bg-muted/30">
            <InstanceDetail instance={instance} />
          </td>
        </tr>
      )}
    </>
  )
}

function InstanceDetail({ instance }: { instance: DriftInstance }) {
  return (
    <div className="space-y-4">
      {/* Diffs */}
      {instance.diffs.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-muted-foreground mb-2">Configuration Diffs</h4>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted-foreground border-b">
                  <th className="pb-1.5 pr-4 font-medium">Field</th>
                  <th className="pb-1.5 pr-4 font-medium">Expected</th>
                  <th className="pb-1.5 font-medium">Actual</th>
                </tr>
              </thead>
              <tbody>
                {instance.diffs.map((diff) => (
                  <tr key={diff.field} className="border-b last:border-0">
                    <td className="py-1.5 pr-4 font-mono font-medium">{diff.field}</td>
                    <td className="py-1.5 pr-4 text-green-400 font-mono">{String(diff.expected)}</td>
                    <td className="py-1.5 text-red-400 font-mono">{String(diff.actual)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* DNS details */}
      {instance.dns && instance.dns.status !== 'unknown' && (
        <div>
          <h4 className="text-xs font-medium text-muted-foreground mb-2">DNS</h4>
          <div className="flex gap-6 text-xs">
            <div>
              <span className="text-muted-foreground">Expected IP: </span>
              <span className="font-mono">{instance.dns.expected_ip || '—'}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Actual IP: </span>
              <span className={cn(
                "font-mono",
                instance.dns.status === 'mismatch' && 'text-red-400',
                instance.dns.status === 'match' && 'text-green-400',
              )}>
                {instance.dns.actual_ip || '—'}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Expected vs Actual state */}
      {instance.status !== 'missing' && instance.actual && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <h4 className="text-xs font-medium text-muted-foreground mb-2">Expected State</h4>
            <pre className="text-xs font-mono bg-muted/50 rounded p-2 overflow-x-auto max-h-48">
              {JSON.stringify(instance.expected, null, 2)}
            </pre>
          </div>
          <div>
            <h4 className="text-xs font-medium text-muted-foreground mb-2">Actual State</h4>
            <pre className="text-xs font-mono bg-muted/50 rounded p-2 overflow-x-auto max-h-48">
              {JSON.stringify(instance.actual, null, 2)}
            </pre>
          </div>
        </div>
      )}

      {instance.status === 'missing' && (
        <p className="text-xs text-red-400">This instance is defined but not found in the cloud provider.</p>
      )}

      {instance.diffs.length === 0 && instance.status === 'in_sync' && (
        <p className="text-xs text-green-400">All fields match expected configuration.</p>
      )}
    </div>
  )
}

function OrphanedSection({ orphaned }: { orphaned: OrphanedInstance[] }) {
  return (
    <Card className="mt-4 border-orange-400/30">
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-orange-400" />
          Orphaned Instances
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground border-b">
                <th scope="col" className="pb-2 pr-4 font-medium">Hostname</th>
                <th scope="col" className="pb-2 pr-4 font-medium">Vultr ID</th>
                <th scope="col" className="pb-2 pr-4 font-medium">Plan</th>
                <th scope="col" className="pb-2 pr-4 font-medium">Region</th>
                <th scope="col" className="pb-2 font-medium">Tags</th>
              </tr>
            </thead>
            <tbody>
              {orphaned.map((inst) => (
                <tr key={inst.vultr_id} className="border-b last:border-0">
                  <td className="py-2 pr-4 font-mono text-xs text-orange-400">{inst.hostname}</td>
                  <td className="py-2 pr-4 font-mono text-xs text-muted-foreground">{inst.vultr_id}</td>
                  <td className="py-2 pr-4 text-muted-foreground">{inst.plan}</td>
                  <td className="py-2 pr-4 text-muted-foreground">{inst.region}</td>
                  <td className="py-2">
                    <div className="flex gap-1 flex-wrap">
                      {inst.tags.map((tag) => (
                        <Badge key={tag} variant="secondary" className="text-xs">{tag}</Badge>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}

function ReportHistory({ reports, activeId, onSelect }: { reports: DriftReport[]; activeId: number | null; onSelect: (id: number) => void }) {
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground border-b">
                <th scope="col" className="pb-2 pr-4 font-medium">Timestamp</th>
                <th scope="col" className="pb-2 pr-4 font-medium">Status</th>
                <th scope="col" className="pb-2 pr-4 font-medium">In Sync</th>
                <th scope="col" className="pb-2 pr-4 font-medium">Drifted</th>
                <th scope="col" className="pb-2 pr-4 font-medium">Missing</th>
                <th scope="col" className="pb-2 font-medium">Orphaned</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((report) => {
                const isActive = report.id === activeId
                const sc = statusColors[report.status === 'error' ? 'missing' : report.status] || statusColors.unknown
                return (
                  <tr
                    key={report.id}
                    className={cn(
                      "border-b last:border-0 cursor-pointer hover:bg-muted/50 transition-colors",
                      isActive && "bg-muted/30",
                    )}
                    onClick={() => onSelect(report.id)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(report.id) } }}
                    tabIndex={0}
                    role="button"
                    aria-label={`Report from ${report.created_at} - ${report.status}`}
                  >
                    <td className="py-2 pr-4">
                      <div className="flex items-center gap-2">
                        <Clock className="h-3 w-3 text-muted-foreground" />
                        <span className="text-xs">{formatDate(report.created_at)}</span>
                        <span className="text-xs text-muted-foreground">({relativeTime(report.created_at)})</span>
                      </div>
                    </td>
                    <td className="py-2 pr-4">
                      <Badge variant="outline" className={cn(sc.text, sc.border, 'text-xs')}>
                        {report.status}
                      </Badge>
                    </td>
                    <td className="py-2 pr-4 text-green-400">{report.summary.in_sync}</td>
                    <td className="py-2 pr-4 text-amber-400">{report.summary.drifted}</td>
                    <td className="py-2 pr-4 text-red-400">{report.summary.missing}</td>
                    <td className="py-2 text-orange-400">{report.summary.orphaned}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}
