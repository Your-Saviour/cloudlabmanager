import { useEffect, useRef } from 'react'
import { useForm, Controller } from 'react-hook-form'
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
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Loader2 } from 'lucide-react'
import { useSubmitBugReport } from '@/hooks/useBugReports'

const MAX_FILE_SIZE = 5 * 1024 * 1024 // 5MB

const schema = z.object({
  title: z.string().min(3, 'Title must be at least 3 characters').max(200, 'Title must be at most 200 characters'),
  steps_to_reproduce: z.string().min(10, 'Please provide at least 10 characters'),
  expected_vs_actual: z.string().min(10, 'Please provide at least 10 characters'),
  severity: z.enum(['low', 'medium', 'high', 'critical']),
  page_url: z.string(),
  screenshot: z
    .instanceof(FileList)
    .optional()
    .refine(
      (files) => !files?.length || files[0].size <= MAX_FILE_SIZE,
      'Screenshot must be under 5MB'
    ),
})

type FormValues = z.infer<typeof schema>

interface ReportBugModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ReportBugModal({ open, onOpenChange }: ReportBugModalProps) {
  const submitMutation = useSubmitBugReport()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      title: '',
      steps_to_reproduce: '',
      expected_vs_actual: '',
      severity: 'medium',
      page_url: typeof window !== 'undefined' ? window.location.pathname : '',
    },
  })

  useEffect(() => {
    if (open) {
      reset({
        title: '',
        steps_to_reproduce: '',
        expected_vs_actual: '',
        severity: 'medium',
        page_url: window.location.pathname,
      })
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }, [open, reset])

  function onSubmit(values: FormValues) {
    const formData = new FormData()
    formData.append('title', values.title)
    formData.append('steps_to_reproduce', values.steps_to_reproduce)
    formData.append('expected_vs_actual', values.expected_vs_actual)
    formData.append('severity', values.severity)
    formData.append('page_url', values.page_url)
    formData.append('browser_info', navigator.userAgent)

    if (values.screenshot?.length) {
      formData.append('screenshot', values.screenshot[0])
    }

    submitMutation.mutate(formData, {
      onSuccess: () => {
        onOpenChange(false)
      },
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Report a Bug</DialogTitle>
          <DialogDescription>
            Help us improve by reporting issues you encounter.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="bug-title">Title</Label>
            <Input id="bug-title" placeholder="Brief description of the issue" {...register('title')} />
            {errors.title && <p className="text-sm text-destructive">{errors.title.message}</p>}
          </div>

          <div className="space-y-2">
            <Label htmlFor="bug-steps">Steps to Reproduce</Label>
            <Textarea
              id="bug-steps"
              placeholder={"1. Go to...\n2. Click on...\n3. Observe..."}
              rows={4}
              {...register('steps_to_reproduce')}
            />
            {errors.steps_to_reproduce && (
              <p className="text-sm text-destructive">{errors.steps_to_reproduce.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="bug-expected">Expected vs Actual Behavior</Label>
            <Textarea
              id="bug-expected"
              placeholder={"Expected: ...\nActual: ..."}
              rows={3}
              {...register('expected_vs_actual')}
            />
            {errors.expected_vs_actual && (
              <p className="text-sm text-destructive">{errors.expected_vs_actual.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="bug-severity">Severity</Label>
            <Controller
              name="severity"
              control={control}
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="bug-severity">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="low">Low</SelectItem>
                    <SelectItem value="medium">Medium</SelectItem>
                    <SelectItem value="high">High</SelectItem>
                    <SelectItem value="critical">Critical</SelectItem>
                  </SelectContent>
                </Select>
              )}
            />
            {errors.severity && <p className="text-sm text-destructive">{errors.severity.message}</p>}
          </div>

          <div className="space-y-2">
            <Label htmlFor="bug-page-url">Page URL</Label>
            <Input id="bug-page-url" {...register('page_url')} />
          </div>

          <div className="space-y-1">
            <Label>Browser Info</Label>
            <p className="text-xs text-muted-foreground break-all">{navigator.userAgent}</p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="bug-screenshot">Screenshot (optional, max 5MB)</Label>
            <Input
              id="bug-screenshot"
              type="file"
              accept="image/*"
              {...register('screenshot')}
              ref={(e) => {
                register('screenshot').ref(e)
                ;(fileInputRef as React.MutableRefObject<HTMLInputElement | null>).current = e
              }}
            />
            {errors.screenshot && (
              <p className="text-sm text-destructive">{errors.screenshot.message as string}</p>
            )}
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitMutation.isPending}>
              {submitMutation.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Submit Bug Report
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
