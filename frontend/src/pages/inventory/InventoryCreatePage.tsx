import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import api from '@/lib/api'
import { useInventoryStore } from '@/stores/inventoryStore'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { toast } from 'sonner'
import type { InventoryField } from '@/types'

export default function InventoryCreatePage() {
  const { typeSlug } = useParams<{ typeSlug: string }>()
  const navigate = useNavigate()
  const types = useInventoryStore((s) => s.types)
  const typeConfig = types.find((t) => t.slug === typeSlug)

  const [name, setName] = useState('')
  const [formData, setFormData] = useState<Record<string, unknown>>(() => {
    const defaults: Record<string, unknown> = {}
    typeConfig?.fields.forEach((f) => {
      if (f.default !== undefined) defaults[f.name] = f.default
    })
    return defaults
  })

  const createMutation = useMutation({
    mutationFn: (body: { name: string; data: Record<string, unknown> }) =>
      api.post(`/api/inventory/${typeSlug}`, body),
    onSuccess: (res) => {
      toast.success('Created successfully')
      const id = res.data.id || res.data.object?.id
      if (id) navigate(`/inventory/${typeSlug}/${id}`)
      else navigate(`/inventory/${typeSlug}`)
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Create failed'),
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    createMutation.mutate({ name, data: formData })
  }

  const updateField = (fieldName: string, value: unknown) => {
    setFormData({ ...formData, [fieldName]: value })
  }

  if (!typeConfig) return <div className="text-muted-foreground">Type not found</div>

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <Button variant="ghost" size="icon" onClick={() => navigate(`/inventory/${typeSlug}`)}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Create {typeConfig.label}</h1>
          <p className="text-sm text-muted-foreground">Add a new {typeConfig.label.toLowerCase()}</p>
        </div>
      </div>

      <Card>
        <CardContent className="pt-6">
          <form onSubmit={handleSubmit} className="space-y-4 max-w-lg">
            <div className="space-y-2">
              <Label>Name *</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
            </div>

            {typeConfig.fields.map((field) => {
              if (field.readonly) return null
              return (
                <div key={field.name} className="space-y-2">
                  <Label>{field.label || field.name}{field.required ? ' *' : ''}</Label>
                  {field.type === 'enum' && field.options ? (
                    <Select value={String(formData[field.name] || '')} onValueChange={(v) => updateField(field.name, v)}>
                      <SelectTrigger><SelectValue placeholder="Select..." /></SelectTrigger>
                      <SelectContent>
                        {field.options.map((opt) => (
                          <SelectItem key={opt} value={opt}>{opt}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : field.type === 'text' || field.type === 'json' ? (
                    <Textarea
                      value={String(formData[field.name] || '')}
                      onChange={(e) => updateField(field.name, e.target.value)}
                      rows={4}
                      className="font-mono text-xs"
                      required={field.required}
                    />
                  ) : field.type === 'boolean' ? (
                    <Select value={String(!!formData[field.name])} onValueChange={(v) => updateField(field.name, v === 'true')}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="true">Yes</SelectItem>
                        <SelectItem value="false">No</SelectItem>
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input
                      type={field.type === 'number' ? 'number' : field.type === 'secret' ? 'password' : 'text'}
                      value={String(formData[field.name] || '')}
                      onChange={(e) => updateField(field.name, field.type === 'number' ? Number(e.target.value) : e.target.value)}
                      required={field.required}
                    />
                  )}
                </div>
              )
            })}

            <div className="flex gap-2 pt-2">
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending ? 'Creating...' : 'Create'}
              </Button>
              <Button type="button" variant="outline" onClick={() => navigate(`/inventory/${typeSlug}`)}>
                Cancel
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
