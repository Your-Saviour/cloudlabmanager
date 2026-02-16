import { useState, useEffect } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Save, FileText, History, Shield, FolderOpen, Upload, Trash2, Download, Pencil, X } from 'lucide-react'
import api from '@/lib/api'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { toast } from 'sonner'
import ConfigVersionHistory from '@/components/config/ConfigVersionHistory'
import ServicePermissions from '@/components/services/ServicePermissions'
import { useHasPermission } from '@/lib/permissions'

interface ConfigFile {
  name: string
  exists: boolean
}

interface ServiceFile {
  name: string
  size: number
  modified: string
}

const MAX_EDIT_SIZE = 102400 // 100KB

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function ServiceConfigPage() {
  const { name } = useParams<{ name: string }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const [activeFile, setActiveFile] = useState<string>('')
  const [content, setContent] = useState('')
  const [dirty, setDirty] = useState(false)
  const [changeNote, setChangeNote] = useState('')
  const canManageACL = useHasPermission('inventory.acl.manage')
  const canFiles = useHasPermission('services.files.view')

  const tabParam = searchParams.get('tab')
  const defaultTab = tabParam === 'permissions' && canManageACL
    ? 'permissions'
    : tabParam === 'files' && canFiles
      ? 'files'
      : 'config'

  // --- Config state ---
  const { data: configData, isLoading } = useQuery({
    queryKey: ['service', name, 'configs'],
    queryFn: async () => {
      const { data } = await api.get(`/api/services/${name}/configs`)
      return data as { configs: ConfigFile[]; service_dir: string }
    },
    enabled: !!name,
  })

  const configs = (configData?.configs || []).filter((c) => c.exists)

  useEffect(() => {
    if (configs.length > 0 && !activeFile) {
      setActiveFile(configs[0].name)
    }
  }, [configs.length])

  const { data: fileContent, isLoading: fileLoading } = useQuery({
    queryKey: ['service', name, 'config', activeFile],
    queryFn: async () => {
      const { data } = await api.get(`/api/services/${name}/configs/${activeFile}`)
      return data.content as string
    },
    enabled: !!name && !!activeFile,
  })

  useEffect(() => {
    if (fileContent !== undefined && !dirty) {
      setContent(fileContent)
    }
  }, [fileContent])

  const saveMutation = useMutation({
    mutationFn: () => api.put(`/api/services/${name}/configs/${activeFile}`, {
      content,
      change_note: changeNote || undefined,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['service', name, 'config', activeFile] })
      queryClient.invalidateQueries({ queryKey: ['service', name, 'config', activeFile, 'versions'] })
      setDirty(false)
      setChangeNote('')
      toast.success('Config saved')
    },
    onError: () => toast.error('Save failed'),
  })

  const selectFile = (fileName: string) => {
    setActiveFile(fileName)
    setDirty(false)
    setChangeNote('')
  }

  // --- Files state ---
  const subdirs = ['inputs', 'outputs']
  const [activeDir, setActiveDir] = useState('inputs')
  const [deleteFileName, setDeleteFileName] = useState<string | null>(null)
  const [editingFileName, setEditingFileName] = useState<string | null>(null)
  const [editFileContent, setEditFileContent] = useState('')
  const [editFileDirty, setEditFileDirty] = useState(false)

  const { data: files = [], isLoading: filesLoading } = useQuery({
    queryKey: ['service', name, 'files', activeDir],
    queryFn: async () => {
      const { data } = await api.get(`/api/services/${name}/files/${activeDir}`)
      return (data.files || []) as ServiceFile[]
    },
    enabled: !!name && canFiles,
  })

  const deleteFileMutation = useMutation({
    mutationFn: (filename: string) => api.delete(`/api/services/${name}/files/${activeDir}/${filename}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['service', name, 'files', activeDir] })
      setDeleteFileName(null)
      toast.success('File deleted')
    },
    onError: () => toast.error('Delete failed'),
  })

  const saveFileMutation = useMutation({
    mutationFn: ({ filename, content }: { filename: string; content: string }) =>
      api.put(`/api/services/${name}/files/${activeDir}/${filename}`, { content }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['service', name, 'files', activeDir] })
      setEditFileDirty(false)
      toast.success('File saved')
    },
    onError: () => toast.error('Save failed'),
  })

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const formData = new FormData()
    formData.append('file', file)
    try {
      await api.post(`/api/services/${name}/files/${activeDir}`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      queryClient.invalidateQueries({ queryKey: ['service', name, 'files', activeDir] })
      toast.success('File uploaded')
    } catch {
      toast.error('Upload failed')
    }
    e.target.value = ''
  }

  const handleDownload = async (filename: string) => {
    try {
      const { data } = await api.get(`/api/services/${name}/files/${activeDir}/${filename}`, {
        responseType: 'blob',
      })
      const url = URL.createObjectURL(data)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      toast.error('Download failed')
    }
  }

  const handleEditFile = async (filename: string) => {
    try {
      const { data } = await api.get(`/api/services/${name}/files/${activeDir}/${filename}`, {
        responseType: 'text',
        transformResponse: [(data: string) => data],
      })
      setEditFileContent(data)
      setEditingFileName(filename)
      setEditFileDirty(false)
    } catch {
      toast.error('Could not load file')
    }
  }

  const handleSaveFileEdit = () => {
    if (!editingFileName) return
    saveFileMutation.mutate({ filename: editingFileName, content: editFileContent })
  }

  const handleCloseFileEdit = () => {
    setEditingFileName(null)
    setEditFileContent('')
    setEditFileDirty(false)
  }

  const switchDir = (dir: string) => {
    setActiveDir(dir)
    handleCloseFileEdit()
  }

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <Button variant="ghost" size="icon" onClick={() => navigate('/services')} aria-label="Back to services">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <h1 className="text-2xl font-semibold tracking-tight">{name}</h1>
          <p className="text-sm text-muted-foreground">Configuration, files, and permissions</p>
        </div>
        {dirty && (
          <Button size="sm" onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
            <Save className="mr-2 h-3 w-3" /> Save
          </Button>
        )}
      </div>

      <Tabs defaultValue={defaultTab}>
        <TabsList>
          <TabsTrigger value="config">Configuration</TabsTrigger>
          {canFiles && (
            <TabsTrigger value="files">
              <FolderOpen className="mr-1 h-3 w-3" /> Files
            </TabsTrigger>
          )}
          {canManageACL && (
            <TabsTrigger value="permissions">
              <Shield className="mr-1 h-3 w-3" /> Permissions
            </TabsTrigger>
          )}
        </TabsList>

        {/* Config Tab */}
        <TabsContent value="config" className="mt-4">
          {isLoading ? (
            <Skeleton className="h-96 w-full" />
          ) : configs.length === 0 ? (
            <Card>
              <CardContent className="pt-6">
                <p className="text-sm text-muted-foreground text-center py-6">No config files found for this service.</p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-[200px_1fr] gap-4">
              <Card>
                <CardContent className="pt-4">
                  <nav className="space-y-1">
                    {configs.map((file) => (
                      <button
                        key={file.name}
                        className={`flex items-center gap-2 w-full px-3 py-2 rounded-md text-sm transition-colors ${
                          activeFile === file.name ? 'bg-primary/10 text-primary' : 'hover:bg-muted/50 text-muted-foreground'
                        }`}
                        onClick={() => selectFile(file.name)}
                      >
                        <FileText className="h-3 w-3" />
                        {file.name}
                      </button>
                    ))}
                  </nav>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="pt-4">
                  <Tabs defaultValue="editor">
                    <TabsList>
                      <TabsTrigger value="editor">Editor</TabsTrigger>
                      <TabsTrigger value="history">
                        <History className="mr-1 h-3 w-3" /> History
                      </TabsTrigger>
                    </TabsList>
                    <TabsContent value="editor" className="mt-4">
                      {fileLoading ? (
                        <Skeleton className="h-96 w-full" />
                      ) : (
                        <>
                          <textarea
                            className="w-full h-[500px] bg-black/30 rounded-md p-4 font-mono text-xs text-foreground resize-none border border-border focus:outline-none focus:ring-1 focus:ring-primary"
                            value={content}
                            onChange={(e) => { setContent(e.target.value); setDirty(true) }}
                            spellCheck={false}
                            aria-label={`Edit ${activeFile}`}
                          />
                          {dirty && (
                            <input
                              type="text"
                              className="mt-2 w-full bg-transparent border border-border rounded-md px-3 py-2 text-xs text-muted-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary"
                              placeholder="Change note (optional)"
                              aria-label="Change note"
                              value={changeNote}
                              onChange={(e) => setChangeNote(e.target.value)}
                            />
                          )}
                        </>
                      )}
                    </TabsContent>
                    <TabsContent value="history" className="mt-4">
                      <ConfigVersionHistory
                        serviceName={name!}
                        filename={activeFile}
                        onRestore={() => {
                          queryClient.invalidateQueries({ queryKey: ['service', name, 'config', activeFile] })
                          setDirty(false)
                        }}
                      />
                    </TabsContent>
                  </Tabs>
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>

        {/* Files Tab */}
        {canFiles && (
          <TabsContent value="files" className="mt-4">
            <div className="flex items-center justify-between mb-4">
              <div className="flex gap-2">
                {subdirs.map((dir) => (
                  <Button
                    key={dir}
                    variant={activeDir === dir ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => switchDir(dir)}
                  >
                    <FolderOpen className="mr-2 h-3 w-3" /> {dir}
                  </Button>
                ))}
              </div>
              <label className="cursor-pointer">
                <input type="file" className="hidden" onChange={handleUpload} />
                <Button size="sm" asChild>
                  <span><Upload className="mr-2 h-3 w-3" /> Upload</span>
                </Button>
              </label>
            </div>

            <Card>
              <CardContent className="pt-4">
                {filesLoading ? (
                  <div className="space-y-2">
                    {[1, 2, 3].map((i) => <Skeleton key={i} className="h-10 w-full" />)}
                  </div>
                ) : files.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-8">No files in {activeDir}/</p>
                ) : (
                  <div className="space-y-1">
                    {files.map((file) => (
                      <div key={file.name} className="flex items-center justify-between px-3 py-2 rounded-md hover:bg-muted/30">
                        <div className="flex items-center gap-3 flex-1 min-w-0">
                          <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                          <span className="text-sm truncate">{file.name}</span>
                          <span className="text-xs text-muted-foreground shrink-0">{formatSize(file.size)}</span>
                        </div>
                        <div className="flex gap-1">
                          {file.size <= MAX_EDIT_SIZE && (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7"
                              onClick={() => handleEditFile(file.name)}
                              title="Edit"
                            >
                              <Pencil className="h-3 w-3" />
                            </Button>
                          )}
                          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => handleDownload(file.name)} title="Download">
                            <Download className="h-3 w-3" />
                          </Button>
                          <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => setDeleteFileName(file.name)} title="Delete">
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Inline File Editor */}
            {editingFileName && (
              <Card className="mt-4">
                <CardContent className="pt-4">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-muted-foreground" />
                      <span className="text-sm font-medium">{editingFileName}</span>
                      {editFileDirty && <span className="text-xs text-muted-foreground">(modified)</span>}
                    </div>
                    <div className="flex gap-2">
                      <Button variant="outline" size="sm" onClick={handleCloseFileEdit}>
                        <X className="mr-1 h-3 w-3" /> Cancel
                      </Button>
                      <Button
                        size="sm"
                        onClick={handleSaveFileEdit}
                        disabled={!editFileDirty || saveFileMutation.isPending}
                      >
                        <Save className="mr-1 h-3 w-3" /> {saveFileMutation.isPending ? 'Saving...' : 'Save'}
                      </Button>
                    </div>
                  </div>
                  <textarea
                    className="w-full h-[400px] bg-black/30 rounded-md p-4 font-mono text-xs text-foreground resize-none border border-border focus:outline-none focus:ring-1 focus:ring-primary"
                    value={editFileContent}
                    onChange={(e) => { setEditFileContent(e.target.value); setEditFileDirty(true) }}
                    spellCheck={false}
                  />
                </CardContent>
              </Card>
            )}

            <ConfirmDialog
              open={!!deleteFileName}
              onOpenChange={() => setDeleteFileName(null)}
              title="Delete File"
              description={`Delete "${deleteFileName}"? This cannot be undone.`}
              confirmLabel="Delete"
              variant="destructive"
              onConfirm={() => deleteFileName && deleteFileMutation.mutate(deleteFileName)}
            />
          </TabsContent>
        )}

        {/* Permissions Tab */}
        {canManageACL && (
          <TabsContent value="permissions" className="mt-4">
            <ServicePermissions serviceName={name!} />
          </TabsContent>
        )}
      </Tabs>
    </div>
  )
}
