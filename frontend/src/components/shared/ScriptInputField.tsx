import { useQuery } from '@tanstack/react-query'
import { Plus, X } from 'lucide-react'
import api from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { ScriptInput } from '@/types'

interface ScriptInputFieldProps {
  input: ScriptInput
  value: any
  onChange: (val: any) => void
  serviceName: string
}

export function ScriptInputField({ input, value, onChange, serviceName }: ScriptInputFieldProps) {
  const isDeploymentType = input.type === 'deployment_id' || input.type === 'deployment_select'
  const { data: deployments = [] } = useQuery({
    queryKey: ['active-deployments'],
    queryFn: async () => {
      const { data } = await api.get('/api/services/active-deployments')
      return (data.deployments || []) as { name: string }[]
    },
    enabled: isDeploymentType,
  })

  const { data: sshKeys = [] } = useQuery({
    queryKey: ['all-ssh-keys'],
    queryFn: async () => {
      const { data } = await api.get('/api/auth/ssh-keys')
      return (data.keys || []) as { user_id: number; username: string; display_name: string; ssh_public_key: string; is_self: boolean }[]
    },
    enabled: input.type === 'ssh_key_select',
  })

  if (input.type === 'ssh_key_select') {
    const selectedKeys = (value as string[]) || []
    return (
      <div className="space-y-2">
        <Label>{input.label || input.name}{input.required ? ' *' : ''}</Label>
        <div className="space-y-2 max-h-48 overflow-auto border rounded-md p-2">
          {sshKeys.length === 0 ? (
            <p className="text-xs text-muted-foreground">No SSH keys available</p>
          ) : (
            sshKeys.map((key) => {
              const keyId = String(key.user_id)
              const isChecked = selectedKeys.includes(keyId)
              return (
                <label key={key.user_id} className="flex items-center gap-2 text-sm cursor-pointer">
                  <Checkbox
                    checked={isChecked}
                    onCheckedChange={(checked) => {
                      if (checked) {
                        onChange([...selectedKeys, keyId])
                      } else {
                        onChange(selectedKeys.filter((k: string) => k !== keyId))
                      }
                    }}
                  />
                  <span>{key.display_name || key.username}</span>
                  <span className="text-muted-foreground text-xs">@{key.username}</span>
                  {key.is_self && (
                    <Badge variant="outline" className="text-[10px] px-1 py-0">you</Badge>
                  )}
                </label>
              )
            })
          )}
        </div>
      </div>
    )
  }

  if (input.type === 'list') {
    const rows = (value as string[]) || ['']
    return (
      <div className="space-y-2">
        <Label>{input.label || input.name}{input.required ? ' *' : ''}</Label>
        <div className="space-y-2">
          {rows.map((row: string, idx: number) => (
            <div key={idx} className="flex gap-2">
              <Input
                value={row}
                onChange={(e) => {
                  const updated = [...rows]
                  updated[idx] = e.target.value
                  onChange(updated)
                }}
                placeholder={input.default || ''}
              />
              {rows.length > 1 && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-9 w-9 shrink-0"
                  onClick={() => onChange(rows.filter((_: string, i: number) => i !== idx))}
                  aria-label={`Remove item ${idx + 1}`}
                >
                  <X className="h-3 w-3" />
                </Button>
              )}
            </div>
          ))}
          <Button
            variant="outline"
            size="sm"
            onClick={() => onChange([...rows, ''])}
          >
            <Plus className="mr-1 h-3 w-3" /> Add
          </Button>
        </div>
      </div>
    )
  }

  if (input.type === 'select' && input.options) {
    return (
      <div className="space-y-2">
        <Label>{input.label || input.name}{input.required ? ' *' : ''}</Label>
        <Select value={value as string} onValueChange={onChange}>
          <SelectTrigger><SelectValue placeholder="Select..." /></SelectTrigger>
          <SelectContent>
            {input.options.map((opt) => (
              <SelectItem key={opt} value={opt}>{opt}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    )
  }

  if (isDeploymentType) {
    return (
      <div className="space-y-2">
        <Label>{input.label || input.name}{input.required ? ' *' : ''}</Label>
        <Select value={value as string} onValueChange={onChange}>
          <SelectTrigger><SelectValue placeholder="Select deployment..." /></SelectTrigger>
          <SelectContent>
            {deployments.map((d: any) => (
              <SelectItem key={d.name} value={d.name}>{d.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <Label>{input.label || input.name}{input.required ? ' *' : ''}</Label>
      <Input
        value={value as string}
        onChange={(e) => onChange(e.target.value)}
        placeholder={input.default || ''}
        required={input.required}
      />
    </div>
  )
}
