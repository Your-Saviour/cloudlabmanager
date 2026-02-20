import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Plus, X, Upload, Library, Search } from 'lucide-react'
import api from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import type { ScriptInput } from '@/types'

export interface LibraryFileRef {
  _libraryFileId: number
  _libraryFileName: string
  _libraryFilePath: string
}

export function isLibraryFileRef(v: any): v is LibraryFileRef {
  return v && typeof v === 'object' && '_libraryFileId' in v
}

interface LibraryFile {
  id: number
  filename: string
  original_name: string
  size_bytes: number
  uploaded_at: string
}

interface ScriptInputFieldProps {
  input: ScriptInput
  value: any
  onChange: (val: any) => void
  serviceName: string
}

export function ScriptInputField({ input, value, onChange, serviceName }: ScriptInputFieldProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [isDragging, setIsDragging] = useState(false)

  // Path history state — must be called unconditionally (Rules of Hooks)
  const isPathInput = typeof input.default === 'string' && input.default.includes('/')
  const pathHistoryKey = `clm_path_history_${serviceName}`
  const [pathSuggestions, setPathSuggestions] = useState<string[]>([])

  useEffect(() => {
    if (!isPathInput) return
    try {
      const history = JSON.parse(localStorage.getItem(pathHistoryKey) || '[]')
      const suggestions = [...new Set([input.default, ...history].filter(Boolean))]
      setPathSuggestions(suggestions.slice(0, 6))
    } catch { setPathSuggestions([]) }
  }, [pathHistoryKey, input.default, isPathInput])

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

  if (input.type === 'multi_file') {
    const files: Array<File | LibraryFileRef> = Array.isArray(value) ? value : []
    const totalSize = files.reduce((sum, f) => {
      if (f instanceof File) return sum + f.size
      return sum
    }, 0)

    const removeFile = (idx: number) => {
      onChange(files.filter((_, i) => i !== idx))
    }

    const addFiles = (newFiles: File[]) => {
      onChange([...files, ...newFiles])
    }

    const addLibraryFile = (ref: LibraryFileRef) => {
      // Prevent duplicate library files
      if (files.some((f) => isLibraryFileRef(f) && f._libraryFileId === ref._libraryFileId)) return
      onChange([...files, ref])
    }

    return (
      <div className="space-y-2">
        <Label>{input.label || input.name}{input.required ? ' *' : ''}</Label>
        {input.description && (
          <p className="text-xs text-muted-foreground">{input.description}</p>
        )}
        <MultiFileInputTabs
          onAddFiles={addFiles}
          onAddLibraryFile={addLibraryFile}
        />
        {files.length > 0 && (
          <div className="border rounded-lg divide-y">
            {files.map((f, idx) => (
              <div key={idx} className="flex items-center justify-between px-3 py-2">
                <div className="flex items-center gap-2 min-w-0">
                  {isLibraryFileRef(f) ? (
                    <>
                      <Library className="h-4 w-4 text-muted-foreground shrink-0" />
                      <span className="text-sm font-medium truncate">{f._libraryFileName}</span>
                      <Badge variant="secondary" className="text-[10px] px-1.5 py-0 shrink-0">From Library</Badge>
                    </>
                  ) : (
                    <>
                      <Upload className="h-4 w-4 text-muted-foreground shrink-0" />
                      <span className="text-sm font-medium truncate">{f.name}</span>
                      <span className="text-xs text-muted-foreground shrink-0">
                        ({(f.size / 1024).toFixed(1)} KB)
                      </span>
                    </>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 shrink-0"
                  onClick={() => removeFile(idx)}
                  aria-label={`Remove ${isLibraryFileRef(f) ? f._libraryFileName : f.name}`}
                >
                  <X className="h-3 w-3" />
                </Button>
              </div>
            ))}
            <div className="px-3 py-2 text-xs text-muted-foreground">
              {files.length} file{files.length !== 1 ? 's' : ''}
              {totalSize > 0 && `, ${(totalSize / (1024 * 1024)).toFixed(2)} MB total`}
            </div>
          </div>
        )}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files && e.target.files.length > 0) {
              addFiles(Array.from(e.target.files))
              e.target.value = ''
            }
          }}
        />
      </div>
    )
  }

  if (input.type === 'file') {
    const file = value instanceof File ? value : null
    const libraryRef = isLibraryFileRef(value) ? value : null
    const hasValue = file || libraryRef

    return (
      <div className="space-y-2">
        <Label>{input.label || input.name}{input.required ? ' *' : ''}</Label>
        {input.description && (
          <p className="text-xs text-muted-foreground">{input.description}</p>
        )}
        {hasValue ? (
          <div className="border rounded-lg p-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              {libraryRef ? (
                <>
                  <Library className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm font-medium">{libraryRef._libraryFileName}</span>
                  <Badge variant="secondary" className="text-[10px] px-1.5 py-0">From Library</Badge>
                </>
              ) : (
                <>
                  <Upload className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm font-medium">{file!.name}</span>
                  <span className="text-xs text-muted-foreground">
                    ({(file!.size / 1024).toFixed(1)} KB)
                  </span>
                </>
              )}
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => onChange(null)}
              aria-label="Clear selected file"
            >
              <X className="h-3 w-3" />
            </Button>
          </div>
        ) : (
          <FileInputTabs
            fileInputRef={fileInputRef}
            isDragging={isDragging}
            setIsDragging={setIsDragging}
            onChange={onChange}
          />
        )}
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          onChange={(e) => {
            if (e.target.files && e.target.files.length > 0) onChange(e.target.files[0])
          }}
        />
      </div>
    )
  }

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
        list={isPathInput ? `datalist-${input.name}` : undefined}
      />
      {isPathInput && pathSuggestions.length > 0 && (
        <datalist id={`datalist-${input.name}`}>
          {pathSuggestions.map((p) => <option key={p} value={p} />)}
        </datalist>
      )}
    </div>
  )
}

