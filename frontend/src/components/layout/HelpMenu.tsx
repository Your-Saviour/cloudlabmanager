import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { HelpCircle, MessageSquare, Bug, ListTodo } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { SubmitFeedbackModal } from '@/components/feedback/SubmitFeedbackModal'

export function HelpMenu() {
  const navigate = useNavigate()
  const [submitOpen, setSubmitOpen] = useState(false)
  const [submitType, setSubmitType] = useState<
    'feature_request' | 'bug_report'
  >('feature_request')

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label="Help menu">
            <HelpCircle className="h-5 w-5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-48">
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
