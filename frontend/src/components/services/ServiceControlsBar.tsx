import { Search, LayoutGrid, List } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

export type StatusFilter = 'all' | 'running' | 'stopped'
export type GroupBy = 'none' | 'tag' | 'region'
export type ViewMode = 'grid' | 'list'

interface ServiceControlsBarProps {
  search: string
  onSearchChange: (value: string) => void
  statusFilter: StatusFilter
  onStatusFilterChange: (value: StatusFilter) => void
  groupBy: GroupBy
  onGroupByChange: (value: GroupBy) => void
  viewMode: ViewMode
  onViewModeChange: (value: ViewMode) => void
}

export function ServiceControlsBar({
  search,
  onSearchChange,
  statusFilter,
  onStatusFilterChange,
  groupBy,
  onGroupByChange,
  viewMode,
  onViewModeChange,
}: ServiceControlsBarProps) {
  return (
    <div className="flex items-center gap-3 mb-6">
      <div className="relative flex-1 max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search services..."
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          className="pl-9"
          aria-label="Search services"
        />
      </div>

      <Select value={statusFilter} onValueChange={(v) => onStatusFilterChange(v as StatusFilter)}>
        <SelectTrigger className="w-32">
          <SelectValue placeholder="Status" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All</SelectItem>
          <SelectItem value="running">Running</SelectItem>
          <SelectItem value="stopped">Stopped</SelectItem>
        </SelectContent>
      </Select>

      <Select value={groupBy} onValueChange={(v) => onGroupByChange(v as GroupBy)}>
        <SelectTrigger className="w-40">
          <SelectValue placeholder="Group by..." />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="none">No grouping</SelectItem>
          <SelectItem value="tag">Group by tag</SelectItem>
          <SelectItem value="region">Group by region</SelectItem>
        </SelectContent>
      </Select>

      <div className="flex items-center border border-border rounded-md">
        <Button
          variant="ghost"
          size="icon"
          className={cn('h-9 w-9 rounded-r-none', viewMode === 'grid' && 'bg-muted')}
          onClick={() => onViewModeChange('grid')}
          aria-label="Grid view"
          aria-pressed={viewMode === 'grid'}
        >
          <LayoutGrid className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className={cn('h-9 w-9 rounded-l-none', viewMode === 'list' && 'bg-muted')}
          onClick={() => onViewModeChange('list')}
          aria-label="List view"
          aria-pressed={viewMode === 'list'}
        >
          <List className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}
