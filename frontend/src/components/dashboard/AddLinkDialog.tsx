import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ExternalLink } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import type { CustomLink } from '@/types/preferences'

const schema = z.object({
  label: z.string().min(1, 'Label is required').max(50),
  url: z.string().url('Must be a valid URL'),
})

type FormValues = z.infer<typeof schema>

interface AddLinkDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSave: (link: CustomLink) => void
  editingLink?: CustomLink | null
}

export function AddLinkDialog({ open, onOpenChange, onSave, editingLink }: AddLinkDialogProps) {
  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { label: '', url: '' },
  })

  useEffect(() => {
    if (open) {
      reset(editingLink ? { label: editingLink.label, url: editingLink.url } : { label: '', url: '' })
    }
  }, [open, editingLink, reset])

  const watchLabel = watch('label')
  const watchUrl = watch('url')

  function onSubmit(values: FormValues) {
    onSave({
      id: editingLink?.id ?? Date.now().toString(),
      label: values.label,
      url: values.url,
    })
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{editingLink ? 'Edit Custom Link' : 'Add Custom Link'}</DialogTitle>
          <DialogDescription>
            Add a link to an external tool or resource.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="label">Label</Label>
            <Input id="label" placeholder="e.g. Grafana Dashboard" {...register('label')} />
            {errors.label && <p className="text-sm text-destructive">{errors.label.message}</p>}
          </div>

          <div className="space-y-2">
            <Label htmlFor="url">URL</Label>
            <Input id="url" placeholder="https://example.com" {...register('url')} />
            {errors.url && <p className="text-sm text-destructive">{errors.url.message}</p>}
          </div>

          {watchLabel && watchUrl && (
            <div className="space-y-2">
              <Label className="text-muted-foreground">Preview</Label>
              <Card className="transition-colors hover:border-primary/50">
                <CardContent className="pt-4 pb-4">
                  <div className="flex items-center justify-between">
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate">{watchLabel}</p>
                      <p className="text-xs text-muted-foreground">Custom Link</p>
                    </div>
                    <ExternalLink className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit">
              {editingLink ? 'Save Changes' : 'Add Link'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
