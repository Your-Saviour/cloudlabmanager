import { useState, useEffect } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import type { DeployStage } from '@/types'
import { PlanSelector } from '@/components/shared/PlanSelector'

interface StageSelectModalProps {
  serviceName: string
  stages: DeployStage[]
  open: boolean
  onOpenChange: (open: boolean) => void
  onContinue: (selectedStages: Record<string, boolean>, plan?: string) => void
  showPlanSelector?: boolean
  defaultPlan?: string
  minPlan?: string | null
  minPlanMonthlyCost?: number | null
}

export function StageSelectModal({
  serviceName,
  stages,
  open,
  onOpenChange,
  onContinue,
  showPlanSelector,
  defaultPlan,
  minPlan,
  minPlanMonthlyCost,
}: StageSelectModalProps) {
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [selectedPlan, setSelectedPlan] = useState(defaultPlan || '')

  // Initialize from stage defaults when modal opens or stages change
  useEffect(() => {
    if (open) {
      const initial: Record<string, boolean> = {}
      for (const stage of stages) {
        initial[stage.id] = stage.default
      }
      setSelected(initial)
      setSelectedPlan(defaultPlan || '')
    }
  }, [open, stages, defaultPlan])

  const handleToggle = (stageId: string, checked: boolean) => {
    setSelected((prev) => {
      const next = { ...prev, [stageId]: checked }

      // Smart coupling: disabling provision auto-disables wait_boot
      if (stageId === 'provision' && !checked) {
        if ('wait_boot' in next) {
          next.wait_boot = false
        }
      }

      // Smart coupling: re-enabling provision auto-enables wait_boot
      if (stageId === 'provision' && checked) {
        if ('wait_boot' in next) {
          next.wait_boot = true
        }
      }

      return next
    })
  }

  const provisionDisabled = stages.some((s) => s.id === 'provision') && !selected.provision

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Deploy {serviceName}</DialogTitle>
          <DialogDescription>
            {stages.length > 0 ? 'Select which stages to run' : 'Configure deployment options'}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2">
          {showPlanSelector && (
            <PlanSelector
              value={selectedPlan}
              onChange={setSelectedPlan}
              defaultPlan={defaultPlan}
              minPlan={minPlan}
              minMonthlyCost={minPlanMonthlyCost}
              disabled={provisionDisabled}
            />
          )}

          {stages.map((stage) => (
            <div
              key={stage.id}
              className="flex items-center justify-between px-3 py-2 rounded-md bg-muted/20"
            >
              <label
                htmlFor={`stage-${stage.id}`}
                className="text-sm font-medium cursor-pointer select-none"
              >
                {stage.label}
              </label>
              <Switch
                id={`stage-${stage.id}`}
                checked={selected[stage.id] ?? stage.default}
                onCheckedChange={(checked) => handleToggle(stage.id, checked)}
              />
            </div>
          ))}
        </div>

        {provisionDisabled && (
          <div className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2">
            <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" aria-hidden="true" />
            <p className="text-xs text-amber-400">
              Provisioning skipped — will use existing inventory
            </p>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => {
              const plan = selectedPlan && selectedPlan !== defaultPlan ? selectedPlan : undefined
              onContinue(selected, plan)
            }}
          >
            Continue
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
