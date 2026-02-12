import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Save, Key, User, Download, Copy } from 'lucide-react'
import api from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'
import { PageHeader } from '@/components/shared/PageHeader'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { toast } from 'sonner'

export default function ProfilePage() {
  const queryClient = useQueryClient()
  const user = useAuthStore((s) => s.user)

  const [displayName, setDisplayName] = useState(user?.display_name || '')
  const [email, setEmail] = useState(user?.email || '')

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')

  const [privateKeyDialog, setPrivateKeyDialog] = useState<string | null>(null)
  const [regenConfirmOpen, setRegenConfirmOpen] = useState(false)

  const { data: existingKey } = useQuery({
    queryKey: ['ssh-key'],
    queryFn: async () => {
      const { data } = await api.get('/api/auth/me/ssh-key')
      return data.ssh_public_key as string | null
    },
  })

  const updateProfileMutation = useMutation({
    mutationFn: () => api.put('/api/auth/me', { display_name: displayName, email }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['auth', 'me'] })
      toast.success('Profile updated')
    },
    onError: () => toast.error('Update failed'),
  })

  const changePasswordMutation = useMutation({
    mutationFn: () =>
      api.post('/api/auth/change-password', {
        current_password: currentPassword,
        new_password: newPassword,
      }),
    onSuccess: () => {
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      toast.success('Password changed')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Password change failed'),
  })

  const generateKeyMutation = useMutation({
    mutationFn: () => api.post('/api/auth/me/ssh-key'),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['ssh-key'] })
      const privateKey = res.data.private_key
      if (privateKey) {
        setPrivateKeyDialog(privateKey)
      } else {
        toast.success('SSH key generated')
      }
    },
    onError: () => toast.error('Key generation failed'),
  })

  const deleteKeyMutation = useMutation({
    mutationFn: () => api.delete('/api/auth/me/ssh-key'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ssh-key'] })
      toast.success('SSH key removed')
    },
    onError: () => toast.error('Remove failed'),
  })

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    toast.success('Copied to clipboard')
  }

  const downloadPrivateKey = (key: string) => {
    const blob = new Blob([key], { type: 'application/x-pem-file' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'cloudlab_key.pem'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  return (
    <div>
      <PageHeader title="Profile" description="Manage your account settings" />

      <div className="grid gap-6 max-w-2xl">
        {/* Profile Info */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <User className="h-4 w-4" /> Profile Information
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Username</Label>
              <Input value={user?.username || ''} disabled />
            </div>
            <div className="space-y-2">
              <Label>Display Name</Label>
              <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>Email</Label>
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <Button size="sm" onClick={() => updateProfileMutation.mutate()} disabled={updateProfileMutation.isPending}>
              <Save className="mr-2 h-3 w-3" /> Save
            </Button>
          </CardContent>
        </Card>

        {/* Change Password */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Key className="h-4 w-4" /> Change Password
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Current Password</Label>
              <Input type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>New Password</Label>
              <Input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>Confirm New Password</Label>
              <Input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} />
            </div>
            {newPassword && confirmPassword && newPassword !== confirmPassword && (
              <p className="text-sm text-destructive">Passwords do not match</p>
            )}
            <Button
              size="sm"
              onClick={() => changePasswordMutation.mutate()}
              disabled={!currentPassword || !newPassword || newPassword !== confirmPassword || changePasswordMutation.isPending}
            >
              Change Password
            </Button>
          </CardContent>
        </Card>

        {/* SSH Key */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">SSH Key</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {existingKey ? (
              <>
                <div className="bg-muted/30 rounded-md p-3 font-mono text-xs break-all">
                  {existingKey}
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setRegenConfirmOpen(true)}
                    disabled={generateKeyMutation.isPending}
                  >
                    Regenerate Key
                  </Button>
                  <Button size="sm" variant="destructive" onClick={() => deleteKeyMutation.mutate()}>
                    Remove Key
                  </Button>
                </div>
              </>
            ) : (
              <div className="space-y-3">
                <p className="text-sm text-muted-foreground">
                  No SSH key configured. Generate one to enable SSH access to instances.
                </p>
                <Button
                  size="sm"
                  onClick={() => generateKeyMutation.mutate()}
                  disabled={generateKeyMutation.isPending}
                >
                  <Key className="mr-2 h-3 w-3" /> Generate SSH Key
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Private Key Dialog */}
      <Dialog open={!!privateKeyDialog} onOpenChange={() => setPrivateKeyDialog(null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>SSH Private Key</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-destructive font-medium">
              Save this private key now. It cannot be retrieved again.
            </p>
            <Textarea
              value={privateKeyDialog || ''}
              readOnly
              rows={12}
              className="font-mono text-xs"
            />
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => privateKeyDialog && copyToClipboard(privateKeyDialog)}
              >
                <Copy className="mr-2 h-3 w-3" /> Copy
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => privateKeyDialog && downloadPrivateKey(privateKeyDialog)}
              >
                <Download className="mr-2 h-3 w-3" /> Download .pem
              </Button>
            </div>
          </div>
          <DialogFooter>
            <Button onClick={() => setPrivateKeyDialog(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Regenerate Confirm */}
      <ConfirmDialog
        open={regenConfirmOpen}
        onOpenChange={setRegenConfirmOpen}
        title="Regenerate SSH Key"
        description="This will replace your current SSH key. The old key will stop working immediately. Continue?"
        confirmLabel="Regenerate"
        variant="destructive"
        onConfirm={() => {
          setRegenConfirmOpen(false)
          generateKeyMutation.mutate()
        }}
      />
    </div>
  )
}
