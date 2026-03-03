import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { usePreferencesStore } from '@/stores/preferencesStore'
import api from '@/lib/api'
import type { WidgetInstance } from '@/types/preferences'

interface WidgetConfigDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  widget: WidgetInstance
}

export function WidgetConfigDialog({ open, onOpenChange, widget }: WidgetConfigDialogProps) {
  const updateWidgetConfig = usePreferencesStore((s) => s.updateWidgetConfig)
  const updateWidgetTitle = usePreferencesStore((s) => s.updateWidgetTitle)

  const [title, setTitle] = useState(widget.title || '')
  const [serviceName, setServiceName] = useState(widget.config.serviceName || '')
  const [scriptName, setScriptName] = useState(widget.config.scriptName || '')

  useEffect(() => {
    if (open) {
      setTitle(widget.title || '')
      setServiceName(widget.config.serviceName || '')
      setScriptName(widget.config.scriptName || '')
    }
  }, [open, widget])

  const { data: servicesData = [] } = useQuery({
    queryKey: ['services'],
    queryFn: async () => {
      const { data } = await api.get('/api/services')
      return data.services || []
    },
  })

  const selectedService = servicesData.find((s: any) => s.name === serviceName)
  const scripts = selectedService?.scripts || []

  function handleSave() {
    if (title) updateWidgetTitle(widget.id, title)

    const config: Record<string, any> = {}
    if (widget.type === 'service_toggle') {
      config.serviceName = serviceName
    } else if (widget.type === 'script_runner') {
      config.serviceName = serviceName
      config.scriptName = scriptName
    }
    updateWidgetConfig(widget.id, config)
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Configure Widget</DialogTitle>
          <DialogDescription>Customize this widget's settings.</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="widget-title">Title (optional)</Label>
            <Input
              id="widget-title"
              placeholder="Custom title..."
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>

          {(widget.type === 'service_toggle' || widget.type === 'script_runner') && (
            <div className="space-y-2">
              <Label>Service</Label>
              <Select value={serviceName} onValueChange={(v) => { setServiceName(v); setScriptName('') }}>
                <SelectTrigger>
                  <SelectValue placeholder="Select a service..." />
                </SelectTrigger>
                <SelectContent>
                  {servicesData.map((svc: any) => (
                    <SelectItem key={svc.name} value={svc.name}>{svc.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {widget.type === 'script_runner' && serviceName && (
            <div className="space-y-2">
              <Label>Script</Label>
              <Select value={scriptName} onValueChange={setScriptName}>
                <SelectTrigger>
                  <SelectValue placeholder="Select a script..." />
                </SelectTrigger>
                <SelectContent>
                  {scripts.map((s: any) => (
                    <SelectItem key={s.name} value={s.name}>{s.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleSave}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
