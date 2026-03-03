import { GripVertical, X, Settings } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

interface WidgetWrapperProps {
  title: string
  widgetId: string
  children: React.ReactNode
  onRemove: (id: string) => void
  onConfigure?: (id: string) => void
  isEditing: boolean
}

export function WidgetWrapper({
  title,
  widgetId,
  children,
  onRemove,
  onConfigure,
  isEditing,
}: WidgetWrapperProps) {
  return (
    <div className={cn(
      "h-full flex flex-col rounded-lg border bg-card text-card-foreground shadow-sm overflow-hidden",
      isEditing && "ring-1 ring-primary/20"
    )}>
      {/* Title bar */}
      <div className={cn(
        "flex items-center justify-between px-3 py-2 border-b bg-muted/30 shrink-0",
        isEditing && "cursor-default"
      )}>
        <div className="flex items-center gap-2 min-w-0">
          {isEditing && (
            <div className="widget-drag-handle cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground touch-none">
              <GripVertical className="h-4 w-4" />
            </div>
          )}
          <h3 className="text-sm font-medium truncate">{title}</h3>
        </div>
        {isEditing && (
          <div className="flex items-center gap-0.5 shrink-0">
            {onConfigure && (
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-muted-foreground hover:text-foreground"
                onClick={() => onConfigure(widgetId)}
                title="Configure widget"
              >
                <Settings className="h-3.5 w-3.5" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 text-muted-foreground hover:text-destructive"
              onClick={() => onRemove(widgetId)}
              title="Remove widget"
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        )}
      </div>
      {/* Widget content */}
      <div className="flex-1 overflow-auto p-3">
        {children}
      </div>
    </div>
  )
}
