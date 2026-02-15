import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface BulkAction {
  label: string
  icon?: React.ReactNode
  variant?: 'default' | 'destructive' | 'outline'
  onClick: () => void
  disabled?: boolean
}

interface BulkActionBarProps {
  selectedCount: number
  onClear: () => void
  actions: BulkAction[]
  itemLabel?: string
}

export function BulkActionBar({ selectedCount, onClear, actions, itemLabel = 'items' }: BulkActionBarProps) {
  if (selectedCount === 0) return null

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40
                    bg-card border border-border shadow-2xl rounded-xl
                    px-5 py-3 flex items-center gap-4
                    animate-slide-up">
      <span className="text-sm font-medium whitespace-nowrap">
        {selectedCount} {selectedCount === 1 ? itemLabel.replace(/s$/, '') : itemLabel} selected
      </span>

      <div className="h-6 w-px bg-border" />

      <div className="flex items-center gap-2">
        {actions.map((action, i) => (
          <Button
            key={i}
            size="sm"
            variant={action.variant || 'default'}
            onClick={action.onClick}
            disabled={action.disabled}
          >
            {action.icon && <span className="mr-1.5">{action.icon}</span>}
            {action.label}
          </Button>
        ))}
      </div>

      <Button variant="ghost" size="icon" className="h-7 w-7 ml-1" onClick={onClear} aria-label="Clear selection">
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
  )
}
