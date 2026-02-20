import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { HelpCircle, MessageSquare, Bug, ListTodo, ArrowUpCircle, CheckCircle2 } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { SubmitFeedbackModal } from '@/components/feedback/SubmitFeedbackModal'
import api from '@/lib/api'

interface RepoStatus {
  current_commit: string | null
  latest_commit: string | null
  update_available: boolean
  commits_behind?: number
  last_checked: string
  error?: string
}

interface UpdateStatus {
  cloudlab: RepoStatus
  cloudlabmanager: RepoStatus
}

export function HelpMenu() {
  const navigate = useNavigate()
  const [submitOpen, setSubmitOpen] = useState(false)
  const [submitType, setSubmitType] = useState<
    'feature_request' | 'bug_report'
  >('feature_request')

  const { data: updates } = useQuery<UpdateStatus>({
    queryKey: ['system-updates'],
    queryFn: async () => {
      const { data } = await api.get('/api/system/updates')
      return data
    },
    staleTime: 5 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
  })

  const hasUpdates =
    updates?.cloudlab?.update_available || updates?.cloudlabmanager?.update_available

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label="Help menu" className="relative">
            <HelpCircle className="h-5 w-5" />
            {hasUpdates && (
              <span
                aria-hidden="true"
                className="absolute top-1 right-1 h-2 w-2 rounded-full bg-amber-400"
              />
            )}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          {updates && (updates.cloudlab || updates.cloudlabmanager) && (
            <>
              <DropdownMenuLabel className="text-xs text-muted-foreground">
                Updates
              </DropdownMenuLabel>
              {updates.cloudlab && (
                <DropdownMenuItem className="gap-2 cursor-default" onSelect={(e) => e.preventDefault()}>
                  {updates.cloudlab.update_available ? (
                    <ArrowUpCircle className="h-4 w-4 text-amber-400" />
                  ) : (
                    <CheckCircle2 className="h-4 w-4 text-green-400" />
                  )}
                  <div className="flex flex-col">
                    <span className="text-sm">CloudLab</span>
                    <span className="text-xs text-muted-foreground">
                      {updates.cloudlab.error
                        ? 'Check failed'
                        : updates.cloudlab.update_available
                          ? `${updates.cloudlab.commits_behind} commit${updates.cloudlab.commits_behind === 1 ? '' : 's'} behind`
                          : 'Up to date'}
                    </span>
                  </div>
                </DropdownMenuItem>
              )}
              {updates.cloudlabmanager && (
                <DropdownMenuItem className="gap-2 cursor-default" onSelect={(e) => e.preventDefault()}>
                  {updates.cloudlabmanager.update_available ? (
                    <ArrowUpCircle className="h-4 w-4 text-amber-400" />
                  ) : updates.cloudlabmanager.current_commit === 'unknown' ? (
                    <HelpCircle className="h-4 w-4 text-muted-foreground" />
                  ) : (
                    <CheckCircle2 className="h-4 w-4 text-green-400" />
                  )}
                  <div className="flex flex-col">
                    <span className="text-sm">CLM</span>
                    <span className="text-xs text-muted-foreground">
                      {updates.cloudlabmanager.error
                        ? 'Check failed'
                        : updates.cloudlabmanager.update_available
                          ? 'Update available'
                          : updates.cloudlabmanager.current_commit === 'unknown'
                            ? `Latest: ${updates.cloudlabmanager.latest_commit ?? '?'}`
                            : 'Up to date'}
                    </span>
                  </div>
                </DropdownMenuItem>
              )}
              <DropdownMenuSeparator />
            </>
          )}
          <DropdownMenuItem
            onClick={() => {
              setSubmitType('feature_request')
              setSubmitOpen(true)
            }}
          >
            <MessageSquare className="mr-2 h-4 w-4" />
            Request a Feature
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => {
              setSubmitType('bug_report')
              setSubmitOpen(true)
            }}
          >
            <Bug className="mr-2 h-4 w-4" />
            Report a Bug
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => navigate('/feedback')}>
            <ListTodo className="mr-2 h-4 w-4" />
            View Feedback
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <SubmitFeedbackModal
        open={submitOpen}
        onClose={() => setSubmitOpen(false)}
        type={submitType}
      />
    </>
  )
}
