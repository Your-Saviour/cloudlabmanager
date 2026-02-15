import { useMemo, useState } from 'react'
import {
  DndContext,
  closestCenter,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  rectSortingStrategy,
  useSortable,
  arrayMove,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { ExternalLink, GripVertical, Plus, MoreVertical, Pencil, Trash2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { usePreferencesStore } from '@/stores/preferencesStore'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { AddLinkDialog } from './AddLinkDialog'
import type { CustomLink } from '@/types/preferences'

interface QuickLink {
  service: string
  label: string
  url: string
}

interface MergedLink {
  id: string
  label: string
  url: string
  service: string
  isCustom: boolean
}

function isSafeUrl(url: string): boolean {
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}

interface QuickLinksSectionProps {
  quickLinks: QuickLink[]
}

export function QuickLinksSection({ quickLinks }: QuickLinksSectionProps) {
  const savedOrder = usePreferencesStore((s) => s.preferences.quick_links.order)
  const customLinks = usePreferencesStore((s) => s.preferences.quick_links.custom_links)
  const reorderQuickLinks = usePreferencesStore((s) => s.reorderQuickLinks)
  const addCustomLink = usePreferencesStore((s) => s.addCustomLink)
  const removeCustomLink = usePreferencesStore((s) => s.removeCustomLink)
  const editCustomLink = usePreferencesStore((s) => s.editCustomLink)

  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingLink, setEditingLink] = useState<CustomLink | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor)
  )

  // Merge auto-discovered and custom links, then sort by saved order
  const sortedLinks = useMemo(() => {
    const allLinks: MergedLink[] = [
      ...quickLinks.map((l) => ({
        id: `${l.service}:${l.label}`,
        label: l.label,
        url: l.url,
        service: l.service,
        isCustom: false,
      })),
      ...customLinks.map((l) => ({
        id: `custom:${l.id}`,
        label: l.label,
        url: l.url,
        service: 'Custom Link',
        isCustom: true,
      })),
    ]

    const linkMap = new Map(allLinks.map((l) => [l.id, l]))
    const ordered: MergedLink[] = []

    // Add links in saved order
    for (const id of savedOrder) {
      const link = linkMap.get(id)
      if (link) {
        ordered.push(link)
        linkMap.delete(id)
      }
    }

    // Append any new links not in saved order
    for (const link of linkMap.values()) {
      ordered.push(link)
    }

    return ordered
  }, [quickLinks, customLinks, savedOrder])

  const sortedIds = sortedLinks.map((l) => l.id)

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    if (over && active.id !== over.id) {
      const oldIndex = sortedIds.indexOf(active.id as string)
      const newIndex = sortedIds.indexOf(over.id as string)
      reorderQuickLinks(arrayMove(sortedIds, oldIndex, newIndex))
    }
  }

  function handleAddLink(link: CustomLink) {
    if (editingLink) {
      editCustomLink(editingLink.id, { label: link.label, url: link.url })
    } else {
      addCustomLink(link)
    }
    setEditingLink(null)
  }

  function handleEditClick(linkId: string) {
    const customId = linkId.replace('custom:', '')
    const link = customLinks.find((l) => l.id === customId)
    if (link) {
      setEditingLink(link)
      setDialogOpen(true)
    }
  }

  function handleDeleteClick(linkId: string) {
    const customId = linkId.replace('custom:', '')
    removeCustomLink(customId)
  }

  function handleAddClick() {
    setEditingLink(null)
    setDialogOpen(true)
  }

  return (
    <>
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext items={sortedIds} strategy={rectSortingStrategy}>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {sortedLinks.map((link) => (
              <SortableQuickLink
                key={link.id}
                id={link.id}
                link={link}
                onEdit={link.isCustom ? () => handleEditClick(link.id) : undefined}
                onDelete={link.isCustom ? () => handleDeleteClick(link.id) : undefined}
              />
            ))}
            {/* Add Link card */}
            <button
              onClick={handleAddClick}
              className="group block text-left"
            >
              <Card className="border-dashed border-2 transition-colors hover:border-primary/50 h-full">
                <CardContent className="pt-4 pb-4">
                  <div className="flex items-center gap-2">
                    <Plus className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-colors shrink-0" />
                    <p className="text-sm text-muted-foreground group-hover:text-primary transition-colors">
                      Add custom link
                    </p>
                  </div>
                </CardContent>
              </Card>
            </button>
          </div>
        </SortableContext>
      </DndContext>

      <AddLinkDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onSave={handleAddLink}
        editingLink={editingLink}
      />
    </>
  )
}

function SortableQuickLink({
  id,
  link,
  onEdit,
  onDelete,
}: {
  id: string
  link: MergedLink
  onEdit?: () => void
  onDelete?: () => void
}) {
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
    <div ref={setNodeRef} style={style} className={cn('group', isDragging && 'opacity-50 z-50')}>
      <Card
        className={cn(
          'transition-colors hover:border-primary/50 cursor-pointer',
          link.isCustom && 'border-dashed'
        )}
        onClick={() => {
          if (isSafeUrl(link.url)) window.open(link.url, '_blank', 'noopener,noreferrer')
        }}
      >
        <CardContent className="pt-4 pb-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 min-w-0">
              <button
                {...attributes}
                {...listeners}
                className="cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground touch-none shrink-0"
                onClick={(e) => e.stopPropagation()}
                aria-label="Drag to reorder"
              >
                <GripVertical className="h-3.5 w-3.5" />
              </button>
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <p className="text-sm font-medium group-hover:text-primary transition-colors truncate">
                    {link.label}
                  </p>
                  {link.isCustom && (
                    <Badge variant="outline" className="text-[10px] px-1 py-0 leading-tight shrink-0">
                      custom
                    </Badge>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">{link.service}</p>
              </div>
            </div>
            <div className="flex items-center gap-1 shrink-0">
              {(onEdit || onDelete) && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button
                      className="text-muted-foreground hover:text-foreground p-0.5 rounded"
                      onClick={(e) => e.stopPropagation()}
                      aria-label="Link actions"
                    >
                      <MoreVertical className="h-3.5 w-3.5" />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    {onEdit && (
                      <DropdownMenuItem onClick={(e) => { e.stopPropagation(); onEdit() }}>
                        <Pencil className="h-3.5 w-3.5" />
                        Edit
                      </DropdownMenuItem>
                    )}
                    {onDelete && (
                      <DropdownMenuItem
                        className="text-destructive focus:text-destructive"
                        onClick={(e) => { e.stopPropagation(); onDelete() }}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Delete
                      </DropdownMenuItem>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
              <ExternalLink className="h-3.5 w-3.5 text-muted-foreground group-hover:text-primary transition-colors" />
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
