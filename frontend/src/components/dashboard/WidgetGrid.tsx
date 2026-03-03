import { useState, useCallback, useMemo } from 'react'
import { Responsive, WidthProvider } from 'react-grid-layout'
import { Plus, Pencil, Check } from 'lucide-react'
import { usePreferencesStore } from '@/stores/preferencesStore'
import { WIDGET_REGISTRY } from './widgets'
import { WidgetWrapper } from './WidgetWrapper'
import { WidgetCatalogDialog } from './WidgetCatalogDialog'
import { WidgetConfigDialog } from './WidgetConfigDialog'
import { Button } from '@/components/ui/button'
import type { WidgetLayoutItem, WidgetInstance } from '@/types/preferences'

import 'react-grid-layout/css/styles.css'

const ResponsiveGridLayout = WidthProvider(Responsive)

export function WidgetGrid() {
  const dashboard = usePreferencesStore((s) => s.getWidgetDashboard())
  const updateLayouts = usePreferencesStore((s) => s.updateWidgetLayouts)
  const removeWidget = usePreferencesStore((s) => s.removeWidget)

  const [isEditing, setIsEditing] = useState(false)
  const [catalogOpen, setCatalogOpen] = useState(false)
  const [configWidgetId, setConfigWidgetId] = useState<string | null>(null)

  const widgetMap = useMemo(() => {
    const map = new Map<string, WidgetInstance>()
    for (const w of dashboard.widgets) map.set(w.id, w)
    return map
  }, [dashboard.widgets])

  const configWidget = configWidgetId ? widgetMap.get(configWidgetId) : null

  const handleLayoutChange = useCallback(
    (_currentLayout: any, allLayouts: any) => {
      if (!isEditing) return
      // allLayouts contains { lg: [...], md: [...], ... }
      // We only save lg
      if (allLayouts.lg) {
        const cleaned: WidgetLayoutItem[] = allLayouts.lg.map((item: any) => ({
          i: item.i,
          x: item.x,
          y: item.y,
          w: item.w,
          h: item.h,
          minW: item.minW,
          minH: item.minH,
        }))
        updateLayouts({ lg: cleaned })
      }
    },
    [isEditing, updateLayouts]
  )

  const handleRemove = useCallback(
    (widgetId: string) => {
      removeWidget(widgetId)
    },
    [removeWidget]
  )

  const handleConfigure = useCallback((widgetId: string) => {
    setConfigWidgetId(widgetId)
  }, [])

  // Build layout items, attaching min constraints from registry
  const layouts = useMemo(() => {
    const lg = dashboard.layouts.lg.map((item) => {
      const widget = widgetMap.get(item.i)
      const meta = widget ? WIDGET_REGISTRY[widget.type] : null
      return {
        ...item,
        minW: item.minW ?? meta?.defaultSize.minW ?? 2,
        minH: item.minH ?? meta?.defaultSize.minH ?? 2,
        static: !isEditing,
      }
    })
    return { lg }
  }, [dashboard.layouts.lg, widgetMap, isEditing])

  return (
    <div>
      {/* Toolbar */}
      <div className="flex items-center justify-end gap-2 mb-4">
        {isEditing && (
          <Button variant="outline" size="sm" onClick={() => setCatalogOpen(true)}>
            <Plus className="mr-1 h-4 w-4" /> Add Widget
          </Button>
        )}
        <Button
          variant={isEditing ? 'default' : 'outline'}
          size="sm"
          onClick={() => setIsEditing(!isEditing)}
        >
          {isEditing ? (
            <><Check className="mr-1 h-4 w-4" /> Done</>
          ) : (
            <><Pencil className="mr-1 h-4 w-4" /> Edit Dashboard</>
          )}
        </Button>
      </div>

      {/* Grid */}
      <ResponsiveGridLayout
        className="widget-grid"
        layouts={layouts}
        breakpoints={{ lg: 1200, md: 996, sm: 768, xs: 480, xxs: 0 }}
        cols={{ lg: 12, md: 10, sm: 6, xs: 4, xxs: 2 }}
        rowHeight={80}
        isDraggable={isEditing}
        isResizable={isEditing}
        draggableHandle=".widget-drag-handle"
        onLayoutChange={handleLayoutChange}
        compactType="vertical"
        margin={[16, 16]}
      >
        {dashboard.widgets.map((widget) => {
          const meta = WIDGET_REGISTRY[widget.type]
          if (!meta) return null
          const Component = meta.component
          const title = widget.title || meta.label

          return (
            <div key={widget.id}>
              <WidgetWrapper
                title={title}
                widgetId={widget.id}
                onRemove={handleRemove}
                onConfigure={meta.configurable ? handleConfigure : undefined}
                isEditing={isEditing}
              >
                <Component config={widget.config} />
              </WidgetWrapper>
            </div>
          )
        })}
      </ResponsiveGridLayout>

      {/* Catalog Dialog */}
      <WidgetCatalogDialog
        open={catalogOpen}
        onOpenChange={setCatalogOpen}
        existingWidgets={dashboard.widgets}
      />

      {/* Config Dialog */}
      {configWidget && (
        <WidgetConfigDialog
          open={!!configWidgetId}
          onOpenChange={(open) => { if (!open) setConfigWidgetId(null) }}
          widget={configWidget}
        />
      )}
    </div>
  )
}
