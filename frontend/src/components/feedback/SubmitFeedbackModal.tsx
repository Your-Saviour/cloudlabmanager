import { useEffect, useRef } from 'react'
import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Upload, Loader2 } from 'lucide-react'
import api from '@/lib/api'
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
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { toast } from 'sonner'

const MAX_FILE_SIZE = 5 * 1024 * 1024 // 5MB

const schema = z.object({
  title: z
    .string()
    .min(1, 'Title is required')
    .max(200, 'Title must be at most 200 characters'),
  description: z.string().min(1, 'Description is required'),
  priority: z.enum(['low', 'medium', 'high']),
  screenshot: z
    .instanceof(FileList)
    .optional()
    .refine(
      (files) => !files?.length || files[0].size <= MAX_FILE_SIZE,
      'Screenshot must be under 5MB'
    ),
})

type FormValues = z.infer<typeof schema>

interface Props {
  open: boolean
  onClose: () => void
  type: 'feature_request' | 'bug_report'
}

export function SubmitFeedbackModal({ open, onClose, type }: Props) {
  const queryClient = useQueryClient()
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
      description: '',
      priority: 'medium',
    },
  })

  useEffect(() => {
    if (open) {
      reset({ title: '', description: '', priority: 'medium' })
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }, [open, reset])

  const submitMutation = useMutation({
    mutationFn: async (values: FormValues) => {
      const res = await api.post('/api/feedback', {
        type,
        title: values.title,
        description: values.description,
        priority: values.priority,
      })
      const feedbackId = res.data.id

      if (values.screenshot?.length) {
        const formData = new FormData()
        formData.append('file', values.screenshot[0])
        await api.post(`/api/feedback/${feedbackId}/screenshot`, formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
      }

      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['feedback'] })
      toast.success(
        type === 'feature_request'
          ? 'Feature request submitted!'
          : 'Bug report submitted!'
      )
      onClose()
    },
    onError: () => {
      toast.error('Failed to submit feedback. Please try again.')
    },
  })

  function onSubmit(values: FormValues) {
    submitMutation.mutate(values)
  }

  const isFeature = type === 'feature_request'

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {isFeature ? 'Request a Feature' : 'Report a Bug'}
          </DialogTitle>
          <DialogDescription>
            {isFeature
              ? 'Suggest a new feature or improvement.'
              : 'Help us improve by reporting issues you encounter.'}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="feedback-title">Title</Label>
            <Input
              id="feedback-title"
              maxLength={200}
              placeholder="Brief summary..."
              {...register('title')}
            />
            {errors.title && (
              <p className="text-sm text-destructive">{errors.title.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="feedback-description">Description</Label>
            <Textarea
              id="feedback-description"
              rows={6}
              placeholder={
                isFeature
                  ? 'Describe the feature you would like to see and the use case...'
                  : 'Steps to reproduce, expected vs actual behavior...'
              }
              {...register('description')}
            />
            {errors.description && (
              <p className="text-sm text-destructive">
                {errors.description.message}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="feedback-priority">Priority</Label>
            <Controller
              name="priority"
              control={control}
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="feedback-priority">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="low">Low</SelectItem>
                    <SelectItem value="medium">Medium</SelectItem>
                    <SelectItem value="high">High</SelectItem>
                  </SelectContent>
                </Select>
              )}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="feedback-screenshot">
              Screenshot (optional, max 5MB)
            </Label>
            <Input
              id="feedback-screenshot"
              type="file"
              accept="image/png,image/jpeg,image/gif,image/webp"
              {...register('screenshot')}
              ref={(e) => {
                register('screenshot').ref(e)
                ;(
                  fileInputRef as React.MutableRefObject<HTMLInputElement | null>
                ).current = e
              }}
            />
            {errors.screenshot && (
              <p className="text-sm text-destructive">
                {errors.screenshot.message as string}
              </p>
            )}
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitMutation.isPending}>
              {submitMutation.isPending && (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              )}
              {isFeature ? 'Submit Feature Request' : 'Submit Bug Report'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
