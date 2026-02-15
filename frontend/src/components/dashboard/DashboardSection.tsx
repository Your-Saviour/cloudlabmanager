import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { GripVertical, ChevronDown, ChevronUp } from 'lucide-react'
import { usePreferencesStore } from '@/stores/preferencesStore'
import { cn } from '@/lib/utils'

interface DashboardSectionProps {
  id: string
  title: string
  icon?: React.ReactNode
  action?: React.ReactNode
  children: React.ReactNode
  sortable?: boolean
}

export function DashboardSection({ id, title, icon, action, children, sortable = true }: DashboardSectionProps) {
  const isCollapsed = usePreferencesStore((s) => s.isSectionCollapsed(id))
  const toggleCollapsed = usePreferencesStore((s) => s.toggleSectionCollapsed)

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn("mb-8", isDragging && "opacity-50 z-50")}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {sortable && (
            <button
              {...attributes}
              {...listeners}
              className="cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground touch-none"
              aria-label="Drag to reorder"
            >
              <GripVertical className="h-4 w-4" />
            </button>
          )}

          <button
            className="flex items-center gap-2 group cursor-pointer"
            onClick={() => toggleCollapsed(id)}
            aria-expanded={!isCollapsed}
            aria-label={`${isCollapsed ? 'Expand' : 'Collapse'} ${title}`}
          >
            {icon}
            <h2 className="text-base font-semibold">{title}</h2>
            {isCollapsed ? (
              <ChevronDown className="h-4 w-4 text-muted-foreground group-hover:text-foreground transition-colors" />
            ) : (
              <ChevronUp className="h-4 w-4 text-muted-foreground group-hover:text-foreground transition-colors" />
            )}
          </button>
        </div>
        {!isCollapsed && action}
      </div>
      {!isCollapsed && children}
    </div>
  )
}