function MultiFileInputTabs({
  onAddFiles,
  onAddLibraryFile,
}: {
  onAddFiles: (files: File[]) => void
  onAddLibraryFile: (ref: LibraryFileRef) => void
}) {
  const multiFileInputRef = useRef<HTMLInputElement>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [librarySearch, setLibrarySearch] = useState('')
  const [activeTab, setActiveTab] = useState('upload')
  const [selectedLibraryIds, setSelectedLibraryIds] = useState<Set<number>>(new Set())

  const { data: libraryFiles = [] } = useQuery({
    queryKey: ['file-library-for-multi-input'],
    queryFn: async () => {
      const { data } = await api.get('/api/files')
      return (data.files || []) as LibraryFile[]
    },
    enabled: activeTab === 'library',
  })

  const filtered = librarySearch
    ? libraryFiles.filter((f) => f.original_name.toLowerCase().includes(librarySearch.toLowerCase()))
    : libraryFiles

  const toggleLibrarySelection = (id: number) => {
    setSelectedLibraryIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const addSelectedLibraryFiles = () => {
    for (const f of libraryFiles) {
      if (selectedLibraryIds.has(f.id)) {
        onAddLibraryFile({
          _libraryFileId: f.id,
          _libraryFileName: f.original_name,
          _libraryFilePath: f.filename,
        })
      }
    }
    setSelectedLibraryIds(new Set())
  }

  return (
    <Tabs value={activeTab} onValueChange={setActiveTab}>
      <TabsList className="w-full">
        <TabsTrigger value="upload" className="flex-1"><Upload className="h-3 w-3 mr-1" /> Upload</TabsTrigger>
        <TabsTrigger value="library" className="flex-1"><Library className="h-3 w-3 mr-1" /> Library</TabsTrigger>
      </TabsList>

      <TabsContent value="upload">
        <div
          role="button"
          tabIndex={0}
          aria-label="Drop files here or click to browse"
          className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors ${
            isDragging ? 'border-primary bg-primary/5' : 'border-muted-foreground/25 hover:border-muted-foreground/50'
          }`}
          onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setIsDragging(false)
            if (e.dataTransfer.files.length > 0) onAddFiles(Array.from(e.dataTransfer.files))
          }}
          onClick={() => multiFileInputRef.current?.click()}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); multiFileInputRef.current?.click() } }}
        >
          <div className="space-y-1">
            <Upload className="h-8 w-8 mx-auto text-muted-foreground/50" />
            <p className="text-sm text-muted-foreground">Drag & drop or click to select files</p>
          </div>
        </div>
        <input
          ref={multiFileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files && e.target.files.length > 0) {
              onAddFiles(Array.from(e.target.files))
              e.target.value = ''
            }
          }}
        />
      </TabsContent>

      <TabsContent value="library">
        <div className="space-y-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="Search files..."
              value={librarySearch}
              onChange={(e) => setLibrarySearch(e.target.value)}
              className="pl-8 h-9"
            />
          </div>
          <div className="max-h-48 overflow-auto border rounded-md divide-y">
            {filtered.length === 0 ? (
              <p className="text-xs text-muted-foreground p-3 text-center">
                {libraryFiles.length === 0 ? 'No files in library' : 'No matching files'}
              </p>
            ) : (
              filtered.map((f) => (
                <label key={f.id} className="flex items-center gap-2 px-3 py-2 hover:bg-muted/50 cursor-pointer">
                  <Checkbox
                    checked={selectedLibraryIds.has(f.id)}
                    onCheckedChange={() => toggleLibrarySelection(f.id)}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">{f.original_name}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {(f.size_bytes / 1024).toFixed(1)} KB
                      {f.uploaded_at && ` \u00b7 ${new Date(f.uploaded_at).toLocaleDateString()}`}
                    </p>
                  </div>
                </label>
              ))
            )}
          </div>
          {selectedLibraryIds.size > 0 && (
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              onClick={addSelectedLibraryFiles}
            >
              Add {selectedLibraryIds.size} Selected
            </Button>
          )}
        </div>
      </TabsContent>
    </Tabs>
  )
}

function FileInputTabs({
  fileInputRef,
  isDragging,
  setIsDragging,
  onChange,
}: {
  fileInputRef: React.RefObject<HTMLInputElement | null>
  isDragging: boolean
  setIsDragging: (v: boolean) => void
  onChange: (val: any) => void
}) {
  const [librarySearch, setLibrarySearch] = useState('')
  const [activeTab, setActiveTab] = useState('upload')

  const { data: libraryFiles = [] } = useQuery({
    queryKey: ['file-library-for-input'],
    queryFn: async () => {
      const { data } = await api.get('/api/files')
      return (data.files || []) as LibraryFile[]
    },
    enabled: activeTab === 'library',
  })

  const filtered = librarySearch
    ? libraryFiles.filter((f) => f.original_name.toLowerCase().includes(librarySearch.toLowerCase()))
    : libraryFiles

  return (
    <Tabs value={activeTab} onValueChange={setActiveTab}>
      <TabsList className="w-full">
        <TabsTrigger value="upload" className="flex-1"><Upload className="h-3 w-3 mr-1" /> Upload</TabsTrigger>
        <TabsTrigger value="library" className="flex-1"><Library className="h-3 w-3 mr-1" /> Library</TabsTrigger>
      </TabsList>

      <TabsContent value="upload">
        <div
          role="button"
          tabIndex={0}
          aria-label="Drop a file here or click to browse"
          className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors ${
            isDragging ? 'border-primary bg-primary/5' : 'border-muted-foreground/25 hover:border-muted-foreground/50'
          }`}
          onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setIsDragging(false)
            if (e.dataTransfer.files.length > 0) onChange(e.dataTransfer.files[0])
          }}
          onClick={() => fileInputRef.current?.click()}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInputRef.current?.click() } }}
        >
          <div className="space-y-1">
            <Upload className="h-8 w-8 mx-auto text-muted-foreground/50" />
            <p className="text-sm text-muted-foreground">Drag & drop or click to select a file</p>
          </div>
        </div>
      </TabsContent>

      <TabsContent value="library">
        <div className="space-y-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="Search files..."
              value={librarySearch}
              onChange={(e) => setLibrarySearch(e.target.value)}
              className="pl-8 h-9"
            />
          </div>
          <div className="max-h-48 overflow-auto border rounded-md divide-y">
            {filtered.length === 0 ? (
              <p className="text-xs text-muted-foreground p-3 text-center">
                {libraryFiles.length === 0 ? 'No files in library' : 'No matching files'}
              </p>
            ) : (
              filtered.map((f) => (
                <div key={f.id} className="flex items-center justify-between px-3 py-2 hover:bg-muted/50">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">{f.original_name}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {(f.size_bytes / 1024).toFixed(1)} KB
                      {f.uploaded_at && ` \u00b7 ${new Date(f.uploaded_at).toLocaleDateString()}`}
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    className="ml-2 h-7 text-xs shrink-0"
                    onClick={() => onChange({
                      _libraryFileId: f.id,
                      _libraryFileName: f.original_name,
                      _libraryFilePath: f.filename,
                    } satisfies LibraryFileRef)}
                  >
                    Select
                  </Button>
                </div>
              ))
            )}
          </div>
        </div>
      </TabsContent>
    </Tabs>
  )
}
