import { useState } from 'react'
import { Play } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { ServiceScript } from '@/types'

interface ScriptRunnerProps {
  scripts: ServiceScript[]
  onRun: (script: ServiceScript) => void
  disabled: boolean
}

export function ScriptRunner({ scripts, onRun, disabled }: ScriptRunnerProps) {
  const [selected, setSelected] = useState(scripts[0]?.name || '')

  if (scripts.length === 1) {
    return (
      <Button
        onClick={() => onRun(scripts[0])}
        disabled={disabled}
      >
        <Play className="mr-1.5 h-3.5 w-3.5" /> {scripts[0].label}
      </Button>
    )
  }

  return (
    <div className="flex">
      <Select value={selected} onValueChange={setSelected}>
        <SelectTrigger className="h-9 text-xs w-36 rounded-r-none border-r-0">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {scripts.map((s) => (
            <SelectItem key={s.name} value={s.name}>{s.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button
        className="rounded-l-none"
        onClick={() => {
          const script = scripts.find((s) => s.name === selected)
          if (script) onRun(script)
        }}
        disabled={disabled}
      >
        <Play className="h-3.5 w-3.5" />
      </Button>
    </div>
  )
}
