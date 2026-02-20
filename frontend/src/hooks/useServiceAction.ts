import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import api from '@/lib/api'
import type { ServiceScript } from '@/types'

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
      // Check if any input values are File objects
      const hasFiles = Object.values(inputs).some((v) => v instanceof File)

      if (hasFiles) {
        const formData = new FormData()
        formData.append('script', script)

        const nonFileInputs: Record<string, any> = {}
        for (const [key, val] of Object.entries(inputs)) {
          if (val instanceof File) {
            formData.append(`file__${key}`, val)
          } else {
            nonFileInputs[key] = val
          }
        }
        formData.append('inputs', JSON.stringify(nonFileInputs))

        return api.post(`/api/services/${serviceName}/run-with-files`, formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
      }

      return api.post(`/api/services/${serviceName}/run`, { script, inputs })
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
    const processed: Record<string, any> = {}
    for (const [key, val] of Object.entries(scriptInputs)) {
      if (val instanceof File) {
        processed[key] = val
      } else if (Array.isArray(val)) {
        processed[key] = val.filter((v: string) => v.trim() !== '')
      } else {
        processed[key] = val
      }
    }

    if (scriptModal.objId > 0) {
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
    isPending: runActionMutation.isPending || runServiceScriptMutation.isPending,
  }
}
