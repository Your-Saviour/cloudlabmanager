import { useMemo } from 'react'
import { useVc2Plans, type VultrPlan } from '@/hooks/usePlans'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

function formatRam(mb: number): string {
  if (mb >= 1024) return `${Math.round(mb / 1024)} GB`
  return `${mb} MB`
}

function formatPlanLabel(plan: VultrPlan): string {
  return `${plan.vcpu_count} vCPU, ${formatRam(plan.ram)}, ${plan.disk} GB SSD — $${plan.monthly_cost}/mo`
}

interface PlanSelectorProps {
  value: string
  onChange: (plan: string) => void
  defaultPlan?: string
  minPlan?: string | null
  minMonthlyCost?: number | null
  disabled?: boolean
  label?: string
}

export function PlanSelector({
  value,
  onChange,
  defaultPlan,
  minPlan,
  minMonthlyCost,
  disabled,
  label = 'VM Plan',
}: PlanSelectorProps) {
  const { data: plans = [], isLoading } = useVc2Plans()

  const filteredPlans = useMemo(() => {
    if (!minPlan && !minMonthlyCost) return plans
    // Resolve min cost from plans cache if we have a plan ID but no cost
    let minCost = minMonthlyCost ?? 0
    if (minPlan && !minMonthlyCost) {
      const minPlanData = plans.find((p) => p.id === minPlan)
      if (minPlanData) minCost = minPlanData.monthly_cost
    }
    if (!minCost) return plans
    return plans.filter((p) => p.monthly_cost >= minCost)
  }, [plans, minPlan, minMonthlyCost])

  if (isLoading || plans.length === 0) return null

  if (filteredPlans.length === 0) {
    return (
      <div className="space-y-2">
        <Label>{label}</Label>
        <p className="text-sm text-destructive">No plans meet the minimum requirement.</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <Select value={value} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger aria-label={label}>
          <SelectValue placeholder="Select a plan" />
        </SelectTrigger>
        <SelectContent>
          {filteredPlans.map((plan) => (
            <SelectItem key={plan.id} value={plan.id}>
              {formatPlanLabel(plan)}
              {plan.id === defaultPlan && ' (default)'}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}
