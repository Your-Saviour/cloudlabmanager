import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import api from '@/lib/api'
import type { ServiceScript } from '@/types'
import { isLibraryFileRef } from '@/components/shared/ScriptInputField'

interface ModalState {
  serviceName: string
  objId: number // -1 when no inventory object exists
  script: ServiceScript
}

export function useServiceAction() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [dryRunModal, setDryRunModal] = useState<ModalState | null>(null)
  const [scriptModal, setScriptModal] = useState<ModalState | null>(null)
  const [scriptInputs, setScriptInputs] = useState<Record<string, any>>({})
  const [saveToLibrary, setSaveToLibrary] = useState(true)

  const runActionMutation = useMutation({
    mutationFn: ({ objId, actionName, body }: { objId: number; actionName: string; body?: any }) =>
      api.post(`/api/inventory/service/${objId}/actions/${actionName}`, body || {}),
    onSuccess: (res) => {
      if (res.data.job_id) {
        toast.success('Action started')
        navigate(`/jobs/${res.data.job_id}`)
      } else {
        toast.success('Action completed')
        queryClient.invalidateQueries({ queryKey: ['active-deployments'] })
      }
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Action failed'),
  })

  const runServiceScriptMutation = useMutation({
    mutationFn: ({ serviceName, script, inputs }: { serviceName: string; script: string; inputs: Record<string, any> }) => {
      // Check if any input values are File objects (including inside arrays for multi_file)
      const hasFiles = Object.values(inputs).some((v) => {
        if (v instanceof File) return true
        if (Array.isArray(v)) return v.some((item) => item instanceof File)
        return false
      })

      if (hasFiles) {
        const formData = new FormData()
        formData.append('script', script)

        const nonFileInputs: Record<string, any> = {}
        for (const [key, val] of Object.entries(inputs)) {
          if (val instanceof File) {
            formData.append(`file__${key}`, val)
          } else if (isLibraryFileRef(val)) {
            nonFileInputs[key] = { library_file_id: val._libraryFileId }
          } else if (Array.isArray(val)) {
            // Multi-file array: separate File objects and library refs
            const libraryRefs: { library_file_id: number }[] = []
            let fileIdx = 0
            for (const item of val) {
              if (item instanceof File) {
                formData.append(`file__${key}__${fileIdx}`, item)
                fileIdx++
              } else if (isLibraryFileRef(item)) {
                libraryRefs.push({ library_file_id: item._libraryFileId })
              }
            }
            if (libraryRefs.length > 0) {
              nonFileInputs[key] = libraryRefs
            }
          } else {
            nonFileInputs[key] = val
          }
        }
        formData.append('inputs', JSON.stringify(nonFileInputs))
        formData.append('save_to_library', saveToLibrary ? 'true' : 'false')

        return api.post(`/api/services/${serviceName}/run-with-files`, formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
      }

      // Convert library refs to { library_file_id } for JSON body
      const processedInputs: Record<string, any> = {}
      for (const [key, val] of Object.entries(inputs)) {
        if (isLibraryFileRef(val)) {
          processedInputs[key] = { library_file_id: val._libraryFileId }
        } else if (Array.isArray(val) && val.length > 0 && isLibraryFileRef(val[0])) {
          processedInputs[key] = val.map((item) =>
            isLibraryFileRef(item) ? { library_file_id: item._libraryFileId } : item
          )
        } else {
          processedInputs[key] = val
        }
      }

      return api.post(`/api/services/${serviceName}/run`, { script, inputs: processedInputs })
    },
    onSuccess: (res) => {
      if (res.data.job_id) {
        toast.success('Action started')
        navigate(`/jobs/${res.data.job_id}`)
      }
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Action failed'),
  })

  const triggerAction = (serviceName: string, objId: number | undefined, script: ServiceScript) => {
    if (script.inputs && script.inputs.length > 0) {
      // Scripts with inputs always show the input modal first
      const defaults: Record<string, any> = {}
      script.inputs.forEach((inp) => {
        if (inp.type === 'list') defaults[inp.name] = inp.default ? [inp.default] : ['']
        else if (inp.type === 'ssh_key_select') defaults[inp.name] = []
        else if (inp.type === 'multi_file') defaults[inp.name] = []
        else if (inp.type === 'file') defaults[inp.name] = null
        else if (inp.default) defaults[inp.name] = inp.default
      })
      setScriptInputs(defaults)
      setScriptModal({ serviceName, objId: objId ?? -1, script })
    } else if (script.name === 'deploy') {
      if (objId) {
        setDryRunModal({ serviceName, objId, script })
      } else {
        runServiceScriptMutation.mutate({ serviceName, script: 'deploy', inputs: {} })
      }
    } else {
      if (objId) {
        runActionMutation.mutate({
          objId,
          actionName: 'run_script',
          body: { script: script.name, inputs: {} },
        })
      } else {
        runServiceScriptMutation.mutate({ serviceName, script: script.name, inputs: {} })
      }
    }
  }

  const confirmDeploy = () => {
    if (!dryRunModal) return
    if (dryRunModal.objId > 0) {
      runActionMutation.mutate({
        objId: dryRunModal.objId,
        actionName: 'run_script',
        body: { script: dryRunModal.script.name, inputs: {} },
      })
    } else {
      runServiceScriptMutation.mutate({
        serviceName: dryRunModal.serviceName,
        script: dryRunModal.script.name,
        inputs: {},
      })
    }
    setDryRunModal(null)
  }

  const submitScriptInputs = () => {
    if (!scriptModal) return

    // Save path-like inputs to localStorage history
    const script = scriptModal.script
    script.inputs?.forEach((inp) => {
      if (inp.type === 'text' && inp.default?.includes('/')) {
        const val = scriptInputs[inp.name]
        if (typeof val === 'string' && val.trim()) {
          const key = `clm_path_history_${scriptModal.serviceName}`
          try {
            const history: string[] = JSON.parse(localStorage.getItem(key) || '[]')
            const updated = [val, ...history.filter((p) => p !== val)].slice(0, 5)
            localStorage.setItem(key, JSON.stringify(updated))
          } catch {}
        }
      }
    })

    const processed: Record<string, any> = {}
    for (const [key, val] of Object.entries(scriptInputs)) {
      if (val instanceof File || isLibraryFileRef(val)) {
        processed[key] = val
      } else if (Array.isArray(val)) {
        // Multi-file arrays: keep File/LibraryRef items, filter empty strings from list inputs
        const hasFileItems = val.some((v) => v instanceof File || isLibraryFileRef(v))
        if (hasFileItems) {
          processed[key] = val.filter((v) => v instanceof File || isLibraryFileRef(v))
        } else {
          processed[key] = val.filter((v: string) => typeof v === 'string' ? v.trim() !== '' : true)
        }
      } else {
        processed[key] = val
      }
    }

    // Only actual File objects require FormData path (library refs are JSON-safe)
    const hasFiles = Object.values(processed).some((v) => {
      if (v instanceof File) return true
      if (Array.isArray(v)) return v.some((item) => item instanceof File)
      return false
    })

    if (scriptModal.objId > 0 && !hasFiles) {
      runActionMutation.mutate({
        objId: scriptModal.objId,
        actionName: 'run_script',
        body: { script: scriptModal.script.name, inputs: processed },
      })
    } else {
      runServiceScriptMutation.mutate({
        serviceName: scriptModal.serviceName,
        script: scriptModal.script.name,
        inputs: processed,
      })
    }
    setScriptModal(null)
  }

  const dismissModals = () => {
    setDryRunModal(null)
    setScriptModal(null)
  }

  return {
    triggerAction,
    confirmDeploy,
    submitScriptInputs,
    dismissModals,
    dryRunModal,
    scriptModal,
    scriptInputs,
    setScriptInputs,
    saveToLibrary,
    setSaveToLibrary,
    isPending: runActionMutation.isPending || runServiceScriptMutation.isPending,
  }
}
