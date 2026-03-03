import { Plus } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useHasPermission } from '@/lib/permissions'
import { usePreferencesStore } from '@/stores/preferencesStore'
import { WIDGET_REGISTRY, type WidgetMeta } from './widgets'
import type { WidgetInstance, WidgetLayoutItem } from '@/types/preferences'

interface WidgetCatalogDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  existingWidgets: WidgetInstance[]
}

export function WidgetCatalogDialog({ open, onOpenChange, existingWidgets }: WidgetCatalogDialogProps) {
  const addWidget = usePreferencesStore((s) => s.addWidget)

  // Check all permissions upfront
  const canDeploy = useHasPermission('services.deploy')
  const canViewFiles = useHasPermission('files.view')

  const permissionMap: Record<string, boolean> = {
    'services.deploy': canDeploy,
    'files.view': canViewFiles,
  }

  const existingTypes = new Set(existingWidgets.map((w) => w.type))

  function handleAdd(meta: WidgetMeta) {
    const id = meta.singleton
      ? `${meta.type}_default`
      : `${meta.type}_${Date.now()}`

    const widget: WidgetInstance = { id, type: meta.type, config: {} }

    // Find max Y to place widget at bottom
    const dashboard = usePreferencesStore.getState().getWidgetDashboard()
    const maxY = dashboard.layouts.lg.reduce((max, item) => Math.max(max, item.y + item.h), 0)

    const layout: WidgetLayoutItem = {
      i: id,
      x: 0,
      y: maxY,
      w: meta.defaultSize.w,
      h: meta.defaultSize.h,
      minW: meta.defaultSize.minW,
      minH: meta.defaultSize.minH,
    }

    addWidget(widget, layout)

    // Close dialog for singletons (only one to add), keep open for multi-instance
    if (meta.singleton) onOpenChange(false)
  }

  const entries = Object.values(WIDGET_REGISTRY).filter((meta) => {
    // Hide widgets the user lacks permissions for
    if (meta.requiredPermission && !permissionMap[meta.requiredPermission]) return false
    return true
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add Widget</DialogTitle>
          <DialogDescription>Choose a widget to add to your dashboard.</DialogDescription>
        </DialogHeader>

        <div className="space-y-3 max-h-[60vh] overflow-y-auto">
          {entries.map((meta) => {
            const alreadyAdded = meta.singleton && existingTypes.has(meta.type)
            return (
              <Card key={meta.type} className={alreadyAdded ? 'opacity-50' : ''}>
                <CardContent className="pt-4 pb-4">
                  <div className="flex items-center justify-between">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="font-medium text-sm">{meta.label}</p>
                        {meta.singleton && <Badge variant="outline" className="text-[10px]">Single</Badge>}
                        {meta.configurable && <Badge variant="outline" className="text-[10px]">Configurable</Badge>}
                      </div>
                      <p className="text-xs text-muted-foreground mt-0.5">{meta.description}</p>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={alreadyAdded}
                      onClick={() => handleAdd(meta)}
                    >
                      <Plus className="mr-1 h-3 w-3" />
                      {alreadyAdded ? 'Added' : 'Add'}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      </DialogContent>
    </Dialog>
  )
}
